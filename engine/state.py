import os
import re
import json
import logging
import subprocess
from collections import deque

logger = logging.getLogger(__name__)

# ─────────────── JSON BACKING STORE 讀寫 ───────────────

def _state_json_path(control_path: str) -> str:
    if control_path.endswith(".json"):
        return control_path
    return os.path.join(os.path.dirname(control_path) or ".", "state.json")


def load_state_json(state_json_path: str) -> dict:
    if not os.path.exists(state_json_path):
        return {}
    try:
        with open(state_json_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load state JSON {state_json_path}: {e}")
        return {}


def save_state_json(state_json_path: str, data: dict):
    temp_path = state_json_path + ".tmp"
    try:
        os.makedirs(os.path.dirname(state_json_path) or ".", exist_ok=True)
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(temp_path, state_json_path)
    except Exception as e:
        logger.error(f"Failed to save state JSON {state_json_path}: {e}")
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


# ─────────────── key 映射白名單與校驗 ───────────────

STATIC_KEYS = {
    "current_phase", "plan_version", "framework_ref", "last_round_mode", "last_round_result",
    "last_round_fail_tasks", "rounds_since_progress", "stuck_level", "current_model_tier",
    "enhanced_rounds_used", "human_required", "human_required_reason", "human_required_msg",
    "review_invalid_streak", "last_safe_sha", "stop_condition_met", "blocking_issues",
    "tree_enabled", "tree_root", "tree_total_nodes", "tree_total_leaves", "tree_max_depth"
}


def _is_valid_key(key: str) -> bool:
    if key in STATIC_KEYS:
        return True
    if re.match(r"^p\d+_(consecutive_pass|total_validations|last_result)$", key):
        return True
    if key.startswith("node_"):
        fields = ("state", "children", "parent", "depth", "stable_rounds", "reflow_count", "depends_on")
        for f in fields:
            if key.endswith(f"_{f}"):
                return True
    if key.startswith("plan_"):
        return True
    return False


def get_val_from_json_data(data: dict, key: str) -> str | None:
    # 1. Root 欄位
    root_keys = {"schema_version", "mode", "current_phase", "plan_version", "framework_ref"}
    if key in root_keys:
        val = data.get(key)
        return str(val) if val is not None else None

    # 2. tree_enabled
    if key == "tree_enabled":
        return "true" if data.get("mode") == "tree" else "false"

    # 3. 樹全局欄位
    if key == "tree_root":
        return data.get("tree", {}).get("root")
    if key == "tree_total_nodes":
        return str(len(data.get("tree", {}).get("nodes", {})))
    if key == "tree_total_leaves":
        nodes = data.get("tree", {}).get("nodes", {})
        leaves = [n for n in nodes.values() if n.get("state") == "LEAF"]
        return str(len(leaves))
    if key == "tree_max_depth":
        nodes = data.get("tree", {}).get("nodes", {})
        depths = [n.get("depth", 0) for n in nodes.values()]
        return str(max(depths) if depths else 0)

    # 4. node_{node_id}_{field}
    if key.startswith("node_"):
        fields = ("state", "children", "parent", "depth", "stable_rounds", "reflow_count", "depends_on")
        for f in fields:
            suffix = f"_{f}"
            if key.endswith(suffix):
                node_id = key[5:-len(suffix)]
                node = data.get("tree", {}).get("nodes", {}).get(node_id)
                if node:
                    val = node.get(f)
                    if isinstance(val, list):
                        return ",".join(val)
                    return str(val) if val is not None else ""
                return None

    # 5. p{phase_id}_consecutive_pass 等計數器
    phase_pat = re.match(r"^p(\d+)_(consecutive_pass|total_validations|last_result)$", key)
    if phase_pat:
        phase_id = phase_pat.group(1)
        attr = phase_pat.group(2)
        phases = data.get("phases", [])
        for ph in phases:
            if str(ph.get("id")) == phase_id:
                val = ph.get(attr)
                return str(val) if val is not None else ""
        return None

    # 6. blocking_issues (重算)
    if key == "blocking_issues":
        issues = data.get("issues", [])
        blocking = [i for i in issues if i.get("status") == "OPEN" and i.get("level") == "BLOCKING"]
        return str(len(blocking))

    # 7. control 欄位
    control_keys = {
        "last_round_mode", "last_round_result", "last_round_fail_tasks",
        "rounds_since_progress", "stuck_level", "current_model_tier",
        "enhanced_rounds_used", "human_required", "human_required_reason",
        "human_required_msg", "review_invalid_streak", "last_safe_sha",
        "stop_condition_met"
    }
    if key in control_keys:
        val = data.get("control", {}).get(key)
        if isinstance(val, bool):
            return "true" if val else "false"
        return str(val) if val is not None else ""

    # 8. plan_ 前綴欄位
    if key.startswith("plan_"):
        attr = key[5:]
        val = data.get("plan", {}).get(attr)
        if isinstance(val, bool):
            return "true" if val else "false"
        return str(val) if val is not None else ""

    return None


def set_val_in_json_data(data: dict, key: str, value: str):
    def to_bool(v):
        return str(v).lower() == "true"
    
    def to_int(v):
        try:
            return int(v)
        except (ValueError, TypeError):
            return 0

    # 1. Root 欄位
    if key in {"schema_version", "mode", "current_phase", "plan_version", "framework_ref"}:
        if key in ("schema_version", "plan_version"):
            data[key] = to_int(value)
        else:
            data[key] = value
        return

    # 2. tree_enabled
    if key == "tree_enabled":
        data["mode"] = "tree" if to_bool(value) else "flat"
        return

    # 3. tree全局欄位
    if key == "tree_root":
        if "tree" not in data:
            data["tree"] = {"root": "", "nodes": {}}
        data["tree"]["root"] = value
        return

    # 4. node_{node_id}_{field}
    if key.startswith("node_"):
        fields = ("state", "children", "parent", "depth", "stable_rounds", "reflow_count", "depends_on")
        for f in fields:
            suffix = f"_{f}"
            if key.endswith(suffix):
                node_id = key[5:-len(suffix)]
                if "tree" not in data:
                    data["tree"] = {"root": "root", "nodes": {}}
                if "nodes" not in data["tree"]:
                    data["tree"]["nodes"] = {}
                if node_id not in data["tree"]["nodes"]:
                    data["tree"]["nodes"][node_id] = {}
                
                node = data["tree"]["nodes"][node_id]
                if f in ("children", "depends_on"):
                    node[f] = [c.strip() for c in value.split(",") if c.strip()]
                elif f in ("depth", "stable_rounds", "reflow_count"):
                    node[f] = to_int(value)
                else:
                    node[f] = value
                return

    # 5. p{phase_id}_consecutive_pass 等計數器
    phase_pat = re.match(r"^p(\d+)_(consecutive_pass|total_validations|last_result)$", key)
    if phase_pat:
        phase_id = phase_pat.group(1)
        attr = phase_pat.group(2)
        if "phases" not in data:
            data["phases"] = []
        
        target_ph = None
        for ph in data["phases"]:
            if str(ph.get("id")) == phase_id:
                target_ph = ph
                break
        
        if not target_ph:
            target_ph = {"id": phase_id, "name": f"Phase {phase_id}", "tasks": [], "coverage": []}
            data["phases"].append(target_ph)
            
        if attr in ("consecutive_pass", "total_validations"):
            target_ph[attr] = to_int(value)
        else:
            target_ph[attr] = value
        return

    # 6. control 欄位
    control_keys = {
        "last_round_mode", "last_round_result", "last_round_fail_tasks",
        "rounds_since_progress", "stuck_level", "current_model_tier",
        "enhanced_rounds_used", "human_required", "human_required_reason",
        "human_required_msg", "review_invalid_streak", "last_safe_sha",
        "stop_condition_met", "blocking_issues"
    }
    if key in control_keys:
        if "control" not in data:
            data["control"] = {}
        
        if key in ("rounds_since_progress", "stuck_level", "enhanced_rounds_used", "review_invalid_streak", "blocking_issues"):
            data["control"][key] = to_int(value)
        elif key in ("human_required", "stop_condition_met"):
            data["control"][key] = to_bool(value)
        else:
            data["control"][key] = value
        return

    # 7. plan_ 前綴欄位
    if key.startswith("plan_"):
        attr = key[5:]
        if "plan" not in data:
            data["plan"] = {}
        
        if attr in ("stable_rounds", "rounds_since_progress", "stuck_level", "enhanced_rounds_used", "version"):
            data["plan"][attr] = to_int(value)
        elif attr in ("human_required", "changed_last"):
            data["plan"][attr] = to_bool(value)
        else:
            data["plan"][attr] = value
        return

    # 8. 其餘暫存欄位
    if "extra" not in data:
        data["extra"] = {}
    data["extra"][key] = value


# ─────────────── API 進入點 ───────────────

def get_val(control: str, key: str) -> str | None:
    state_json = _state_json_path(control)
    if not os.path.exists(state_json):
        return None
    data = load_state_json(state_json)
    return get_val_from_json_data(data, key)


def set_val(control: str, key: str, value: str):
    state_json = _state_json_path(control)
    data = load_state_json(state_json)
    set_val_in_json_data(data, key, value)
    save_state_json(state_json, data)
    render_all(state_json)


def as_int(v, d=0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return d


# ─────────────── 自動渲染 Markdown 視圖 ───────────────

def render_all(state_json_path: str):
    pass



# ─────────────── 歷史與進度重建（從 rounds.jsonl 讀取） ───────────────

def reconstruct_history_and_progress(cfg: dict, maxlen: int) -> tuple:
    dq = deque(maxlen=maxlen)
    progress = {}
    p = rounds_log_path(cfg)
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except (json.JSONDecodeError, ValueError):
                        continue
                    if record.get("type") == "round_finished":
                        progress = {
                            "sig": record.get("progress_sig") or "",
                            "idle": str(record.get("idle_rounds") or 0),
                            "killed_streak": str(record.get("killed_streak") or 0),
                            "phase": str(record.get("phase") or ""),
                            "last_pass": str(record.get("consecutive_pass") or 0)
                        }
                        
                        mode = record.get("mode") or ""
                        result = record.get("result") or ""
                        is_fail_verify = (not record.get("killed")) and ("驗證" in mode) and (result == "FAIL")
                        if is_fail_verify:
                            fp = record.get("fail_fingerprint")
                            if fp:
                                dq.append(fp)
                        
                        if record.get("progressed"):
                            dq.clear()
        except OSError as e:
            logger.warning(f"Failed to reconstruct history and progress from rounds.jsonl: {e}")
    return dq, progress


def progress_signature(cfg: dict, control: str) -> str:
    from git_utils import git_head
    phase = get_val(control, "current_phase") or ""
    total_pass = 0
    for ph in (cfg.get("phases") or []):
        total_pass += as_int(get_val(control, f"p{ph.get('id')}_consecutive_pass"))
    return f"{phase}|{total_pass}|{git_head()}"


def rounds_log_path(cfg: dict) -> str:
    return os.path.join(cfg["runtime"]["state_dir"], "rounds.jsonl")


def append_round_record(cfg: dict, record: dict) -> None:
    p = rounds_log_path(cfg)
    try:
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        line = json.dumps(record, ensure_ascii=False) + "\n"
        with open(p, "a", encoding="utf-8") as f:
            f.write(line)
    except (OSError, TypeError, ValueError) as e:
        logger.warning(f"Failed to append round record: {e}")


def check_stop_requested(cfg: dict, log_both=None) -> bool:
    from datetime import datetime
    p = os.path.join(cfg["runtime"]["state_dir"], "stop_requested")
    if os.path.exists(p):
        try:
            os.remove(p)
        except OSError:
            pass
        msg = "✋ [Cooperative Stop] 偵測到協同式停機請求，正在優雅釋放資源並關閉..."
        if log_both:
            log_both(msg)
        else:
            print(msg, flush=True)
            
        append_round_record(cfg, {
            "run_id": cfg.get("run_id"),
            "ts": datetime.now().strftime("%F %T"),
            "type": "stop_requested",
            "message": "Cooperative stop requested by user."
        })
        return True
    return False


def set_human_required(control: str, required: bool, reason: str = "", msg: str = ""):
    if required:
        set_val(control, "human_required", "true")
        set_val(control, "human_required_reason", reason)
        set_val(control, "human_required_msg", msg)
    else:
        set_val(control, "human_required", "false")
        set_val(control, "human_required_reason", "")
        set_val(control, "human_required_msg", "")


def set_plan_human_required(plan_md: str, required: bool, reason: str = "", msg: str = ""):
    if required:
        set_val(plan_md, "plan_human_required", "true")
        set_val(plan_md, "plan_human_required_reason", reason)
        set_val(plan_md, "plan_human_required_msg", msg)
    else:
        set_val(plan_md, "plan_human_required", "false")
        set_val(plan_md, "plan_human_required_reason", "")
        set_val(plan_md, "plan_human_required_msg", "")


# ─────────────── 一次性 Migration 工具 ───────────────

def _get_val_from_md_content(content: str, key: str) -> str | None:
    pat = re.compile(rf"^\s*{re.escape(key)}\s*:\s*(.*?)\s*$", re.MULTILINE)
    m = pat.search(content)
    if m:
        return m.group(1).split("#", 1)[0].strip().strip('"').strip("'")
    return None


def migrate_to_json(control_path: str, out_json_path: str):
    data = {
        "schema_version": 1,
        "mode": "flat",
        "current_phase": "1",
        "plan_version": 1,
        "framework_ref": "",
        "repo_structure": "",
        "requirements_map": [],
        "phases": [],
        "issues": [],
        "tree": {
            "root": "root",
            "nodes": {}
        },
        "control": {},
        "plan": {}
    }
    
    if os.path.exists(control_path):
        with open(control_path, "r", encoding="utf-8") as f:
            content = f.read()
            
        repo_m = re.search(r"# 📁 第二段：Repository 結構.*?\n```(.*?)```", content, re.DOTALL)
        if repo_m:
            data["repo_structure"] = repo_m.group(1).strip()
            
        yaml_blocks = re.findall(r"```yaml(.*?)```", content, re.DOTALL)
        for block in yaml_blocks:
            for line in block.split("\n"):
                if ":" in line:
                    k, v = line.split(":", 1)
                    k = k.strip()
                    v = v.split("#", 1)[0].strip().strip('"').strip("'")
                    if not k:
                        continue
                    set_val_in_json_data(data, k, v)
                    
        # 讀取 p{id}_* 的舊值
        phase_ids = set()
        for k in data.get("control", {}).keys():
            m = re.match(r"^p(\d+)_", k)
            if m:
                phase_ids.add(m.group(1))
        for m in re.finditer(r"^p(\d+)_", content, re.MULTILINE):
            phase_ids.add(m.group(1))

        phase_headers = re.finditer(r"## Phase (\S+?)（(.*?)）狀態表", content)
        for match in phase_headers:
            phase_id = match.group(1)
            phase_name = match.group(2)
            phase_ids.add(phase_id)
            
            # 尋找是否已存在該 phase_id 的物件
            ph = None
            for existing in data["phases"]:
                if str(existing.get("id")) == phase_id:
                    ph = existing
                    break
            
            if not ph:
                ph = {"id": phase_id, "tasks": [], "coverage": []}
                data["phases"].append(ph)
                
            ph["name"] = phase_name
            ph["consecutive_pass"] = as_int(_get_val_from_md_content(content, f"p{phase_id}_consecutive_pass"))
            ph["total_validations"] = as_int(_get_val_from_md_content(content, f"p{phase_id}_total_validations"))
            ph["last_result"] = _get_val_from_md_content(content, f"p{phase_id}_last_result") or ""
            
            start_pos = match.end()
            end_pos = len(content)
            next_h = re.search(r"(^##|^\s*---\s*$)", content[start_pos:], re.MULTILINE)
            if next_h:
                end_pos = start_pos + next_h.start()
                
            table_content = content[start_pos:end_pos]
            
            for line in table_content.split("\n"):
                line = line.strip()
                if not line.startswith("|") or "Status" in line or "---" in line:
                    continue
                parts = [p.strip() for p in line.split("|")[1:-1]]
                if len(parts) >= 6:
                    t_num = parts[0]
                    t_name_raw = parts[1]
                    t_output = parts[2]
                    t_status = parts[3]
                    t_conv_raw = parts[4]
                    t_round_raw = parts[5]
                    
                    t_id = f"TASK-{t_num}"
                    spec_ref = ""
                    id_match = re.search(r"\[(TASK-\S+?)\]\((.*?)\)", t_name_raw)
                    if id_match:
                        t_id = id_match.group(1)
                        spec_ref = id_match.group(2)
                    else:
                        t_id = t_name_raw.strip()
                        
                    conv = 0
                    threshold = 5
                    if "/" in t_conv_raw:
                        c_parts = t_conv_raw.split("/")
                        try:
                            conv = int(c_parts[0])
                            threshold = int(c_parts[1])
                        except ValueError:
                            pass
                            
                    last_round = None
                    try:
                        last_round = int(t_round_raw)
                    except ValueError:
                        pass
                        
                    ph["tasks"].append({
                        "id": t_id,
                        "order": len(ph["tasks"]) + 1,
                        "spec_ref": spec_ref,
                        "status": t_status,
                        "conv": conv,
                        "threshold": threshold,
                        "depends_on": [],
                        "verify_method": "re_derive",
                        "output": t_output,
                        "last_round": last_round
                    })


        # 把那些在 YAML 裡但沒有被狀態表涵蓋的 phase 也建出來
        for pid in phase_ids:
            if not any(ph.get("id") == pid for ph in data["phases"]):
                data["phases"].append({
                    "id": pid,
                    "name": f"Phase {pid}",
                    "consecutive_pass": as_int(_get_val_from_md_content(content, f"p{pid}_consecutive_pass")),
                    "total_validations": as_int(_get_val_from_md_content(content, f"p{pid}_total_validations")),
                    "last_result": _get_val_from_md_content(content, f"p{pid}_last_result") or "",
                    "tasks": [],
                    "coverage": []
                })

        cov_matches = re.finditer(r"## Coverage 定義與統計.*?\n(.*?)(?=\n##|\n---|$(?![\s\S]))", content, re.DOTALL)
        for match in cov_matches:
            table_text = match.group(1)
            if data["phases"]:
                ph = data["phases"][-1]
                for line in table_text.split("\n"):
                    line = line.strip()
                    if not line.startswith("|") or "指標" in line or "---" in line:
                        continue
                    parts = [p.strip() for p in line.split("|")[1:-1]]
                    if len(parts) >= 5:
                        metric = parts[0]
                        denom = parts[1]
                        num = 0
                        try:
                            num = int(parts[2])
                        except ValueError:
                            pass
                        round_val = parts[4]
                        
                        ph["coverage"].append({
                            "metric": metric,
                            "denominator": denom,
                            "numerator": num,
                            "round": round_val
                        })

        req_m = re.search(r"# 🎯 第五段：需求 → 任務 追溯表.*?\n(.*?)(?=\n#|\n---|$(?![\s\S]))", content, re.DOTALL)
        if req_m:
            table_text = req_m.group(1)
            for line in table_text.split("\n"):
                line = line.strip()
                if not line.startswith("|") or "需求 ID" in line or "---" in line:
                    continue
                parts = [p.strip() for p in line.split("|")[1:-1]]
                if len(parts) >= 3:
                    data["requirements_map"].append({
                        "req_id": parts[0],
                        "task_id": parts[1],
                        "verify": parts[2]
                    })
                    
        issue_m = re.search(r"# 🐛 第六段：Issue 索引.*?\n(.*?)(?=\n#|\n---|$(?![\s\S]))", content, re.DOTALL)
        if issue_m:
            table_text = issue_m.group(1)
            for line in table_text.split("\n"):
                line = line.strip()
                if not line.startswith("|") or "Issue ID" in line or "---" in line or "(無)" in line:
                    continue
                parts = [p.strip() for p in line.split("|")[1:-1]]
                if len(parts) >= 6:
                    phase_task = parts[3]
                    phase_val, task_val = "", ""
                    if "/" in phase_task:
                        phase_val, task_val = phase_task.split("/", 1)
                    data["issues"].append({
                        "id": parts[0],
                        "level": parts[1],
                        "title": parts[2],
                        "phase": phase_val,
                        "task": task_val,
                        "status": parts[4],
                        "round": parts[5]
                    })

    tree_path = os.path.join(os.path.dirname(control_path) or ".", "TREE.md")
    if os.path.exists(tree_path):
        data["mode"] = "tree"
        with open(tree_path, "r", encoding="utf-8") as f:
            tree_content = f.read()
        
        root_m = re.search(r"tree_root\s*:\s*(\S+)", tree_content)
        if root_m:
            data["tree"]["root"] = root_m.group(1)
            
        node_blocks = re.findall(r"```yaml(.*?)```", tree_content, re.DOTALL)
        for block in node_blocks:
            for line in block.split("\n"):
                if ":" in line:
                    k, v = line.split(":", 1)
                    k = k.strip()
                    v = v.split("#", 1)[0].strip().strip('"').strip("'")
                    if k.startswith("node_"):
                        set_val_in_json_data(data, k, v)

    plan_path = os.path.join(os.path.dirname(control_path) or ".", "PLAN.md")
    if os.path.exists(plan_path):
        with open(plan_path, "r", encoding="utf-8") as f:
            plan_content = f.read()
        yaml_blocks = re.findall(r"```yaml(.*?)```", plan_content, re.DOTALL)
        for block in yaml_blocks:
            for line in block.split("\n"):
                if ":" in line:
                    k, v = line.split(":", 1)
                    k = k.strip()
                    v = v.split("#", 1)[0].strip().strip('"').strip("'")
                    if k.startswith("plan_"):
                        set_val_in_json_data(data, k, v)

    save_state_json(out_json_path, data)
    render_all(out_json_path)


# ─────────────── CLI 進入點 ───────────────

if __name__ == "__main__":
    import argparse
    import sys
    
    parser = argparse.ArgumentParser(description="Loop Engineering State CLI Tool")
    subparsers = parser.add_subparsers(dest="cmd", required=True)
    
    # get
    get_p = subparsers.add_parser("get")
    get_p.add_argument("--control")
    get_p.add_argument("--state")
    get_p.add_argument("key")
    
    # set
    set_p = subparsers.add_parser("set")
    set_p.add_argument("--control")
    set_p.add_argument("--state")
    set_p.add_argument("key")
    set_p.add_argument("value")
    
    # incr
    incr_p = subparsers.add_parser("incr")
    incr_p.add_argument("--control")
    incr_p.add_argument("--state")
    incr_p.add_argument("key")
    incr_p.add_argument("--by", type=int, default=1)
    
    # task-status
    ts_p = subparsers.add_parser("task-status")
    ts_p.add_argument("--state", required=True)
    ts_p.add_argument("--phase", required=True)
    ts_p.add_argument("--task", required=True)
    ts_p.add_argument("--to", required=True, choices=["TODO", "DRAFTED", "CONVERGED", "NEEDS_REVISION", "FROZEN"])
    
    # task-conv
    tc_p = subparsers.add_parser("task-conv")
    tc_p.add_argument("--state", required=True)
    tc_p.add_argument("--phase", required=True)
    tc_p.add_argument("--task", required=True)
    tc_group = tc_p.add_mutually_exclusive_group(required=True)
    tc_group.add_argument("--incr", action="store_true")
    tc_group.add_argument("--reset", action="store_true")
    
    # task-add
    ta_p = subparsers.add_parser("task-add")
    ta_p.add_argument("--state", required=True)
    ta_p.add_argument("--phase", required=True)
    ta_p.add_argument("--id", required=True)
    ta_p.add_argument("--order", type=int, required=True)
    ta_p.add_argument("--threshold", type=int, default=5)
    ta_p.add_argument("--depends", default="")
    ta_p.add_argument("--output", default="")
    ta_p.add_argument("--spec", default="")
    
    # issue-add
    ia_p = subparsers.add_parser("issue-add")
    ia_p.add_argument("--state", required=True)
    ia_p.add_argument("--id", required=True)
    ia_p.add_argument("--level", required=True, choices=["BLOCKING", "NON_BLOCKING"])
    ia_p.add_argument("--task", default="")
    ia_p.add_argument("--phase", default="")
    ia_p.add_argument("--title", required=True)
    
    # issue-set-status
    is_p = subparsers.add_parser("issue-set-status")
    is_p.add_argument("--state", required=True)
    is_p.add_argument("--id", required=True)
    is_p.add_argument("--to", required=True, choices=["OPEN", "RESOLVED"])
    
    # node-set-state
    ns_p = subparsers.add_parser("node-set-state")
    ns_p.add_argument("--state", required=True)
    ns_p.add_argument("--node", required=True)
    ns_p.add_argument("--to", required=True, choices=["PENDING", "DECOMPOSED", "LEAF", "IN_PROGRESS", "CONVERGED", "NEEDS_REVISION", "FROZEN"])
    
    # node-children
    nc_p = subparsers.add_parser("node-children")
    nc_p.add_argument("--state", required=True)
    nc_p.add_argument("--node", required=True)
    nc_p.add_argument("--set", required=True)
    
    # node-reflow
    nr_p = subparsers.add_parser("node-reflow")
    nr_p.add_argument("--state", required=True)
    nr_p.add_argument("--node", required=True)
    
    # render-control
    rc_p = subparsers.add_parser("render-control")
    rc_p.add_argument("--state", required=True)
    rc_p.add_argument("--out", required=True)
    
    # derive
    dv_p = subparsers.add_parser("derive")
    dv_p.add_argument("--state", required=True)
    dv_p.add_argument("expr")
    
    # migrate
    mg_p = subparsers.add_parser("migrate")
    mg_p.add_argument("--control", required=True)
    mg_p.add_argument("--out", required=True)
    
    args = parser.parse_args()
    
    # 決定 state.json 的絕對路徑
    state_path = None
    if getattr(args, "state", None):
        state_path = args.state
    elif getattr(args, "control", None):
        state_path = _state_json_path(args.control)
    
    # 處理 migrate 子命令 (特別，因為它不需要 state 參數)
    if args.cmd == "migrate":
        migrate_to_json(args.control, args.out)
        sys.exit(0)
        
    if not state_path:
        print("Error: Either --state or --control must be specified.", file=sys.stderr)
        sys.exit(1)
        
    state_path = os.path.abspath(state_path)
    
    if args.cmd in ("get", "set", "incr"):
        if not os.path.exists(state_path):
            print(f"Error: state file {state_path} does not exist. Run migrate first.", file=sys.stderr)
            sys.exit(1)
            
        data = load_state_json(state_path)
        
        if args.cmd == "get":
            val = get_val_from_json_data(data, args.key)
            if val is not None:
                print(val)
                sys.exit(0)
            else:
                print(f"Error: Key '{args.key}' not found.", file=sys.stderr)
                sys.exit(1)
                
        elif args.cmd == "set":
            if not _is_valid_key(args.key):
                print(f"Error: Key '{args.key}' is not in white-list.", file=sys.stderr)
                sys.exit(1)
            set_val_in_json_data(data, args.key, args.value)
            save_state_json(state_path, data)
            render_all(state_path)
            print(f"OK {args.key}={args.value}")
            sys.exit(0)
            
        elif args.cmd == "incr":
            if not _is_valid_key(args.key):
                print(f"Error: Key '{args.key}' is not in white-list.", file=sys.stderr)
                sys.exit(1)
            # 校驗 key 是否為數值型
            val_str = get_val_from_json_data(data, args.key)
            # 如果是 p{ph_id}_consecutive_pass 或總計數器等，可以 incr
            is_numeric = (
                "consecutive_pass" in args.key or 
                "total_validations" in args.key or 
                args.key in ("rounds_since_progress", "stuck_level", "enhanced_rounds_used", "review_invalid_streak", "plan_version", "plan_stable_rounds") or
                "depth" in args.key or "stable_rounds" in args.key or "reflow_count" in args.key
            )
            if not is_numeric:
                print(f"Error: Key '{args.key}' is not numeric, cannot increment.", file=sys.stderr)
                sys.exit(1)
                
            old_val = as_int(val_str)
            new_val = old_val + args.by
            set_val_in_json_data(data, args.key, str(new_val))
            save_state_json(state_path, data)
            render_all(state_path)
            print(f"OK {args.key}={new_val}")
            sys.exit(0)
            
    elif args.cmd in ("task-status", "task-conv", "task-add"):
        data = load_state_json(state_path)
        if "phases" not in data:
            data["phases"] = []
            
        # 尋找對應 phase
        phase_ph = None
        for ph in data["phases"]:
            if str(ph.get("id")) == args.phase:
                phase_ph = ph
                break
                
        if args.cmd == "task-add":
            if not phase_ph:
                phase_ph = {"id": args.phase, "name": f"Phase {args.phase}", "tasks": [], "coverage": []}
                data["phases"].append(phase_ph)
            # 檢查 task_id 是否已存在
            for t in phase_ph["tasks"]:
                if t.get("id") == args.id:
                    print(f"Error: Task '{args.id}' already exists in phase '{args.phase}'.", file=sys.stderr)
                    sys.exit(1)
            depends = [d.strip() for d in args.depends.split(",") if d.strip()]
            phase_ph["tasks"].append({
                "id": args.id,
                "order": args.order,
                "spec_ref": args.spec,
                "status": "TODO",
                "conv": 0,
                "threshold": args.threshold,
                "depends_on": depends,
                "verify_method": "re_derive",
                "output": args.output,
                "last_round": None
            })
            save_state_json(state_path, data)
            render_all(state_path)
            print(f"OK task-add {args.id}")
            sys.exit(0)
            
        # task-status & task-conv
        if not phase_ph:
            print(f"Error: Phase '{args.phase}' not found.", file=sys.stderr)
            sys.exit(1)
            
        target_task = None
        for t in phase_ph["tasks"]:
            if t.get("id") == args.task:
                target_task = t
                break
                
        if not target_task:
            print(f"Error: Task '{args.task}' not found in phase '{args.phase}'.", file=sys.stderr)
            sys.exit(1)
            
        if args.cmd == "task-status":
            old_status = target_task.get("status", "TODO")
            new_status = args.to
            
            # 單步狀態轉移校驗：
            # 合法：TODO -> DRAFTED, DRAFTED -> CONVERGED, NEEDS_REVISION -> DRAFTED
            # 非法：TODO -> CONVERGED, etc.
            allowed = False
            if old_status == new_status:
                allowed = True
            elif old_status == "TODO" and new_status in ("DRAFTED", "FROZEN"):
                allowed = True
            elif old_status == "DRAFTED" and new_status in ("CONVERGED", "NEEDS_REVISION", "FROZEN"):
                allowed = True
            elif old_status == "NEEDS_REVISION" and new_status in ("DRAFTED", "FROZEN"):
                allowed = True
            elif old_status == "FROZEN" and new_status in ("TODO", "DRAFTED", "NEEDS_REVISION"):
                allowed = True
            elif old_status == "CONVERGED" and new_status in ("NEEDS_REVISION", "FROZEN"):
                allowed = True
                
            if not allowed:
                print(f"Error: Invalid status transition from {old_status} to {new_status}.", file=sys.stderr)
                sys.exit(1)
                
            if new_status == "CONVERGED":
                # 加驗 conv 是否達 threshold
                if target_task.get("conv", 0) < target_task.get("threshold", 5):
                    print(f"Error: Task conv {target_task.get('conv')} < threshold {target_task.get('threshold')}.", file=sys.stderr)
                    sys.exit(1)
                    
            target_task["status"] = new_status
            save_state_json(state_path, data)
            render_all(state_path)
            print(f"OK task-status {args.task} to {new_status}")
            sys.exit(0)
            
        elif args.cmd == "task-conv":
            if args.incr:
                target_task["conv"] = target_task.get("conv", 0) + 1
            elif args.reset:
                target_task["conv"] = 0
            save_state_json(state_path, data)
            render_all(state_path)
            print(f"OK task-conv {args.task} (conv={target_task['conv']})")
            sys.exit(0)
            
    elif args.cmd in ("issue-add", "issue-set-status"):
        data = load_state_json(state_path)
        if "issues" not in data:
            data["issues"] = []
            
        if args.cmd == "issue-add":
            # 檢查 issue 是否已存在
            for iss in data["issues"]:
                if iss.get("id") == args.id:
                    print(f"Error: Issue '{args.id}' already exists.", file=sys.stderr)
                    sys.exit(1)
                    
            # 取得當前 Round，可以從 control.review_invalid_streak 或 rounds.jsonl 推得，這裡預設填寫空
            # 或是從 control 中讀取。其實我們可以看 rounds_since_progress 等。
            data["issues"].append({
                "id": args.id,
                "level": args.level,
                "title": args.title,
                "phase": args.phase,
                "task": args.task,
                "status": "OPEN",
                "round": ""
            })
            save_state_json(state_path, data)
            render_all(state_path)
            print(f"OK issue-add {args.id}")
            sys.exit(0)
            
        elif args.cmd == "issue-set-status":
            target_iss = None
            for iss in data["issues"]:
                if iss.get("id") == args.id:
                    target_iss = iss
                    break
            if not target_iss:
                print(f"Error: Issue '{args.id}' not found.", file=sys.stderr)
                sys.exit(1)
            target_iss["status"] = args.to
            save_state_json(state_path, data)
            render_all(state_path)
            print(f"OK issue-set-status {args.id} to {args.to}")
            sys.exit(0)
            
    elif args.cmd in ("node-set-state", "node-children", "node-reflow"):
        data = load_state_json(state_path)
        if "tree" not in data:
            data["tree"] = {"root": "root", "nodes": {}}
        nodes = data["tree"].setdefault("nodes", {})
        
        if args.cmd == "node-set-state":
            node = nodes.setdefault(args.node, {
                "state": "PENDING", "children": [], "parent": None,
                "depth": 0, "stable_rounds": 0, "reflow_count": 0, "depends_on": []
            })
            node["state"] = args.to
            save_state_json(state_path, data)
            render_all(state_path)
            print(f"OK node-set-state {args.node} to {args.to}")
            sys.exit(0)
            
        elif args.cmd == "node-children":
            node = nodes.setdefault(args.node, {
                "state": "PENDING", "children": [], "parent": None,
                "depth": 0, "stable_rounds": 0, "reflow_count": 0, "depends_on": []
            })
            children = [c.strip() for c in args.set.split(",") if c.strip()]
            node["children"] = children
            if node["state"] == "PENDING":
                node["state"] = "DECOMPOSED"
            
            # 為子節點設定 parent 與 depth
            for c in children:
                c_node = nodes.setdefault(c, {
                    "state": "PENDING", "children": [], "parent": args.node,
                    "depth": node.get("depth", 0) + 1, "stable_rounds": 0, "reflow_count": 0, "depends_on": []
                })
                c_node["parent"] = args.node
                c_node["depth"] = node.get("depth", 0) + 1
                
            save_state_json(state_path, data)
            render_all(state_path)
            print(f"OK node-children {args.node} children set to {children}")
            sys.exit(0)
            
        elif args.cmd == "node-reflow":
            node = nodes.get(args.node)
            if not node:
                print(f"Error: Node '{args.node}' not found.", file=sys.stderr)
                sys.exit(1)
            node["reflow_count"] = node.get("reflow_count", 0) + 1
            node["state"] = "NEEDS_REVISION"
            save_state_json(state_path, data)
            render_all(state_path)
            print(f"OK node-reflow {args.node} reflow_count={node['reflow_count']}")
            sys.exit(0)
            
    elif args.cmd == "render-control":
        print(f"OK render-control to {args.out} (noop)")
        sys.exit(0)

        
    elif args.cmd == "derive":
        data = load_state_json(state_path)
        expr = args.expr
        
        if expr == "blocking_issues":
            issues = data.get("issues", [])
            blocking = [i for i in issues if i.get("status") == "OPEN" and i.get("level") == "BLOCKING"]
            print(len(blocking))
            sys.exit(0)
            
        elif expr.startswith("phase-converged:"):
            phase_id = expr.split(":", 1)[1]
            phases = data.get("phases", [])
            target_ph = None
            for ph in phases:
                if str(ph.get("id")) == phase_id:
                    target_ph = ph
                    break
            if not target_ph:
                print("false")
                sys.exit(0)
            tasks = target_ph.get("tasks", [])
            if not tasks:
                print("false")
                sys.exit(0)
            all_conv = all(t.get("status") == "CONVERGED" for t in tasks)
            print("true" if all_conv else "false")
            sys.exit(0)
            
        elif expr == "is-done":
            # 平模式下的 is-done
            phases = data.get("phases", [])
            if not phases:
                print("false")
                sys.exit(0)
            last_ph = phases[-1]
            last_ph_id = last_ph.get("id")
            
            sc = {
                "final_phase_pass_gte": 10,
                "blocking_eq": 0,
            }
            # 取得計數器
            consecutive_pass = last_ph.get("consecutive_pass", 0)
            current_phase = data.get("current_phase", "1")
            
            issues = data.get("issues", [])
            blocking_count = len([i for i in issues if i.get("status") == "OPEN" and i.get("level") == "BLOCKING"])
            
            tasks = last_ph.get("tasks", [])
            all_conv = all(t.get("status") == "CONVERGED" for t in tasks) if tasks else False
            
            is_completed = (
                str(current_phase) == str(last_ph_id) and
                consecutive_pass >= sc["final_phase_pass_gte"] and
                blocking_count == sc["blocking_eq"] and
                all_conv
            )
            print("true" if is_completed else "false")
            sys.exit(0)
            
        else:
            print(f"Error: Unknown derivation expression '{expr}'.", file=sys.stderr)
            sys.exit(1)
