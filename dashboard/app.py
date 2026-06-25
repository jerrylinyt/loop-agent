import os
import asyncio
import subprocess
import psutil
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, StreamingResponse
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

class StartRequest(BaseModel):
    mode: str = "auto"

class ConfigUpdateRequest(BaseModel):
    content: str

class InitRequest(BaseModel):
    repo_path: str
    workspace_name: str = "default"

def get_index_path():
    return os.path.expanduser("~/.loop/index.md")

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
                    
                    # Check if actually running via lock file
                    is_running = False
                    pid = None
                    lock_path = os.path.join(repo_path, ".loop", ws, ".loop_state", "run.lock")
                    if os.path.exists(lock_path):
                        is_running = True
                        try:
                            with open(lock_path, "r", encoding="utf-8") as lf:
                                lock_data = lf.read()
                                # pid=1234 started=...
                                if lock_data.startswith("pid="):
                                    pid = int(lock_data.split(" ")[0].split("=")[1])
                        except Exception:
                            pass
                    
                    # If process is dead but lock exists, it's stale, but we reflect lock existence for now
                    if pid:
                        try:
                            p = psutil.Process(pid)
                            if not p.is_running() or p.status() == psutil.STATUS_ZOMBIE:
                                is_running = False
                        except psutil.NoSuchProcess:
                            is_running = False

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
                        "config_path": os.path.join(repo_path, ".loop", ws, "loop.config.yaml")
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
    
    framework_dir = os.path.dirname(HERE)
    run_py = os.path.join(framework_dir, "engine", "run.py")
    
    # Spawn subprocess
    try:
        subprocess.Popen(
            ["python", run_py, "--workspace", proj["workspace"], "--mode", req.mode],
            cwd=proj["repo"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
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
            ["python", init_py, repo_path, "--name", req.workspace_name],
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

async def log_generator(log_path: str):
    if not os.path.exists(log_path):
        yield f"data: Log file not found at {log_path}\n\n"
        return
        
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            # Read all existing lines first if file is small, or last 100 lines
            f.seek(0, os.SEEK_END)
            # Just tailing from current end for simplicity, or we could seek back
            # Real implementation might want to send history first.
            yield "data: --- Connected to Log Stream ---\n\n"
            
            while True:
                line = f.readline()
                if not line:
                    await asyncio.sleep(0.5)
                    continue
                # Server Sent Events format
                # Replace newlines in the data string
                safe_line = line.strip().replace('\n', ' ')
                yield f"data: {safe_line}\n\n"
    except asyncio.CancelledError:
        pass

@app.get("/api/projects/{proj_id}/logs/{log_type}")
def stream_logs(proj_id: str, log_type: str):
    proj = get_project_by_id(proj_id)
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
        
    if log_type not in ["loop", "plan"]:
        raise HTTPException(status_code=400, detail="Invalid log type")
        
    log_file = f"{log_type}.log"
    log_path = os.path.join(proj["repo"], ".loop", proj["workspace"], log_file)
    
    return StreamingResponse(log_generator(log_path), media_type="text/event-stream")

@app.get("/")
def serve_index():
    index_html = os.path.join(TEMPLATES_DIR, "index.html")
    if not os.path.exists(index_html):
        return HTMLResponse("<h1>Dashboard templates not found.</h1>")
    with open(index_html, "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())
