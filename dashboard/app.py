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
import json
import hashlib
import fnmatch
import re

app = FastAPI(title="Loop Engineering Dashboard")

# Ensure dashboard templates/frontend folder exists
HERE = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIST = os.path.join(HERE, "frontend", "dist")
STATIC_DIR = os.path.join(HERE, "static")

# Mount Vite compiled assets if dist exists
if os.path.exists(FRONTEND_DIST):
    app.mount("/assets", StaticFiles(directory=os.path.join(FRONTEND_DIST, "assets")), name="assets")
else:
    # Fallback to old static files
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


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

class ConfigWizardRequest(BaseModel):
    build_cmd: str
    fast_model: str
    normal_model: str
    thinking_model: str
    mode: str = "gated"
    extra_args: list[str] = []

class InitRequest(BaseModel):
    repo_path: str
    workspace_name: str = "default"

class AddProjectRequest(BaseModel):
    repo_path: str
    workspace_name: str = "default"

class ParallelAddRequest(BaseModel):
    repo_path: str
    branch: str
    workspace_name: Optional[str] = None
    target_path: Optional[str] = None
    base_ref: Optional[str] = None

class RejectRequest(BaseModel):
    subtree_id: str


# Helper Functions
def get_index_path():
    return os.path.expanduser("~/.loop/index.md")

