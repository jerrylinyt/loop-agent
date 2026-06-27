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
        
def test_parse_control_threshold_normalization():
    with tempfile.TemporaryDirectory() as tmpdir:
        control_path = os.path.join(tmpdir, "CONTROL.md")
        with open(control_path, "w", encoding="utf-8") as f:
            f.write("p1_consecutive_pass: 1\n")
            f.write("p2_consecutive_pass: 2\n")
        # config: phase 1 numeric threshold, phase 2 placeholder string
        with open(os.path.join(tmpdir, "loop.config.yaml"), "w", encoding="utf-8") as f:
            f.write("phases:\n")
            f.write("  - { id: 1, converge_threshold: 3 }\n")
            f.write("  - { id: 2, converge_threshold: <placeholder> }\n")
        data = parse_control_file(control_path)
        by_id = {p["id"]: p for p in data["phases"]}
        assert by_id["1"]["threshold"] == 3          # numeric kept as int
        assert by_id["2"]["threshold"] is None        # placeholder -> None (UI shows plain count)


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

def test_d_features_activity_categorization():
    from dashboard.app import ACTIVITY_CLASSIFICATION_RULES, parse_timestamp
    
    # Test timestamp parsing
    ts, text = parse_timestamp("2026-06-27 22:00:01 ✅ LOOP COMPLETE")
    assert ts == "2026-06-27 22:00:01"
    assert text == "✅ LOOP COMPLETE"
    
    # Test line categorization rules
    lines_and_types = [
        ("2026-06-27 22:00:01 ✅ LOOP COMPLETE", "complete"),
        ("2026-06-27 22:00:01 🚨 [Git Review Gate] REVERT", "review_revert"),
        ("2026-06-27 22:00:01 ⛔ 停下交人類", "human_required"),
        ("2026-06-27 22:00:01 升級模型", "model_upgrade"),
        ("2026-06-27 22:00:01 ↩ 有進展", "progress"),
        ("2026-06-27 22:00:01 🍃 收斂", "leaf_converged")
    ]
    
    for line, expected_type in lines_and_types:
        matched = None
        for act_type, check_fn in ACTIVITY_CLASSIFICATION_RULES:
            if check_fn(line):
                matched = act_type
                break
        assert matched == expected_type, f"Failed for line: {line}"

def test_d_features_d4_heartbeat(monkeypatch):
    import time
    with tempfile.TemporaryDirectory() as tmpdir:
        index_path = os.path.join(tmpdir, "index.md")
        repo_path = os.path.join(tmpdir, "my-repo")
        os.makedirs(os.path.join(repo_path, ".loop", "default", ".loop_state"), exist_ok=True)
        
        with open(index_path, "w", encoding="utf-8") as f:
            f.write("# Loop 專案總覽（自動維護）\n\n")
            f.write("| 專案 | repo | workspace | phase | stuck | 狀態 | 更新 |\n")
            f.write("|------|------|-----------|-------|-------|------|------|\n")
            f.write(f"| my-repo | {repo_path} | default | 1 | 0 | tracked | t |\n")
            
        monkeypatch.setattr("dashboard.app.get_index_path", lambda: index_path)
        
        # Write run.lock
        lock_path = os.path.join(repo_path, ".loop", "default", ".loop_state", "run.lock")
        with open(lock_path, "w", encoding="utf-8") as lf:
            lf.write("pid=12345 started=2026-06-27 22:00:00\n")
            
        # Parse index and check D4 fields
        projects = parse_index()
        assert len(projects) == 1
        assert projects[0]["started_at"] == "2026-06-27 22:00:00"
        assert projects[0]["heartbeat_age"] is not None
        assert projects[0]["heartbeat_age"] >= 0

def test_d_features_d7_doc_restrictions(monkeypatch):
    from fastapi.testclient import TestClient
    from dashboard.app import app
    
    with tempfile.TemporaryDirectory() as tmpdir:
        index_path = os.path.join(tmpdir, "index.md")
        repo_path = os.path.join(tmpdir, "my-repo")
        os.makedirs(os.path.join(repo_path, ".loop", "default", "tree"), exist_ok=True)
        os.makedirs(os.path.join(repo_path, ".loop", "default", "phases"), exist_ok=True)
        
        with open(index_path, "w", encoding="utf-8") as f:
            f.write("# Loop 專案總覽（自動維護）\n\n")
            f.write("| 專案 | repo | workspace | phase | stuck | 狀態 | 更新 |\n")
            f.write("|------|------|-----------|-------|-------|------|------|\n")
            f.write(f"| my-repo | {repo_path} | default | 1 | 0 | tracked | t |\n")
            
        monkeypatch.setattr("dashboard.app.get_index_path", lambda: index_path)
        
        # Create whitelist files
        req_path = os.path.join(repo_path, ".loop", "default", "REQUIREMENTS.md")
        with open(req_path, "w", encoding="utf-8") as f:
            f.write("Target Requirements Content")
            
        node_path = os.path.join(repo_path, ".loop", "default", "tree", "n1.decomp.md")
        with open(node_path, "w", encoding="utf-8") as f:
            f.write("Node Spec Content")
            
        projects = parse_index()
        proj_id = projects[0]["id"]
        
        client = TestClient(app)
        
        # Test whitelisted file
        r1 = client.get(f"/api/projects/{proj_id}/doc?path=REQUIREMENTS.md")
        assert r1.status_code == 200
        assert r1.json()["content"] == "Target Requirements Content"
        
        r2 = client.get(f"/api/projects/{proj_id}/doc?path=tree/n1.decomp.md")
        assert r2.status_code == 200
        assert r2.json()["content"] == "Node Spec Content"
        
        # Test non-whitelisted path (even if it exists)
        non_white = os.path.join(repo_path, ".loop", "default", "secret.txt")
        with open(non_white, "w") as f:
            f.write("secret")
        r3 = client.get(f"/api/projects/{proj_id}/doc?path=secret.txt")
        assert r3.status_code == 403
        
        # Test path traversal block
        r4 = client.get(f"/api/projects/{proj_id}/doc?path=../../../../etc/passwd")
        assert r4.status_code in [400, 403]

