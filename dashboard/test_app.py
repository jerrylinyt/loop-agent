import os
import tempfile
import pytest
import psutil
from dashboard.app import get_last_n_lines, parse_index, get_control_val, set_control_val, extract_human_context, parse_control_file, index_row_matches

def test_get_last_n_lines():
    with tempfile.NamedTemporaryFile(delete=False, mode="w+", encoding="utf-8") as tmp:
        # Write some lines
        for i in range(1, 100):
            tmp.write(f"Line {i}\n")
        tmp.flush()
        
        # Test reading last 5 lines
        lines = get_last_n_lines(tmp.name, 5)
        assert len(lines) == 5
        assert lines == ["Line 95", "Line 96", "Line 97", "Line 98", "Line 99"]
        
        # Test reading more lines than exists
        lines = get_last_n_lines(tmp.name, 150)
        assert len(lines) == 99
        assert lines[0] == "Line 1"
        assert lines[-1] == "Line 99"

        # Test empty count
        lines = get_last_n_lines(tmp.name, 0)
        assert lines == []
        
    os.unlink(tmp.name)

def test_get_last_n_lines_nonexistent():
    # Test non-existent file
    assert get_last_n_lines("nonexistent_file.log", 10) == []

def test_parse_index_stale_lock(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a mock index.md
        index_path = os.path.join(tmpdir, "index.md")
        
        # Write mock index
        repo_path = os.path.join(tmpdir, "my-repo")
        os.makedirs(os.path.join(repo_path, ".loop", "default", ".loop_state"), exist_ok=True)
        
        with open(index_path, "w", encoding="utf-8") as f:
            f.write("# Loop 專案總覽（自動維護）\n\n")
            f.write("| 專案 | repo | workspace | phase | stuck | 狀態 | 更新 |\n")
            f.write("|------|------|-----------|-------|-------|------|------|\n")
            f.write(f"| my-repo | {repo_path} | default | 1 | 0 | tracked | 2026-06-27 22:00:00 |\n")
            
        # Mock index path function
        monkeypatch.setattr("dashboard.app.get_index_path", lambda: index_path)
        
        # First check when no lock exists
        projects = parse_index()
        assert len(projects) == 1
        assert projects[0]["is_running"] is False
        assert projects[0]["stale_lock"] is False
        
        # Create a run.lock with a non-existent PID (stale)
        lock_path = os.path.join(repo_path, ".loop", "default", ".loop_state", "run.lock")
        with open(lock_path, "w", encoding="utf-8") as lf:
            lf.write("pid=999999 started=2026-06-27 22:00:00\n")
            
        projects = parse_index()
        assert len(projects) == 1
        assert projects[0]["is_running"] is False
        assert projects[0]["stale_lock"] is True
        
        # Test get_control_val for nonexistent
        assert get_control_val(os.path.join(repo_path, "nonexistent"), "current_phase") is None

def test_set_control_val_and_parse():
    with tempfile.TemporaryDirectory() as tmpdir:
        control_path = os.path.join(tmpdir, "CONTROL.md")
        with open(control_path, "w", encoding="utf-8") as f:
            f.write("current_phase: 1\n")
            f.write("human_required: true\n")
            f.write("p1_consecutive_pass: 3\n")
            
        # Parse it
        data = parse_control_file(control_path)
        assert data["current_phase"] == "1"
        assert data["human_required"] == "true"
        assert len(data["phases"]) == 1
        assert data["phases"][0]["id"] == "1"
        assert data["phases"][0]["consecutive_pass"] == "3"
        
        # Modify value using set_control_val
        set_control_val(control_path, "human_required", "false")
        data_mod = parse_control_file(control_path)
        assert data_mod["human_required"] == "false"
        assert data_mod["current_phase"] == "1"
        
def test_extract_human_context():
    with tempfile.NamedTemporaryFile(delete=False, mode="w+", encoding="utf-8") as tmp:
        tmp.write("log line 1\n")
        tmp.write("log line 2 with human_required set to true due to crash\n")
        tmp.write("log line 3\n")
        tmp.write("log line 4\n")
        tmp.flush()
        
        reason, excerpt = extract_human_context(tmp.name)
        assert "human_required" in reason
        assert "log line 2" in excerpt
        assert "log line 4" in excerpt
        
    os.unlink(tmp.name)

def test_index_row_matches():
    # exact cell match (not substring) so prefix paths don't collide
    row = "| my-repo | /tmp/app | default | 1 | 0 | tracked | 2026-06-27 22:00:00 |"
    assert index_row_matches(row, "/tmp/app", "default") is True
    # prefix path must NOT match
    assert index_row_matches(row, "/tmp/ap", "default") is False
    assert index_row_matches(row, "/tmp/app-2", "default") is False
    # wrong workspace must NOT match
    assert index_row_matches(row, "/tmp/app", "feat-x") is False
    # header / separator / non-rows are ignored
    assert index_row_matches("| 專案 | repo | workspace | phase | stuck | 狀態 | 更新 |", "/tmp/app", "default") is False
    assert index_row_matches("|------|------|------|------|------|------|------|", "/tmp/app", "default") is False
    assert index_row_matches("not a row", "/tmp/app", "default") is False


def test_untrack_exact_match_not_prefix(monkeypatch):
    from fastapi.testclient import TestClient
    from dashboard.app import app
    with tempfile.TemporaryDirectory() as tmpdir:
        index_path = os.path.join(tmpdir, "index.md")
        repo_a = os.path.join(tmpdir, "app")
        repo_b = os.path.join(tmpdir, "app-2")  # shares prefix with repo_a
        for r in (repo_a, repo_b):
            os.makedirs(os.path.join(r, ".loop", "default"), exist_ok=True)
        with open(index_path, "w", encoding="utf-8") as f:
            f.write("# idx\n\n")
            f.write("| 專案 | repo | workspace | phase | stuck | 狀態 | 更新 |\n")
            f.write("|------|------|-----------|-------|-------|------|------|\n")
            f.write(f"| app | {repo_a} | default | 1 | 0 | tracked | t |\n")
            f.write(f"| app-2 | {repo_b} | default | 1 | 0 | tracked | t |\n")
        monkeypatch.setattr("dashboard.app.get_index_path", lambda: index_path)

        client = TestClient(app)
        projects = parse_index()
        a = next(p for p in projects if p["repo"] == repo_a)
        resp = client.delete(f"/api/projects/{a['id']}")
        assert resp.status_code == 200
        # only repo_a removed; repo_b (prefix sibling) survives
        remaining = parse_index()
        repos = {p["repo"] for p in remaining}
        assert repo_a not in repos
        assert repo_b in repos


def test_download_log_endpoint(monkeypatch):
    from fastapi.testclient import TestClient
    from dashboard.app import app
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a mock index.md
        index_path = os.path.join(tmpdir, "index.md")
        repo_path = os.path.join(tmpdir, "my-repo")
        os.makedirs(os.path.join(repo_path, ".loop", "default"), exist_ok=True)
        
        # Create mock index
        with open(index_path, "w", encoding="utf-8") as f:
            f.write("# Loop 專案總覽（自動維護）\n\n")
            f.write("| 專案 | repo | workspace | phase | stuck | 狀態 | 更新 |\n")
            f.write("|------|------|-----------|-------|-------|------|------|\n")
            f.write(f"| my-repo | {repo_path} | default | 1 | 0 | tracked | 2026-06-27 22:00:00 |\n")
            
        monkeypatch.setattr("dashboard.app.get_index_path", lambda: index_path)
        
        # Write dummy log file
        log_path = os.path.join(repo_path, ".loop", "default", "loop.log")
        with open(log_path, "w", encoding="utf-8") as lf:
            lf.write("Line 1 in log\nLine 2 in log\n")
            
        # Get project ID
        projects = parse_index()
        proj_id = projects[0]["id"]
        
        client = TestClient(app)
        
        # Test download endpoint
        response = client.get(f"/api/projects/{proj_id}/logs/loop/download")
        assert response.status_code == 200
        assert "Line 1 in log" in response.text
        
        # Test invalid log type with valid project
        response_invalid = client.get(f"/api/projects/{proj_id}/logs/invalid_type/download")
        assert response_invalid.status_code == 400


