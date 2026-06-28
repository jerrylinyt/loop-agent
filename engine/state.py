import os
import re
import json
import logging
from collections import deque
from git_utils import git_head

logger = logging.getLogger(__name__)

# ─────────────── CONTROL 讀寫（單行，不載入 LLM context） ───────────────
def get_val(control: str, key: str) -> str | None:
    if not os.path.exists(control):
        return None
    pat = re.compile(rf"^\s*{re.escape(key)}\s*:\s*(.*?)\s*$")
    try:
        with open(control, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                m = pat.match(line)
                if m:
                    return m.group(1).split("#", 1)[0].strip().strip('"')
    except OSError as e:
        logger.warning(f"Failed to read {control}: {e}")
    return None


def set_val(control: str, key: str, value: str):
    if not os.path.exists(control):
        return
    pat = re.compile(rf"^(\s*{re.escape(key)}\s*:\s*).*?(\s*(#.*)?)$")
    out, hit = [], False
    try:
        with open(control, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
            
        for line in lines:
            m = pat.match(line.rstrip("\n"))
            if m and not hit:
                comment = m.group(3) or ""
                out.append(f"{m.group(1)}{value}  {comment}".rstrip() + "\n")
                hit = True
            else:
                out.append(line)
                
        # If the key was not found, attempt to insert it within the ```yaml ... ``` block
        if not hit:
            in_yaml = False
            insert_idx = -1
            for idx, line in enumerate(out):
                if line.strip() == "```yaml":
                    in_yaml = True
                elif line.strip() == "```" and in_yaml:
                    insert_idx = idx
                    break
                    
            if insert_idx != -1:
                out.insert(insert_idx, f"{key}: {value}\n")
                hit = True
                
        if hit:
            with open(control, "w", encoding="utf-8") as f:
                f.writelines(out)
    except OSError as e:
        logger.error(f"Failed to write to {control}: {e}")


def as_int(v, d=0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return d


# ─────────────── 歷史與進度重建（從 rounds.jsonl 讀取） ───────────────
def reconstruct_history_and_progress(cfg: dict, maxlen: int) -> tuple:
    """從 rounds.jsonl 重建震盪歷史 (fail_history) 及進度特徵 (progress)。
    讀取最近的歷史紀錄來還原上一次中斷時的記憶體狀態。"""
    from collections import deque
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
                    # 1. 僅根據類型為 round_finished 或預設無 type 的執行輪重建進度
                    if record.get("type", "round_finished") == "round_finished":
                        progress = {
                            "sig": record.get("progress_sig") or "",
                            "idle": str(record.get("idle_rounds") or 0),
                            "killed_streak": str(record.get("killed_streak") or 0),
                            "phase": str(record.get("phase") or ""),
                            "last_pass": str(record.get("consecutive_pass") or 0)
                        }
                        
                        # 2. 重建震盪指紋佇列
                        # 只有客觀驗證失敗才會有指紋
                        mode = record.get("mode") or ""
                        result = record.get("result") or ""
                        is_fail_verify = (not record.get("killed")) and ("驗證" in mode) and (result == "FAIL")
                        if is_fail_verify:
                            fp = record.get("fail_fingerprint")
                            if fp:
                                dq.append(fp)
                        
                        # 若該輪有進展，清空之前的失敗佇列
                        if record.get("progressed"):
                            dq.clear()
        except OSError as e:
            logger.warning(f"Failed to reconstruct history and progress from rounds.jsonl: {e}")
    return dq, progress


def progress_signature(cfg: dict, control: str) -> str:
    """本輪『活動簽章』= current_phase + 各 phase consecutive_pass 總和 + HEAD commit。
    連續多輪簽章不變 = agent 沒提交任何東西、計數器也沒動（空轉/反覆被 watchdog 中斷/CLI 壞掉）。"""
    from git_utils import git_head
    phase = get_val(control, "current_phase") or ""
    total_pass = 0
    for ph in (cfg.get("phases") or []):
        total_pass += as_int(get_val(control, f"p{ph.get('id')}_consecutive_pass"))
    return f"{phase}|{total_pass}|{git_head()}"


def rounds_log_path(cfg: dict) -> str:
    return os.path.join(cfg["runtime"]["state_dir"], "rounds.jsonl")


def append_round_record(cfg: dict, record: dict) -> None:
    """Append 一行逐輪紀錄到 rounds.jsonl，並限制最多保留 100 筆紀錄。
    Best-effort：失敗只記 warning，絕不中斷主迴圈。"""
    p = rounds_log_path(cfg)
    try:
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        
        # 讀取現有紀錄
        lines = []
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                lines = [l for l in f if l.strip()]
                
        # 新增此輪紀錄
        line = json.dumps(record, ensure_ascii=False) + "\n"
        lines.append(line)
        
        # 保留最後 100 筆
        if len(lines) > 100:
            lines = lines[-100:]
            
        with open(p, "w", encoding="utf-8") as f:
            f.writelines(lines)
    except (OSError, TypeError, ValueError) as e:
        logger.warning(f"Failed to append round record: {e}")


def check_stop_requested(cfg: dict, log_both=None) -> bool:
    """檢查是否有優雅停機請求 (stop_requested)。
    若有，則刪除該檔案、記錄日誌、寫入停機事件到 rounds.jsonl，並回傳 True。"""
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

