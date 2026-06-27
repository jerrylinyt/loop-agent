import os
import sys
import time
import asyncio
import subprocess
import psutil
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Optional
import yaml
import hashlib

app = FastAPI(title="Loop Engineering Dashboard")

# Ensure dashboard templates folder exists
HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(HERE, "templates")

# Models
class ProjectStatus(BaseModel):
    id: str
    repo: str
    repo_name: str
    workspace: str
    phase: str
    stuck: str
    status: str
    updated_at: str
    is_running: bool
    pid: Optional[int] = None
    config_path: str
    stale_lock: bool = False
    started_at: Optional[str] = None
    heartbeat_age: Optional[int] = None

class StartRequest(BaseModel):
    mode: str = "auto"
    stage: str = "all"

class ConfigUpdateRequest(BaseModel):
    content: str

class InitRequest(BaseModel):
    repo_path: str
    workspace_name: str = "default"

class AddProjectRequest(BaseModel):
    repo_path: str
    workspace_name: str = "default"

class RejectRequest(BaseModel):
    subtree_id: str

def get_index_path():
    return os.path.expanduser("~/.loop/index.md")

def get_control_val(control_path: str, key: str) -> str | None:
    if not os.path.exists(control_path):
        return None
    import re
    pat = re.compile(rf"^\s*{re.escape(key)}\s*:\s*(.*?)\s*$")
    try:
        with open(control_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                m = pat.match(line)
                if m:
                    return m.group(1).split("#", 1)[0].strip().strip('"')
    except Exception:
        pass
    return None

def get_last_n_lines(file_path: str, n: int) -> list[str]:
    if n <= 0:
        return []
    BLOCK_SIZE = 4096
    lines = []
    try:
        with open(file_path, "rb") as f:
            f.seek(0, os.SEEK_END)
            file_size = f.tell()
            
            data = bytearray()
            pos = file_size
            while pos > 0 and len(lines) <= n:
                to_read = min(BLOCK_SIZE, pos)
                pos -= to_read
                f.seek(pos)
                chunk = f.read(to_read)
                data = chunk + data
                newlines_count = data.count(b'\n')
                if newlines_count > n + 1:
                    break
            
            decoded = data.decode("utf-8", errors="replace")
            all_lines = decoded.splitlines()
            if len(all_lines) > n:
                lines = all_lines[-n:]
            else:
                lines = all_lines
    except Exception:
        pass
    return lines

def set_control_val(control_path: str, key: str, value: str):
    if not os.path.exists(control_path):
        return
    import re
    pat = re.compile(rf"^(\s*{re.escape(key)}\s*:\s*).*?(\s*(#.*)?)$")
    out, hit = [], False
    try:
        with open(control_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                m = pat.match(line.rstrip("\n"))
                if m and not hit:
                    comment = m.group(3) or ""
                    out.append(f"{m.group(1)}{value}  {comment}".rstrip() + "\n")
                    hit = True
                else:
                    out.append(line)
        if hit:
            with open(control_path, "w", encoding="utf-8") as f:
                f.writelines(out)
    except Exception as e:
        print(f"Failed to set control value: {e}")

def extract_human_context(log_path: str) -> tuple[str, str]:
    if not os.path.exists(log_path):
        return "", ""
    lines = get_last_n_lines(log_path, 1000)
    idx = -1
    for i in range(len(lines) - 1, -1, -1):
        if "human_required" in lines[i] or "🧑‍⚖️" in lines[i]:
            idx = i
            break
    if idx == -1:
        return "", ""
    reason_line = lines[idx].strip()
    excerpt_lines = lines[idx : idx + 15]
    log_excerpt = "\n".join(excerpt_lines)
    return reason_line, log_excerpt

def parse_control_file(control_path: str) -> dict:
    if not os.path.exists(control_path):
        return {}
    import re
    data = {}
    phase_ids = set()
    pat = re.compile(r"^\s*([a-zA-Z0-9_]+)\s*:\s*(.*?)\s*$")
    try:
        with open(control_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line_no_comment = line.split("#", 1)[0].strip()
                m = pat.match(line_no_comment)
                if m:
                    key = m.group(1)
                    val = m.group(2).strip().strip('"')
                    data[key] = val
                    pm = re.match(r"^p(\d+)_consecutive_pass$", key)
                    if pm:
                        phase_ids.add(pm.group(1))
    except Exception:
        pass
    # Load loop.config.yaml thresholds
    config_path = os.path.join(os.path.dirname(control_path), "loop.config.yaml")
    thresholds = {}
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as cf:
                config_data = yaml.safe_load(cf)
                if isinstance(config_data, dict):
                    phases_conf = config_data.get("phases", [])
                    if isinstance(phases_conf, list):
                        for p_conf in phases_conf:
                            if isinstance(p_conf, dict) and "id" in p_conf:
                                p_id = str(p_conf["id"])
                                thresholds[p_id] = p_conf.get("converge_threshold")
        except Exception:
            pass

    phases_list = []
    for pid in sorted(phase_ids, key=int):
        consec = data.get(f"p{pid}_consecutive_pass")
        tot = data.get(f"p{pid}_total_validations")
        last_res = data.get(f"p{pid}_last_result")
        threshold_val = thresholds.get(pid)
        phases_list.append({
            "id": pid,
            "consecutive_pass": consec if consec is not None else "0",
            "total_validations": tot if tot is not None else "0",
            "last_result": last_res if last_res is not None else "N/A",
            "threshold": threshold_val
        })
    data["phases"] = phases_list
    return data

import re
TIMESTAMP_REGEX = re.compile(r"^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})")

def parse_timestamp(line: str) -> tuple[str, str]:
    m = TIMESTAMP_REGEX.match(line)
    if m:
        ts = m.group(1)
        text = line[len(ts):].strip()
        return ts, text
    return "", line.strip()

ACTIVITY_CLASSIFICATION_RULES = [
    ("complete", lambda l: "LOOP COMPLETE" in l or "TREE EXECUTE COMPLETE" in l),
    ("review_revert", lambda l: "Git Review Gate" in l and "🚨" in l),
    ("human_required", lambda l: "停下交人類" in l or "human_required" in l or "⛔" in l or "🧑‍⚖️" in l),
    ("model_upgrade", lambda l: "升級模型" in l or "⬆" in l or "⬆⬆" in l),
    ("progress", lambda l: "↩ 有進展" in l),
    ("leaf_converged", lambda l: "🍃" in l and "收斂" in l),
]

def index_row_matches(line: str, repo_path: str, workspace: str) -> bool:
    """是否為對應 (repo_path, workspace) 的 index.md 資料列。
    用解析後的儲存格做精確比對，避免路徑互為前綴時的子字串誤判。"""
    line = line.strip()
    if not line.startswith("|") or line.startswith("| 專案 ") or set(line) <= set("|-: "):
        return False
    parts = [p.strip() for p in line.split("|")][1:-1]
    if len(parts) < 7:
        return False
    return parts[1] == repo_path and parts[2] == workspace

def parse_index():
    index_path = get_index_path()
    projects = []
    if not os.path.exists(index_path):
        return projects
    
    try:
        with open(index_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line.startswith("|") or line.startswith("| 專案 ") or set(line) <= set("|-: "):
                    continue
                
                parts = [p.strip() for p in line.split("|")][1:-1]
                if len(parts) >= 7:
                    repo_name, repo_path, ws, phase, stuck, status, updated_at = parts[:7]
                    proj_id = hashlib.md5(f"{repo_path}_{ws}".encode()).hexdigest()
                    
                    # Read real-time values from CONTROL.md if exists
                    control_path = os.path.join(repo_path, ".loop", ws, "CONTROL.md")
                    if os.path.exists(control_path):
                        r_phase = get_control_val(control_path, "current_phase")
                        r_stuck = get_control_val(control_path, "stuck_level")
                        r_human = get_control_val(control_path, "human_required")
                        r_done = get_control_val(control_path, "stop_condition_met")
                        r_last = get_control_val(control_path, "last_round_result")
                        
                        if r_phase:
                            phase = r_phase
                        if r_stuck:
                            stuck = r_stuck
                        if r_human == "true":
                            status = "human_required"
                        elif r_done == "true":
                            status = "complete"
                        elif r_last:
                            status = r_last

                    # Check if actually running via lock file
                    is_running = False
                    pid = None
                    stale_lock = False
                    started_at = None
                    heartbeat_age = None
                    lock_path = os.path.join(repo_path, ".loop", ws, ".loop_state", "run.lock")
                    if os.path.exists(lock_path):
                        is_running = True
                        try:
                            with open(lock_path, "r", encoding="utf-8") as lf:
                                lock_data = lf.read().strip()
                                # pid=1234 started=...
                                if lock_data.startswith("pid="):
                                    pid_part = lock_data.split(" ")[0]
                                    pid = int(pid_part.split("=")[1])
                                if "started=" in lock_data:
                                    started_at = lock_data.split("started=", 1)[1].strip()
                        except Exception:
                            pass
                        try:
                            heartbeat_age = int(time.time() - os.path.getmtime(lock_path))
                        except Exception:
                            pass
                    
                    lock_exists = os.path.exists(lock_path)
                    if lock_exists:
                        if pid:
                            try:
                                p = psutil.Process(pid)
                                if not p.is_running() or p.status() == psutil.STATUS_ZOMBIE:
                                    is_running = False
                            except psutil.NoSuchProcess:
                                is_running = False
                        else:
                            is_running = False
                        stale_lock = not is_running

                    projects.append({
                        "id": proj_id,
                        "repo": repo_path,
                        "repo_name": repo_name,
                        "workspace": ws,
                        "phase": phase,
                        "stuck": stuck,
                        "status": status,
                        "updated_at": updated_at,
                        "is_running": is_running,
                        "pid": pid,
                        "config_path": os.path.join(repo_path, ".loop", ws, "loop.config.yaml"),
                        "stale_lock": stale_lock,
                        "started_at": started_at,
                        "heartbeat_age": heartbeat_age
                    })
    except Exception as e:
        print(f"Error reading index: {e}")
    return projects

def get_project_by_id(proj_id: str):
    projects = parse_index()
    for p in projects:
        if p["id"] == proj_id:
            return p
    return None

@app.get("/api/projects", response_model=List[ProjectStatus])
def list_projects():
    return parse_index()

@app.post("/api/projects/{proj_id}/start")
def start_project(proj_id: str, req: StartRequest):
    proj = get_project_by_id(proj_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    
    if proj["is_running"]:
        raise HTTPException(status_code=400, detail="Already running")
        
    if req.mode not in ["auto", "gated"]:
        raise HTTPException(status_code=400, detail="Invalid mode")
    if req.stage not in ["all", "plan", "execute"]:
        raise HTTPException(status_code=400, detail="Invalid stage")
    
    # Auto clear stale lock if it exists
    if proj.get("stale_lock"):
        lock_path = os.path.join(proj["repo"], ".loop", proj["workspace"], ".loop_state", "run.lock")
        if os.path.exists(lock_path):
            try:
                os.remove(lock_path)
            except Exception as e:
                print(f"Failed to clear stale lock: {e}")

    framework_dir = os.path.dirname(HERE)
    run_py = os.path.join(framework_dir, "engine", "run.py")
    
    # Spawn subprocess
    try:
        state_dir = os.path.join(proj["repo"], ".loop", proj["workspace"], ".loop_state")
        os.makedirs(state_dir, exist_ok=True)
        spawn_log_path = os.path.join(state_dir, "spawn.log")
        with open(spawn_log_path, "a", encoding="utf-8") as f_out:
            subprocess.Popen(
                [sys.executable, run_py, "--workspace", proj["workspace"], "--mode", req.mode, "--stage", req.stage],
                cwd=proj["repo"],
                stdout=f_out,
                stderr=f_out
            )
        return {"status": "started"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/projects/init")
def init_project(req: InitRequest):
    repo_path = os.path.abspath(os.path.expanduser(req.repo_path))
    if not os.path.isdir(repo_path):
        raise HTTPException(status_code=400, detail="Repository path does not exist or is not a directory.")
        
    framework_dir = os.path.dirname(HERE)
    init_py = os.path.join(framework_dir, "init-project.py")
    
    try:
        result = subprocess.run(
            [sys.executable, init_py, repo_path, "--name", req.workspace_name],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            raise HTTPException(status_code=500, detail=f"Init failed: {result.stderr or result.stdout}")
            
        # Add to index.md so dashboard sees it immediately
        index_path = get_index_path()
        os.makedirs(os.path.dirname(index_path) or ".", exist_ok=True)
        repo_name = os.path.basename(repo_path)
        from datetime import datetime
        ts = datetime.now().strftime("%F %T")
        row = f"| {repo_name} | {repo_path} | {req.workspace_name} | - | - | initialized | {ts} |\n"
        
        # Very simple append; the engine will overwrite this line properly on first run
        if os.path.exists(index_path):
            with open(index_path, "a", encoding="utf-8") as f:
                f.write(row)
        else:
            with open(index_path, "w", encoding="utf-8") as f:
                f.write("# Loop 專案總覽（自動維護）\n\n")
                f.write("| 專案 | repo | workspace | phase | stuck | 狀態 | 更新 |\n")
                f.write("|------|------|-----------|-------|-------|------|------|\n")
                f.write(row)
                
        return {"status": "initialized", "output": result.stdout}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/projects/add")
def add_project(req: AddProjectRequest):
    repo_path = os.path.abspath(os.path.expanduser(req.repo_path))
    if not os.path.isdir(repo_path):
        raise HTTPException(status_code=400, detail="Repository path does not exist or is not a directory.")
        
    config_path = os.path.join(repo_path, ".loop", req.workspace_name, "loop.config.yaml")
    if not os.path.exists(config_path):
        raise HTTPException(status_code=400, detail=f"No workspace named '{req.workspace_name}' found at path. Please initialize it first.")
        
    control_path = os.path.join(repo_path, ".loop", req.workspace_name, "CONTROL.md")
    phase = "-"
    stuck = "-"
    status = "tracked"
    if os.path.exists(control_path):
        r_phase = get_control_val(control_path, "current_phase")
        r_stuck = get_control_val(control_path, "stuck_level")
        r_human = get_control_val(control_path, "human_required")
        r_done = get_control_val(control_path, "stop_condition_met")
        r_last = get_control_val(control_path, "last_round_result")
        
        if r_phase:
            phase = r_phase
        if r_stuck:
            stuck = r_stuck
        if r_human == "true":
            status = "human_required"
        elif r_done == "true":
            status = "complete"
        elif r_last:
            status = r_last
            
    index_path = get_index_path()
    os.makedirs(os.path.dirname(index_path) or ".", exist_ok=True)
    repo_name = os.path.basename(repo_path)
    from datetime import datetime
    ts = datetime.now().strftime("%F %T")
    row = f"| {repo_name} | {repo_path} | {req.workspace_name} | {phase} | {stuck} | {status} | {ts} |\n"
    
    exists = False
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        for line in lines:
            if index_row_matches(line, repo_path, req.workspace_name):
                exists = True
                break
                
    if not exists:
        if os.path.exists(index_path):
            with open(index_path, "a", encoding="utf-8") as f:
                f.write(row)
        else:
            with open(index_path, "w", encoding="utf-8") as f:
                f.write("# Loop 專案總覽（自動維護）\n\n")
                f.write("| 專案 | repo | workspace | phase | stuck | 狀態 | 更新 |\n")
                f.write("|------|------|-----------|-------|-------|------|------|\n")
                f.write(row)
                
    return {"status": "added"}

@app.get("/api/projects/{proj_id}/human-context")
def get_human_context(proj_id: str):
    proj = get_project_by_id(proj_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
        
    control_path = os.path.join(proj["repo"], ".loop", proj["workspace"], "CONTROL.md")
    r_human = get_control_val(control_path, "human_required")
    is_human = (r_human == "true")
    
    reason = ""
    log_excerpt = ""
    if is_human:
        log_path = os.path.join(proj["repo"], ".loop", proj["workspace"], "loop.log")
        reason, log_excerpt = extract_human_context(log_path)
        
    return {
        "human_required": is_human,
        "reason": reason,
        "log_excerpt": log_excerpt
    }

@app.post("/api/projects/{proj_id}/resume")
def resume_project(proj_id: str):
    proj = get_project_by_id(proj_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
        
    if proj["is_running"]:
        raise HTTPException(status_code=400, detail="Cannot resume while project is running. Stop it first.")
        
    control_path = os.path.join(proj["repo"], ".loop", proj["workspace"], "CONTROL.md")

    # Resume mode comes from loop.config.yaml's generation.mode (the real auto/gated
    # source). Note: CONTROL.md's last_round_mode holds per-round descriptions
    # (e.g. "驗證"/"中斷"), NOT the generation mode — do not read it for this.
    mode_arg = "auto"
    try:
        with open(proj["config_path"], "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        cfg_mode = (cfg.get("generation") or {}).get("mode")
        if cfg_mode in ("auto", "gated"):
            mode_arg = cfg_mode
    except Exception:
        pass

    set_control_val(control_path, "human_required", "false")
    
    lock_path = os.path.join(proj["repo"], ".loop", proj["workspace"], ".loop_state", "run.lock")
    if os.path.exists(lock_path):
        try:
            os.remove(lock_path)
        except Exception:
            pass
            
    framework_dir = os.path.dirname(HERE)
    run_py = os.path.join(framework_dir, "engine", "run.py")
    
    try:
        state_dir = os.path.join(proj["repo"], ".loop", proj["workspace"], ".loop_state")
        os.makedirs(state_dir, exist_ok=True)
        spawn_log_path = os.path.join(state_dir, "spawn.log")
        with open(spawn_log_path, "a", encoding="utf-8") as f_out:
            subprocess.Popen(
                [sys.executable, run_py, "--workspace", proj["workspace"], "--mode", mode_arg],
                cwd=proj["repo"],
                stdout=f_out,
                stderr=f_out
            )
        return {"status": "resumed"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/projects/{proj_id}/control")
def get_project_control(proj_id: str):
    proj = get_project_by_id(proj_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
        
    control_path = os.path.join(proj["repo"], ".loop", proj["workspace"], "CONTROL.md")
    return parse_control_file(control_path)

@app.delete("/api/projects/{proj_id}")
def untrack_project(proj_id: str):
    proj = get_project_by_id(proj_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
        
    if proj["is_running"]:
        raise HTTPException(status_code=400, detail="Cannot untrack a running project. Stop it first.")
        
    index_path = get_index_path()
    if not os.path.exists(index_path):
        raise HTTPException(status_code=500, detail="Index file not found")
        
    try:
        with open(index_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            
        out_lines = []
        found = False
        for line in lines:
            if index_row_matches(line, proj["repo"], proj["workspace"]):
                found = True
                continue
            out_lines.append(line)
            
        if found:
            with open(index_path, "w", encoding="utf-8") as f:
                f.writelines(out_lines)
                
        return {"status": "untracked"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/projects/{proj_id}/stop")
def stop_project(proj_id: str):
    proj = get_project_by_id(proj_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    
    pid = proj["pid"]
    if not pid:
        raise HTTPException(status_code=400, detail="Not running or no PID found in run.lock")
    
    try:
        parent = psutil.Process(pid)
        for child in parent.children(recursive=True):
            child.kill()
        parent.kill()
        
        # Clean up lock file
        lock_path = os.path.join(proj["repo"], ".loop", proj["workspace"], ".loop_state", "run.lock")
        if os.path.exists(lock_path):
            os.remove(lock_path)
            
        return {"status": "stopped"}
    except psutil.NoSuchProcess:
        # Maybe clean up stale lock file
        lock_path = os.path.join(proj["repo"], ".loop", proj["workspace"], ".loop_state", "run.lock")
        if os.path.exists(lock_path):
            os.remove(lock_path)
        return {"status": "stopped (stale lock removed)"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/projects/{proj_id}/clear-lock")
def clear_lock(proj_id: str):
    proj = get_project_by_id(proj_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    
    lock_path = os.path.join(proj["repo"], ".loop", proj["workspace"], ".loop_state", "run.lock")
    if os.path.exists(lock_path):
        try:
            os.remove(lock_path)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to clear lock: {e}")
    return {"status": "cleared"}

@app.get("/api/projects/{proj_id}/config")
def get_config(proj_id: str):
    proj = get_project_by_id(proj_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    
    config_path = proj["config_path"]
    if not os.path.exists(config_path):
        raise HTTPException(status_code=404, detail="Config file not found")
        
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            content = f.read()
        return {"content": content}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/projects/{proj_id}/config")
def save_config(proj_id: str, req: ConfigUpdateRequest):
    proj = get_project_by_id(proj_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    
    config_path = proj["config_path"]
    try:
        # Validate yaml
        yaml.safe_load(req.content)
        
        with open(config_path, "w", encoding="utf-8") as f:
            f.write(req.content)
        return {"status": "saved"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid YAML: {e}")

@app.get("/api/projects/{proj_id}/tree")
def get_project_tree(proj_id: str):
    proj = get_project_by_id(proj_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
        
    tree_md = os.path.join(proj["repo"], ".loop", proj["workspace"], "TREE.md")
    if not os.path.exists(tree_md):
        return {"tree_enabled": False, "nodes": [], "root": None}
        
    is_enabled = get_control_val(tree_md, "tree_enabled") == "true"
    root_id = get_control_val(tree_md, "tree_root") or "root"
    
    if not is_enabled:
        return {"tree_enabled": False, "nodes": [], "root": root_id}
        
    nodes = {}
    node_ids = []
    import re
    state_pat = re.compile(r"^\s*node_(\S+?)_state\s*:")
    try:
        with open(tree_md, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                m = state_pat.match(line)
                if m:
                    node_ids.append(m.group(1))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read TREE.md: {e}")
        
    for nid in node_ids:
        state = get_control_val(tree_md, f"node_{nid}_state") or "PENDING"
        children_raw = get_control_val(tree_md, f"node_{nid}_children") or ""
        children = [c.strip() for c in children_raw.split(",") if c.strip()] if children_raw else []
        parent = get_control_val(tree_md, f"node_{nid}_parent") or ""
        depth = get_control_val(tree_md, f"node_{nid}_depth") or "0"
        stable_rounds = get_control_val(tree_md, f"node_{nid}_stable_rounds") or "0"
        reflow_count = get_control_val(tree_md, f"node_{nid}_reflow_count") or "0"
        
        description = nid
        decomp_path = os.path.join(proj["repo"], ".loop", proj["workspace"], "tree", f"{nid}.decomp.md")
        if os.path.exists(decomp_path):
            desc_val = get_control_val(decomp_path, "description")
            if desc_val:
                description = desc_val
                
        nodes[nid] = {
            "id": nid,
            "state": state,
            "children": children,
            "parent": parent,
            "depth": int(depth) if depth.isdigit() else 0,
            "stable_rounds": int(stable_rounds) if stable_rounds.isdigit() else 0,
            "reflow_count": int(reflow_count) if reflow_count.isdigit() else 0,
            "description": description
        }
        
    return {
        "tree_enabled": True,
        "nodes": list(nodes.values()),
        "root": root_id
    }

@app.post("/api/projects/{proj_id}/reject")
def reject_project(proj_id: str, req: RejectRequest):
    proj = get_project_by_id(proj_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
        
    if proj["is_running"]:
        raise HTTPException(status_code=400, detail="Cannot reject while project is running. Stop it first.")
        
    framework_dir = os.path.dirname(HERE)
    run_py = os.path.join(framework_dir, "engine", "run.py")
    
    try:
        state_dir = os.path.join(proj["repo"], ".loop", proj["workspace"], ".loop_state")
        os.makedirs(state_dir, exist_ok=True)
        spawn_log_path = os.path.join(state_dir, "spawn.log")
        with open(spawn_log_path, "a", encoding="utf-8") as f_out:
            subprocess.Popen(
                [sys.executable, run_py, "--workspace", proj["workspace"], "--stage", "reject", "--subtree", req.subtree_id],
                cwd=proj["repo"],
                stdout=f_out,
                stderr=f_out
            )
        return {"status": "rejected_and_planning"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

async def log_generator(log_path: str, tail: int = 500):
    if not os.path.exists(log_path):
        yield f"data: Log file not found at {log_path}\n\n"
        return
        
    try:
        size_at_start = 0
        if os.path.exists(log_path):
            size_at_start = os.path.getsize(log_path)

        # 1. Send historical lines
        history_lines = get_last_n_lines(log_path, tail)
        for line in history_lines:
            safe_line = line.replace('\r', '').replace('\n', ' ')
            yield f"data: {safe_line}\n\n"
            
        # 2. Send divider
        yield "data: --- end of history (live) ---\n\n"
        
        # 3. Stream new lines
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            f.seek(size_at_start)
            while True:
                line = f.readline()
                if not line:
                    await asyncio.sleep(0.5)
                    continue
                safe_line = line.strip().replace('\r', '').replace('\n', ' ')
                yield f"data: {safe_line}\n\n"
    except asyncio.CancelledError:
        pass

@app.get("/api/projects/{proj_id}/logs/{log_type}")
def stream_logs(proj_id: str, log_type: str, tail: int = 500):
    proj = get_project_by_id(proj_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
        
    if log_type not in ["loop", "plan"]:
        raise HTTPException(status_code=400, detail="Invalid log type")
        
    log_file = f"{log_type}.log"
    log_path = os.path.join(proj["repo"], ".loop", proj["workspace"], log_file)
    
    return StreamingResponse(log_generator(log_path, tail), media_type="text/event-stream")

@app.get("/api/projects/{proj_id}/logs/{log_type}/download")
def download_log(proj_id: str, log_type: str):
    proj = get_project_by_id(proj_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
        
    if log_type not in ["loop", "plan"]:
        raise HTTPException(status_code=400, detail="Invalid log type")
        
    log_file = f"{log_type}.log"
    log_path = os.path.join(proj["repo"], ".loop", proj["workspace"], log_file)
    
    if not os.path.exists(log_path):
        raise HTTPException(status_code=404, detail="Log file not found")
        
    return FileResponse(log_path, media_type="text/plain", filename=f"{proj['repo_name']}-{proj['workspace']}-{log_file}")

@app.get("/api/projects/{proj_id}/activity")
def get_activity(proj_id: str, limit: int = 50):
    proj = get_project_by_id(proj_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
        
    log_path = os.path.join(proj["repo"], ".loop", proj["workspace"], "loop.log")
    if not os.path.exists(log_path):
        return []
        
    lines = get_last_n_lines(log_path, 600)
    events = []
    
    for line in reversed(lines):
        line_str = line.strip()
        if not line_str:
            continue
            
        matched_type = None
        for act_type, check_fn in ACTIVITY_CLASSIFICATION_RULES:
            if check_fn(line_str):
                matched_type = act_type
                break
                
        if matched_type:
            ts, text = parse_timestamp(line_str)
            events.append({
                "ts": ts,
                "type": matched_type,
                "text": text
            })
            if len(events) >= limit:
                break
                
    return events

import fnmatch

@app.get("/api/projects/{proj_id}/doc")
def get_project_doc(proj_id: str, path: str):
    proj = get_project_by_id(proj_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
        
    repo = proj["repo"]
    ws = proj["workspace"]
    
    base_dir = os.path.realpath(os.path.join(repo, ".loop", ws))
    target_path = os.path.realpath(os.path.join(base_dir, path))
    
    try:
        common = os.path.commonpath([base_dir, target_path])
        if common != base_dir:
            raise HTTPException(status_code=403, detail="Path traversal detected")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid path structure")
        
    rel_path = os.path.relpath(target_path, base_dir)
    normalized_rel = rel_path.replace(os.sep, "/")
    
    is_whitelisted = False
    if normalized_rel == "REQUIREMENTS.md":
        is_whitelisted = True
    elif fnmatch.fnmatch(normalized_rel, "phases/PHASE*.md"):
        is_whitelisted = True
    elif fnmatch.fnmatch(normalized_rel, "tree/*.decomp.md"):
        is_whitelisted = True
        
    if not is_whitelisted:
        raise HTTPException(status_code=403, detail="Access denied for the requested path")
        
    if not os.path.exists(target_path):
        raise HTTPException(status_code=404, detail="Requested document not found")
        
    try:
        with open(target_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        return {
            "path": normalized_rel,
            "content": content
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read file: {e}")

@app.get("/api/projects/{proj_id}/diff")
def get_project_diff(proj_id: str):
    proj = get_project_by_id(proj_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
        
    repo = proj["repo"]
    ws = proj["workspace"]
    
    sha_path = os.path.join(repo, ".loop", ws, ".loop_state", "last_safe_sha")
    base_sha = None
    if os.path.exists(sha_path):
        try:
            with open(sha_path, "r", encoding="utf-8") as sf:
                base_sha = sf.read().strip()
        except Exception:
            pass
            
    head_sha = None
    try:
        r = subprocess.run(["git", "-C", repo, "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True)
        head_sha = r.stdout.strip()
    except Exception:
        pass
        
    diff_content = ""
    resolved_base = base_sha
    
    if resolved_base:
        try:
            r = subprocess.run(["git", "-C", repo, "diff", resolved_base, "HEAD"], capture_output=True, text=True, check=True)
            diff_content = r.stdout
        except Exception:
            resolved_base = None
            
    if not resolved_base:
        try:
            r = subprocess.run(["git", "-C", repo, "diff", "HEAD~1", "HEAD"], capture_output=True, text=True, check=True)
            diff_content = r.stdout
            resolved_base = "HEAD~1"
        except Exception:
            resolved_base = None
            
    limit = 400 * 1024
    truncated = False
    if len(diff_content) > limit:
        diff_content = diff_content[:limit] + "\n...[truncated]"
        truncated = True
        
    return {
        "base": resolved_base,
        "head": head_sha,
        "diff": diff_content,
        "truncated": truncated
    }

@app.get("/")
def serve_index():
    index_html = os.path.join(TEMPLATES_DIR, "index.html")
    if not os.path.exists(index_html):
        return HTMLResponse("<h1>Dashboard templates not found.</h1>")
    with open(index_html, "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())