def test_d_features_d5_diff_fallback(monkeypatch):
    from fastapi.testclient import TestClient
    from dashboard.app import app
    
    with tempfile.TemporaryDirectory() as tmpdir:
        index_path = os.path.join(tmpdir, "index.md")
        repo_path = os.path.join(tmpdir, "my-repo")
        os.makedirs(os.path.join(repo_path, ".loop", "default", ".loop_state"), exist_ok=True)
        
        with open(index_path, "w", encoding="utf-8") as f:
            f.write("# Loop 專案總覽（自動維護）\n\n")
            f.write("| 專案 | repo | workspace | phase | stuck | 狀態 | 更新 |\n")
            f.write("|------|------|-----------|-------|-------|------|------|\n")
            f.write(f"| my-repo | {repo_path} | default | 1 | 0 | tracked | t |\n")
            
        monkeypatch.setattr("dashboard.app.get_index_path", lambda: index_path)
        
        projects = parse_index()
        proj_id = projects[0]["id"]
        
        client = TestClient(app)
        
        # Test diff endpoint without git repo - should fall back and not crash, returning empty diff
        response = client.get(f"/api/projects/{proj_id}/diff")
        assert response.status_code == 200
        data = response.json()
        assert "diff" in data
        assert data["diff"] == ""

def test_rounds_history_logging():
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "engine"))
    from state import append_round_record, rounds_log_path
    
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = {
            "runtime": {
                "state_dir": tmpdir
            }
        }
        record = {
            "run_id": "test_run:default:12345",
            "round": 1,
            "loop_type": "execute"
        }
        
        append_round_record(cfg, record)
        
        log_file = rounds_log_path(cfg)
        assert os.path.exists(log_file)
        
        import json
        with open(log_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
        assert len(lines) == 1
        data = json.loads(lines[0].strip())
        assert data["run_id"] == "test_run:default:12345"
        assert data["round"] == 1

def test_collect_traces_metrics():
    import sys
    import subprocess
    import json
    with tempfile.TemporaryDirectory() as tmpdir:
        index_path = os.path.join(tmpdir, "index.md")
        repo_a = os.path.join(tmpdir, "repo-a")
        repo_b = os.path.join(tmpdir, "repo-b")
        
        for r in (repo_a, repo_b):
            os.makedirs(os.path.join(r, ".loop", "default", ".loop_state"), exist_ok=True)
            
        with open(index_path, "w", encoding="utf-8") as f:
            f.write("# idx\n\n| 專案 | repo | workspace | phase | stuck | 狀態 | 更新 |\n")
            f.write(f"| repo-a | {repo_a} | default | 1 | 0 | tracked | t |\n")
            f.write(f"| repo-b | {repo_b} | default | 1 | 0 | tracked | t |\n")
            
        with open(os.path.join(repo_a, ".loop", "default", ".loop_state", "rounds.jsonl"), "w") as f:
            f.write(json.dumps({"run_id": "a:default:1", "round": 1, "loop_type": "execute", "phase": "2", "result": "FAIL", "consecutive_pass": 0, "progressed": False, "stuck_level": 0, "enhanced_rounds_used": 0, "ts": "2026-06-27 22:00:00"}) + "\n")
            
        with open(os.path.join(repo_b, ".loop", "default", ".loop_state", "rounds.jsonl"), "w") as f:
            f.write(json.dumps({"run_id": "b:default:1", "round": 1, "loop_type": "execute", "phase": "2", "result": "FAIL", "consecutive_pass": 0, "progressed": False, "stuck_level": 1, "enhanced_rounds_used": 4, "ts": "2026-06-27 22:00:00"}) + "\n")
            
        with open(os.path.join(repo_a, ".loop", "default", ".loop_state", "fail_history"), "w") as f:
            f.write("fp1\nfp2\nfp2\n")
        with open(os.path.join(repo_b, ".loop", "default", ".loop_state", "fail_history"), "w") as f:
            f.write("fp1\n")
            
        collect_py = os.path.join(os.path.dirname(os.path.dirname(__file__)), "engine", "collect_traces.py")
        out_dir = os.path.join(tmpdir, "out")
        r = subprocess.run([
            sys.executable, collect_py,
            "--index", index_path,
            "--out", out_dir,
            "--k", "2"
        ], capture_output=True, text=True)
        
        assert r.returncode == 0
        
        summary_path = os.path.join(out_dir, "summary.json")
        assert os.path.exists(summary_path)
        
        with open(summary_path, "r") as sf:
            summary = json.load(sf)
            
        assert summary["totals"]["repos"] == 2
        assert summary["totals"]["rounds"] == 2
        
        candidates = summary["cross_project_candidates"]
        fp1_cand = next(c for c in candidates if c["signal_key"] == "oscillation:fp1")
        assert fp1_cand["meets_K"] is True
        assert fp1_cand["distinct_repos"] == 2
        
        fp2_cand = next(c for c in candidates if c["signal_key"] == "oscillation:fp2")
        assert fp2_cand["meets_K"] is False