def get_control_val(control_path: str, key: str) -> str | None:
    if not os.path.exists(control_path):
        return None
    try:
        with open(control_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        import re
        m = re.match(r"^node_(\S+?)_(state|children|parent|depth|stable_rounds|reflow_count)$", key)
        if m:
            nid = m.group(1)
            sub_key = m.group(2)
            node = data.get("tree", {}).get("nodes", {}).get(nid, {})
            if sub_key == "children":
                return ",".join(node.get("children", []))
            return str(node.get(sub_key, ""))

        pm = re.match(r"^p(\d+)_(consecutive_pass|total_validations|last_result)$", key)
        if pm:
            pid = pm.group(1)
            sub_key = pm.group(2)
            for ph in data.get("phases", []):
                if str(ph.get("id")) == pid:
                    return str(ph.get(sub_key, ""))

        if key in ("current_phase", "plan_version", "framework_ref"):
            return str(data.get(key, ""))
        if key == "blocking_issues":
            issues = data.get("issues", [])
            blocking = len([i for i in issues if i.get("status") == "OPEN" and i.get("level") == "BLOCKING"])
            return str(blocking)

        if key.startswith("plan_"):
            attr = key[5:]
            val = data.get("plan", {}).get(attr)
            if isinstance(val, bool):
                return "true" if val else "false"
            return str(val) if val is not None else ""

        ctrl = data.get("control", {})
        if key in ctrl:
            val = ctrl.get(key)
            if isinstance(val, bool):
                return "true" if val else "false"
            return str(val) if val is not None else ""
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
    try:
        with open(control_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        import re
        m = re.match(r"^node_(\S+?)_(state|stable_rounds|reflow_count)$", key)
        if m:
            nid = m.group(1)
            sub_key = m.group(2)
            if "tree" not in data:
                data["tree"] = {}
            if "nodes" not in data["tree"]:
                data["tree"]["nodes"] = {}
            if nid not in data["tree"]["nodes"]:
                data["tree"]["nodes"][nid] = {}
            val = value
            if sub_key in ("stable_rounds", "reflow_count"):
                try:
                    val = int(value)
                except ValueError:
                    val = 0
            data["tree"]["nodes"][nid][sub_key] = val
        elif key.startswith("p") and "_" in key:
            pm = re.match(r"^p(\d+)_(consecutive_pass|total_validations|last_result)$", key)
            if pm:
                pid = pm.group(1)
                sub_key = pm.group(2)
                target_ph = None
                for ph in data.get("phases", []):
                    if str(ph.get("id")) == pid:
                        target_ph = ph
                        break
                if not target_ph:
                    target_ph = {"id": pid, "tasks": [], "coverage": []}
                    data.setdefault("phases", []).append(target_ph)
                if sub_key in ("consecutive_pass", "total_validations"):
                    try:
                        target_ph[sub_key] = int(value)
                    except ValueError:
                        target_ph[sub_key] = 0
                else:
                    target_ph[sub_key] = value
        elif key == "current_phase":
            data["current_phase"] = value
        elif key == "plan_version":
            try:
                data["plan_version"] = int(value)
            except ValueError:
                data["plan_version"] = 1
        elif key == "framework_ref":
            data["framework_ref"] = value
        elif key.startswith("plan_"):
            attr = key[5:]
            if "plan" not in data:
                data["plan"] = {}
            val = value
            if value == "true":
                val = True
            elif value == "false":
                val = False
            elif attr in ("stable_rounds", "rounds_since_progress", "stuck_level", "enhanced_rounds_used", "version"):
                try:
                    val = int(value)
                except ValueError:
                    val = 0
            data["plan"][attr] = val
        else:
            if "control" not in data:
                data["control"] = {}
            val = value
            if value == "true":
                val = True
            elif value == "false":
                val = False
            data["control"][key] = val

        temp_file = control_path + ".tmp"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(temp_file, control_path)
    except Exception as e:
        print(f"Failed to set state.json value: {e}")

def parse_control_file(control_path: str) -> dict:
    if not os.path.exists(control_path):
        return {}
    try:
        with open(control_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        res = {}
        res["current_phase"] = str(data.get("current_phase", "1"))
        res["plan_version"] = str(data.get("plan_version", 1))
        res["framework_ref"] = data.get("framework_ref", "")

        issues = data.get("issues", [])
        blocking_issues = len([i for i in issues if i.get("status") == "OPEN" and i.get("level") == "BLOCKING"])
        res["blocking_issues"] = str(blocking_issues)

        ctrl = data.get("control", {})
        for k, v in ctrl.items():
            if isinstance(v, bool):
                res[k] = "true" if v else "false"
            else:
                res[k] = str(v) if v is not None else ""

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
                                    try:
                                        thresholds[p_id] = int(p_conf.get("converge_threshold"))
                                    except (TypeError, ValueError):
                                        thresholds[p_id] = None
            except Exception:
                pass

        phases_list = []
        for ph in data.get("phases", []):
            pid = str(ph.get("id"))
            consec = ph.get("consecutive_pass", 0)
            tot = ph.get("total_validations", 0)
            last_res = ph.get("last_result", "")
            threshold_val = thresholds.get(pid)
            phases_list.append({
                "id": pid,
                "consecutive_pass": str(consec),
                "total_validations": str(tot),
                "last_result": last_res if last_res else "N/A",
                "threshold": threshold_val
            })
        res["phases"] = phases_list
        res["requirements_map"] = data.get("requirements_map", [])
        res["issues"] = data.get("issues", [])
        res["plan"] = data.get("plan", {})
        res["mode"] = data.get("mode", "flat")
        res["repo_structure"] = data.get("repo_structure", "")
        return res
    except Exception as e:
        print(f"Failed to parse state.json: {e}")
        return {}

def parse_index():
    index_path = get_index_path()
    projects = []
    if not os.path.exists(index_path):
        return projects
    
    try:
        header_seen = False
        with open(index_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line.startswith("|") or set(line) <= set("|-: "):
                    continue
                if not header_seen:
                    header_seen = True
                    continue

                parts = [p.strip() for p in line.split("|")][1:-1]
                if len(parts) >= 7:
                    repo_name, repo_path, ws, phase, stuck, status, updated_at = parts[:7]
                    proj_id = hashlib.md5(f"{repo_path}_{ws}".encode()).hexdigest()
                    
                    # Read real-time values from state.json if it exists
                    control_path = os.path.join(repo_path, ".loop", ws, "state.json")
                    if os.path.exists(control_path):
                        r_phase = get_control_val(control_path, "current_phase")
                        r_stuck = get_control_val(control_path, "stuck_level")
                        r_human = get_control_val(control_path, "human_required")
                        r_done = get_control_val(control_path, "stop_condition_met")
                        r_last = get_control_val(control_path, "last_round_result")
                        
                        r_plan_human = get_control_val(control_path, "plan_human_required")
                        if r_plan_human == "true":
                            r_human = "true"

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

def index_row_matches(line: str, repo: str, ws: str) -> bool:
    parts = [p.strip() for p in line.split("|")][1:-1]
    if len(parts) >= 3:
        # parts[1] is repo path, parts[2] is workspace name
        return os.path.realpath(parts[1]) == os.path.realpath(repo) and parts[2] == ws
    return False

def append_index_row(repo: str, ws: str, phase="-", stuck="-", status="initialized"):
    index_path = get_index_path()
    os.makedirs(os.path.dirname(index_path), exist_ok=True)
    
    lines = []
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            
    # Check if exists, update it if so
    found = False
    for i, line in enumerate(lines):
        if line.strip().startswith("|") and not set(line.strip()) <= set("|-: "):
            if index_row_matches(line, repo, ws):
                repo_name = os.path.basename(repo)
                updated_at = time.strftime("%Y-%m-%d %H:%M:%S")
                lines[i] = f"| {repo_name} | {repo} | {ws} | {phase} | {stuck} | {status} | {updated_at} |\n"
                found = True
                break
                
    if not found:
        # Create table headers if empty
        if not lines:
            lines.append("| Repo | Path | Workspace | Phase | Stuck | Status | Updated At |\n")
            lines.append("| --- | --- | --- | --- | --- | --- | --- |\n")
        repo_name = os.path.basename(repo)
        updated_at = time.strftime("%Y-%m-%d %H:%M:%S")
        lines.append(f"| {repo_name} | {repo} | {ws} | {phase} | {stuck} | {status} | {updated_at} |\n")
        
    with open(index_path, "w", encoding="utf-8") as f:
        f.writelines(lines)


# --- NEW WORKSPACE API ENDPOINTS ---

@app.get("/api/workspaces")
def list_workspaces():
    projects = parse_index()
    workspaces = []
    for p in projects:
        control_path = os.path.join(p["repo"], ".loop", p["workspace"], "state.json")
        direction = "neutral"
        headline = "Idle"
        why = ""
        mode = "flat"
        
        state_data = {}
        if os.path.exists(control_path):
            try:
                with open(control_path, "r", encoding="utf-8") as sf:
                    state_data = json.load(sf)
                mode = state_data.get("mode", "flat")
            except Exception:
                pass
                
        status = "idle"
        if p["is_running"]:
            status = "running"
        
        r_human = get_control_val(control_path, "human_required")
        r_plan_human = get_control_val(control_path, "plan_human_required")
        if r_human == "true" or r_plan_human == "true":
            status = "human_required"
            
        r_done = get_control_val(control_path, "stop_condition_met")
        if r_done == "true":
            status = "completed"
            
        stuck_level = 0
        try:
            stuck_level = int(p["stuck"]) if p["stuck"] != "-" else 0
        except ValueError:
            pass
            
        rounds_since_progress = 0
        try:
            rounds_since_progress = int(get_control_val(control_path, "plan_rounds_since_progress") or "0")
        except ValueError:
            pass
            
        if status == "completed":
            direction = "forward"
        elif status == "human_required":
            direction = "neutral"
        elif stuck_level > 0 or rounds_since_progress > 2:
            direction = "stalled"
        elif rounds_since_progress > 0:
            direction = "neutral"
        else:
            r_last = get_control_val(control_path, "last_round_result")
            if r_last == "PASS":
                direction = "forward"
            elif r_last == "FAIL":
                direction = "backward"
            else:
                direction = "neutral"
                
        if status == "running":
            headline = f"Running Phase {p['phase']}"
            why = f"Stuck level is {stuck_level}. Active in {p['workspace']}."
        elif status == "human_required":
            headline = "Needs Human Input"
            why = get_control_val(control_path, "human_required_msg") or get_control_val(control_path, "plan_human_required_msg") or "Waiting for confirmation."
        elif status == "completed":
            headline = "Loop Completed"
            why = "All phases and tasks have converged successfully!"
        else:
            headline = f"Workspace is {status}"
            why = f"Last updated at {p['updated_at']}."
            
        workspaces.append({
            "id": p["id"],
            "repo": p["repo"],
            "repo_name": p["repo_name"],
            "workspace": p["workspace"],
            "mode": mode,
            "status": status,
            "direction": direction,
            "headline": headline,
            "why": why,
            "current": {
                "phase": p["phase"],
                "active_leaf": get_control_val(control_path, "active_leaf") or None,
                "stuck_level": stuck_level,
                "rounds_since_progress": rounds_since_progress,
                "model_tier": get_control_val(control_path, "model_tier") or "default"
            },
            "run": {
                "is_running": p["is_running"],
                "pid": p["pid"],
                "started_at": p["started_at"],
                "heartbeat_age": p["heartbeat_age"]
            },
            "updated_at": p["updated_at"]
        })
    return workspaces

@app.get("/api/workspaces/{id}/overview")
def get_workspace_overview(id: str):
    workspaces = list_workspaces()
    for w in workspaces:
        if w["id"] == id:
            status = w["status"]
            next_action = {
                "kind": "wait",
                "label": "No action needed",
                "detail": "Engine is running stably."
            }
            if status == "human_required":
                next_action = {
                    "kind": "input",
                    "label": "Resume Engine",
                    "detail": "Review the reason in timeline/logs and click Resume to continue."
                }
            elif status == "idle":
                next_action = {
                    "kind": "start",
                    "label": "Start Loop",
                    "detail": "Click Start to begin running the automated loop engine."
                }
            elif status == "completed":
                next_action = {
                    "kind": "review",
                    "label": "All Completed",
                    "detail": "The task is complete. No further actions required."
                }
            elif status == "preflight_blocked":
                next_action = {
                    "kind": "configure",
                    "label": "Fix Preflight Issues",
                    "detail": "Please configure model and build commands before starting."
                }
            w["next_action"] = next_action
            return w
    raise HTTPException(status_code=404, detail="Workspace not found")

@app.post("/api/workspaces/{id}/start")
def start_workspace(id: str, req: StartRequest):
    return start_project(id, req)

@app.post("/api/workspaces/{id}/stop")
def stop_workspace(id: str):
    return stop_project(id)

@app.post("/api/workspaces/{id}/resume")
def resume_workspace(id: str):
    return resume_project(id)

@app.post("/api/workspaces/{id}/clear-lock")
def clear_workspace_lock(id: str):
    return clear_lock(id)

@app.get("/api/workspaces/{id}/preflight")
def get_workspace_preflight(id: str):
    return get_preflight(id)

@app.get("/api/workspaces/{id}/config")
def get_workspace_config(id: str):
    return get_config(id)

@app.post("/api/workspaces/{id}/config")
def save_workspace_config(id: str, req: ConfigUpdateRequest):
    return save_config(id, req)

@app.post("/api/workspaces/{id}/config-wizard")
def apply_workspace_config_wizard(id: str, req: ConfigWizardRequest):
    return apply_config_wizard(id, req)

@app.get("/api/workspaces/{id}/tree")
def get_workspace_tree(id: str):
    return get_project_tree(id)

@app.post("/api/workspaces/{id}/reject")
def reject_workspace_node(id: str, req: RejectRequest):
    return reject_project(id, req)

@app.get("/api/workspaces/{id}/timeline")
def get_workspace_timeline(id: str, limit: int = 100):
    proj = get_project_by_id(id)
    if not proj:
        raise HTTPException(status_code=404, detail="Workspace not found")
        
    rounds_path = os.path.join(proj["repo"], ".loop", proj["workspace"], ".loop_state", "rounds.jsonl")
    if not os.path.exists(rounds_path):
        return []
        
    events = []
    try:
        # Efficient O(1) parsing from tail
        lines = get_last_n_lines(rounds_path, limit * 2)
        for line in lines:
            line_str = line.strip()
            if not line_str:
                continue
            try:
                record = json.loads(line_str)
            except Exception:
                continue
                
            rec_type = record.get("type")
            ts = record.get("ts", "")
            
            severity = "info"
            title = "Event"
            detail = ""
            event_type = "unknown"
            
            if rec_type in ("loop_complete", "loop_completed"):
                event_type = "loop_completed"
                severity = "success"
                title = "Loop Completed Successfully!"
                detail = record.get('message', 'All stages and criteria have converged.')
            elif rec_type == "review_revert":
                event_type = "review_reverted"
                severity = "error"
                title = "Git Review Gate Reverted Changes"
                detail = record.get('message', 'Validation failed or review gate rejected modifications.')
            elif rec_type == "human_required":
                event_type = "human_required"
                severity = "warning"
                title = "Human Intervention Required"
                detail = record.get('message', 'An action is required from you to proceed.')
            elif rec_type == "round_finished":
                result = record.get("result", "UNKNOWN")
                phase = record.get("phase", "?")
                
                if result == "PASS":
                    event_type = "round_passed"
                    severity = "success"
                    title = f"Round {record.get('round')} Passed"
                    detail = f"Phase {phase} validation succeeded."
                    
                    if record.get("progressed"):
                        event_type = "progress_made"
                        title = "Progress Made!"
                        detail = f"Phase {phase} pass counter advanced."
                else:
                    event_type = "round_failed"
                    severity = "error"
                    title = f"Round {record.get('round')} Failed"
                    detail = f"Phase {phase} validation failed."
                    
                    if record.get("stuck_level", 0) > 0:
                        event_type = "model_escalated"
                        severity = "warning"
                        title = f"Model Escalated (Stuck Level {record.get('stuck_level')})"
                        detail = f"Switched to model tier: {record.get('model_tier') or 'thinking'} to resolve stalling."
            
            if event_type != "unknown":
                events.append({
                    "ts": ts,
                    "type": event_type,
                    "severity": severity,
                    "title": title,
                    "detail": detail
                })
    except Exception as e:
        print(f"Error reading timeline: {e}")
        
    return list(reversed(events))[:limit]

@app.get("/api/workspaces/{id}/progress")
def get_workspace_progress(id: str, limit: int = 200):
    proj = get_project_by_id(id)
    if not proj:
        raise HTTPException(status_code=404, detail="Workspace not found")
        
    rounds_path = os.path.join(proj["repo"], ".loop", proj["workspace"], ".loop_state", "rounds.jsonl")
    if not os.path.exists(rounds_path):
        return []
        
    records = []
    try:
        for line in get_last_n_lines(rounds_path, limit):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except Exception:
                continue
            if record.get("type") == "round_finished":
                records.append({
                    "round": record.get("round", 0),
                    "ts": record.get("ts", ""),
                    "phase": str(record.get("phase", "1")),
                    "result": record.get("result", "UNKNOWN"),
                    "progressed": record.get("progressed", False),
                    "direction": "forward" if record.get("result") == "PASS" else "backward",
                    "stuck_level": record.get("stuck_level", 0),
                    "rounds_since_progress": record.get("rounds_since_progress", 0),
                    "model_tier": record.get("model_tier", "default"),
                    "fail_fingerprint": record.get("fail_fingerprint"),
                    "summary": record.get("summary", "Round execution finished.")
                })
    except Exception as e:
        print(f"Error reading progress: {e}")
    return records

@app.get("/api/workspaces/{id}/logs/{log_type}")
def stream_workspace_logs(id: str, log_type: str, tail: int = 500):
    return stream_logs(id, log_type, tail)

@app.get("/api/workspaces/{id}/logs/{log_type}/download")
def download_workspace_log(id: str, log_type: str):
    return download_log(id, log_type)

@app.get("/api/workspaces/{id}/diagnostics")
def get_workspace_diagnostics(id: str):
    proj = get_project_by_id(id)
    if not proj:
        raise HTTPException(status_code=404, detail="Workspace not found")
        
    state_path = os.path.join(proj["repo"], ".loop", proj["workspace"], "state.json")
    raw_state = {}
    if os.path.exists(state_path):
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                raw_state = json.load(f)
        except Exception:
            pass
            
    diff_data = get_project_diff(id)
    
    return {
        "raw_state": raw_state,
        "git_diff": diff_data,
        "config_path": proj["config_path"],
        "lock_path": os.path.join(proj["repo"], ".loop", proj["workspace"], ".loop_state", "run.lock")
    }

@app.get("/api/workspaces/{id}/doc")
def get_workspace_doc(id: str, path: str):
    return get_project_doc(id, path)

@app.get("/api/workspaces/{id}/diff")
def get_workspace_diff(id: str):
    return get_project_diff(id)

@app.post("/api/workspaces/init")
def workspace_init(req: InitRequest):
    return init_project(req)

@app.post("/api/workspaces/add")
def workspace_add(req: AddProjectRequest):
    return add_project(req)

@app.delete("/api/workspaces/{id}")
def untrack_workspace(id: str):
    return untrack_project(id)


# --- OLD PROJECT API ENDPOINTS (STIPPLED / ALIASED FOR COMPATIBILITY) ---

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
            
        append_index_row(repo_path, req.workspace_name, status="initialized")
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
        
    control_path = os.path.join(repo_path, ".loop", req.workspace_name, "state.json")
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
            
    append_index_row(repo_path, req.workspace_name, phase=phase, stuck=stuck, status=status)
    return {"status": "added"}

@app.post("/api/parallel/add")
def add_parallel_worktree(req: ParallelAddRequest):
    repo_path = os.path.abspath(os.path.expanduser(req.repo_path))
    if not os.path.isdir(repo_path):
        raise HTTPException(status_code=400, detail="Repository path does not exist or is not a directory.")
    if not req.branch.strip():
        raise HTTPException(status_code=400, detail="Branch name is required.")

    framework_dir = os.path.dirname(HERE)
    parallel_py = os.path.join(framework_dir, "parallel.py")
    cmd = [sys.executable, parallel_py, "add", req.branch.strip()]
    workspace = (req.workspace_name or "").strip()
    if workspace:
        cmd.extend(["--name", workspace])
    else:
        workspace = req.branch.strip().replace("/", "-")
    if req.target_path:
        cmd.extend(["--path", os.path.abspath(os.path.expanduser(req.target_path))])
    if req.base_ref:
        cmd.extend(["--base", req.base_ref])

    try:
        # run parallel.py
        result = subprocess.run(cmd, cwd=framework_dir, capture_output=True, text=True)
        if result.returncode != 0:
            raise HTTPException(status_code=500, detail=f"Parallel worktree creation failed: {result.stderr or result.stdout}")
        
        # parallel add automatically initialises the workspace, so we track it
        target_wt_path = os.path.join(os.path.dirname(repo_path), workspace)
        if req.target_path:
            target_wt_path = os.path.abspath(os.path.expanduser(req.target_path))
            
        append_index_row(target_wt_path, workspace, status="initialized")
        return {"status": "added", "output": result.stdout}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/projects/{proj_id}/human-context")
def get_human_context(proj_id: str):
    proj = get_project_by_id(proj_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
        
    control_path = os.path.join(proj["repo"], ".loop", proj["workspace"], "state.json")
    r_human = get_control_val(control_path, "human_required")
    is_human = (r_human == "true")
    
    r_plan_human = get_control_val(control_path, "plan_human_required")
    is_plan_human = (r_plan_human == "true")
    
    is_any_human = is_human or is_plan_human
    
    reason = ""
    log_excerpt = ""
    reason_code = ""
    if is_any_human:
        if is_human:
            reason = get_control_val(control_path, "human_required_msg") or get_control_val(control_path, "human_required_reason") or ""
            reason_code = get_control_val(control_path, "human_required_reason") or ""
        else:
            reason = get_control_val(control_path, "plan_human_required_msg") or get_control_val(control_path, "plan_human_required_reason") or ""
            reason_code = get_control_val(control_path, "plan_human_required_reason") or ""
            
    return {
        "human_required": is_any_human,
        "reason": reason,
        "reason_code": reason_code,
        "log_excerpt": log_excerpt
    }

@app.post("/api/projects/{proj_id}/resume")
def resume_project(proj_id: str):
    proj = get_project_by_id(proj_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
        
    if proj["is_running"]:
        raise HTTPException(status_code=400, detail="Cannot resume while project is running. Stop it first.")
        
    control_path = os.path.join(proj["repo"], ".loop", proj["workspace"], "state.json")

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
    set_control_val(control_path, "human_required_reason", "")
    set_control_val(control_path, "human_required_msg", "")
    
    set_control_val(control_path, "plan_human_required", "false")
    set_control_val(control_path, "plan_human_required_reason", "")
    set_control_val(control_path, "plan_human_required_msg", "")
    
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
        
    control_path = os.path.join(proj["repo"], ".loop", proj["workspace"], "state.json")
    return parse_control_file(control_path)

@app.delete("/api/projects/{proj_id}")
def untrack_project(proj_id: str):
    proj = get_project_by_id(proj_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
        
    index_path = get_index_path()
    if not os.path.exists(index_path):
        return {"status": "untracked"}
        
    try:
        lines = []
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
            try:
                os.remove(lock_path)
            except Exception:
                pass
        return {"status": "stopped"}
    except psutil.NoSuchProcess:
        # Lock exists but process is already dead
        lock_path = os.path.join(proj["repo"], ".loop", proj["workspace"], ".loop_state", "run.lock")
        if os.path.exists(lock_path):
            try:
                os.remove(lock_path)
            except Exception:
                pass
        return {"status": "stopped"}
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
        yaml.safe_load(req.content)
        with open(config_path, "w", encoding="utf-8") as f:
            f.write(req.content)
        return {"status": "saved"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid YAML: {e}")

def yaml_inline(value) -> str:
    import json
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=False)
    return json.dumps(str(value), ensure_ascii=False)

def replace_config_wizard_fields(content: str, req: ConfigWizardRequest) -> str:
    replacements = {
        ("generation", "mode"): yaml_inline(req.mode),
        ("agent", "build_cmd"): yaml_inline(req.build_cmd.strip()),
        ("agent", "extra_args"): yaml_inline(req.extra_args or []),
        ("agent.models", "fast"): yaml_inline(req.fast_model.strip()),
        ("agent.models", "normal"): yaml_inline(req.normal_model.strip()),
        ("agent.models", "thinking"): yaml_inline(req.thinking_model.strip()),
    }
    seen = set()
    lines = content.splitlines(keepends=True)
    out = []
    top = None
    in_agent_models = False

    for line in lines:
        raw = line.rstrip("\r\n")
        newline = line[len(raw):]
        stripped = raw.lstrip()
        indent = len(raw) - len(stripped)

        if stripped and not stripped.startswith("#"):
            top_match = re.match(r"^([A-Za-z0-9_]+)\s*:", stripped)
            if indent == 0 and top_match:
                top = top_match.group(1)
                in_agent_models = False

            if top == "agent" and indent == 2 and re.match(r"^models\s*:", stripped):
                in_agent_models = True
            elif top == "agent" and in_agent_models and indent <= 2 and not re.match(r"^models\s*:", stripped):
                in_agent_models = False

            key_match = re.match(r"^([A-Za-z0-9_]+)\s*:", stripped)
            if key_match:
                key = key_match.group(1)
                section = "agent.models" if top == "agent" and in_agent_models and indent == 4 else top
                rep_key = (section, key)
                if rep_key in replacements:
                    comment = ""
                    if "#" in raw:
                        comment = "  #" + raw.split("#", 1)[1]
                    out.append(" " * indent + f"{key}: {replacements[rep_key]}{comment}{newline}")
                    seen.add(rep_key)
                    continue

        out.append(line)

    missing = set(replacements) - seen
    if missing:
        raise ValueError(f"Could not find required config fields: {', '.join('.'.join(k) for k in sorted(missing))}")
    return "".join(out)

@app.post("/api/projects/{proj_id}/config-wizard")
def apply_config_wizard(proj_id: str, req: ConfigWizardRequest):
    proj = get_project_by_id(proj_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    if req.mode not in ["auto", "gated"]:
        raise HTTPException(status_code=400, detail="Invalid generation mode")

    required = [req.build_cmd, req.fast_model, req.normal_model, req.thinking_model]
    if any(not (v or "").strip() for v in required):
        raise HTTPException(status_code=400, detail="Build command and all three model names are required.")

    config_path = proj["config_path"]
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            original = f.read()
        cfg = yaml.safe_load(original) or {}
        if not isinstance(cfg, dict):
            raise ValueError("Config root must be a mapping")

        with open(config_path, "w", encoding="utf-8") as f:
            f.write(replace_config_wizard_fields(original, req))
        return {"status": "saved"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to update config: {e}")

def requirements_path_for_project(proj: dict) -> str:
    return os.path.join(proj["repo"], ".loop", proj["workspace"], "REQUIREMENTS.md")

def has_placeholder(value) -> bool:
    if not value or not isinstance(value, str):
        return False
    return "[TODO" in value or "<TODO" in value or "PLACEHOLDER" in value or "__" in value

@app.get("/api/projects/{proj_id}/preflight")
def get_preflight(proj_id: str):
    proj = get_project_by_id(proj_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")

    checks = []

    repo_exists = os.path.isdir(proj["repo"])
    checks.append({"id": "repo", "label": "Repo path exists", "ok": repo_exists, "detail": proj["repo"]})

    req_path = requirements_path_for_project(proj)
    req_exists = os.path.exists(req_path)
    req_confirmed = False
    if req_exists:
        try:
            with open(req_path, "r", encoding="utf-8", errors="replace") as f:
                req_confirmed = "REQUIREMENTS CONFIRMED" in f.read()
        except Exception:
            pass
    checks.append({"id": "requirements", "label": "Requirements confirmed", "ok": req_exists and req_confirmed, "detail": "confirmed" if req_confirmed else "missing confirmation marker"})

    config_ok = False
    config_detail = "missing config"
    cfg = {}
    if os.path.exists(proj["config_path"]):
        try:
            with open(proj["config_path"], "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            config_ok = isinstance(cfg, dict)
            config_detail = "valid YAML" if config_ok else "config root is not a mapping"
        except Exception as e:
            config_detail = f"invalid YAML: {e}"
    checks.append({"id": "config_yaml", "label": "Config YAML is readable", "ok": config_ok, "detail": config_detail})

    agent = cfg.get("agent", {}) if isinstance(cfg, dict) else {}
    models = agent.get("models", {}) if isinstance(agent, dict) else {}
    placeholders = []
    if has_placeholder(agent.get("build_cmd")):
        placeholders.append("agent.build_cmd")
    for key in ["fast", "normal", "thinking"]:
        if has_placeholder(models.get(key)):
            placeholders.append(f"agent.models.{key}")
    checks.append({"id": "agent_config", "label": "Agent command and models filled", "ok": not placeholders, "detail": ", ".join(placeholders) if placeholders else "ready"})

    mode = ((cfg.get("generation") or {}).get("mode") if isinstance(cfg, dict) else None)
    checks.append({"id": "generation_mode", "label": "Generation mode is valid", "ok": mode in ["auto", "gated"], "detail": str(mode or "missing")})

    lock_detail = "not locked"
    lock_ok = not proj.get("is_running") and not proj.get("stale_lock")
    if proj.get("is_running"):
        lock_detail = f"running pid={proj.get('pid')}"
    elif proj.get("stale_lock"):
        lock_detail = "stale lock present"
    checks.append({"id": "run_lock", "label": "No active/stale run lock", "ok": lock_ok, "detail": lock_detail})

    git_ok = False
    git_detail = "not checked"
    try:
        r = subprocess.run(["git", "-C", proj["repo"], "status", "--short"], capture_output=True, text=True, encoding="utf-8")
        if r.returncode == 0:
            dirty_lines = [ln for ln in r.stdout.splitlines() if ln.strip()]
            git_ok = True
            git_detail = "clean" if not dirty_lines else f"{len(dirty_lines)} changed/untracked files"
        else:
            git_detail = r.stderr.strip() or "git status failed"
    except Exception as e:
        git_detail = str(e)
    checks.append({"id": "git_status", "label": "Git status readable", "ok": git_ok, "detail": git_detail})

    return {
        "ok": all(c["ok"] for c in checks),
        "checks": checks
    }

@app.get("/api/projects/{proj_id}/tree")
def get_project_tree(proj_id: str):
    proj = get_project_by_id(proj_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
        
    state_json = os.path.join(proj["repo"], ".loop", proj["workspace"], "state.json")
    if os.path.exists(state_json):
        try:
            with open(state_json, "r", encoding="utf-8") as f:
                data = json.load(f)
            is_enabled = data.get("mode", "flat") == "tree"
            root_id = data.get("tree", {}).get("root") or "root"
            if not is_enabled:
                return {"tree_enabled": False, "nodes": [], "root": root_id}
                
            nodes_data = data.get("tree", {}).get("nodes", {})
            nodes = {}
            for nid, node in nodes_data.items():
                description = nid
                decomp_path = os.path.join(proj["repo"], ".loop", proj["workspace"], "tree", f"{nid}.decomp.md")
                if os.path.exists(decomp_path):
                    desc_val = get_control_val(decomp_path, "description")
                    if desc_val:
                        description = desc_val
                        
                nodes[nid] = {
                    "id": nid,
                    "state": node.get("state", "PENDING"),
                    "children": node.get("children", []),
                    "parent": node.get("parent") or "",
                    "depth": node.get("depth", 0),
                    "stable_rounds": node.get("stable_rounds", 0),
                    "reflow_count": node.get("reflow_count", 0),
                    "description": description
                }
            return {
                "tree_enabled": True,
                "nodes": list(nodes.values()),
                "root": root_id
            }
        except Exception as e:
            print(f"Failed to load tree from state.json: {e}")

    # Fallback to TREE.md
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

        history_lines = get_last_n_lines(log_path, tail)
        for line in history_lines:
            safe_line = line.replace('\r', '').replace('\n', ' ')
            yield f"data: {safe_line}\n\n"
            
        yield "data: --- end of history (live) ---\n\n"
        
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

@app.get("/api/projects/{proj_id}/rounds")
def get_project_rounds(proj_id: str, limit: int = 200):
    return get_workspace_progress(proj_id, limit)

@app.get("/api/projects/{proj_id}/activity")
def get_activity(proj_id: str, limit: int = 50):
    return get_workspace_timeline(proj_id, limit)

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
    
    control_path = os.path.join(repo, ".loop", ws, "state.json")
    base_sha = get_control_val(control_path, "last_safe_sha")
            
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


# Serve React app
@app.get("/")
def serve_dashboard():
    index_path = os.path.join(FRONTEND_DIST, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    
    # Fallback to old index.html
    old_index_html = os.path.join(STATIC_DIR, "index.html")
    if not os.path.exists(old_index_html):
        old_index_html = os.path.join(HERE, "templates", "index.html")
        
    if os.path.exists(old_index_html):
        with open(old_index_html, "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())
            
    return HTMLResponse("<h1>Dashboard frontend not compiled yet. Please build the frontend first.</h1>")
