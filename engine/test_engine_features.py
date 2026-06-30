import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from state import (
    append_round_artifact,
    append_run_finished,
    get_val,
    rounds_log_path,
    set_human_required,
)
from utils import structured_preflight


def test_guarded_state_write_rejects_stale_revision():
    with tempfile.TemporaryDirectory() as tmpdir:
        control_path = os.path.join(tmpdir, "state.json")
        with open(control_path, "w", encoding="utf-8") as f:
            json.dump({"current_phase": "1", "control": {}}, f)

        first = set_human_required(control_path, True, "agent_requested", "Need help", run_id="run-a")
        assert first["ok"] is True
        assert get_val(control_path, "state_revision") == "1"
        assert get_val(control_path, "human_required_code") == "agent_requested"
        assert get_val(control_path, "human_required_reason") == "Need help"

        stale = set_human_required(
            control_path,
            False,
            run_id="run-b",
            source="dashboard_resume",
            expected_revision=0,
        )
        assert stale["ok"] is False
        assert stale["conflict"] is True
        assert get_val(control_path, "human_required") == "true"


def test_structured_preflight_returns_checks():
    cfg = {
        "framework_path": "missing-framework",
        "agent": {
            "models": {"fast": "flash", "normal": "", "thinking": ""},
            "prompts": {
                "base": "x",
                "escalation": "x",
                "git_review": "x",
                "plan": "x",
                "plan_gate": "x",
                "tree_decompose": "x",
                "tree_decompose_gate": "x",
            },
            "build_cmd": "python",
        },
        "phases": [],
        "control": "state.json",
        "runtime": {"state_dir": "."},
        "_workspace": "default",
    }

    result = structured_preflight(cfg, "plan", repo_path=os.getcwd(), workspace="default")
    assert result["workspace"] == "default"
    assert result["stage"] == "plan"
    assert isinstance(result["checks"], list)
    assert any(check["id"] == "framework_path" for check in result["checks"])
    assert any(check["id"] == "requirements_confirmed" for check in result["checks"])


def test_append_run_finished_and_round_artifact():
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = {
            "run_id": "repo:default:1",
            "_workspace": "default",
            "generation": {"mode": "gated"},
            "runtime": {"state_dir": tmpdir},
        }

        append_run_finished(cfg, final_status="complete", exit_code=0, stage="execute")
        append_round_artifact(
            cfg,
            round_no=3,
            loop_type="execute",
            phase="2",
            changed_files=["src/app.py"],
            git_head_before="abc",
            git_head_after="def",
            validation_summary="pytest passed",
            validation_status="passed",
            evidence_files=["report.txt"],
        )

        with open(rounds_log_path(cfg), "r", encoding="utf-8") as f:
            records = [json.loads(line) for line in f if line.strip()]

        assert records[0]["type"] == "run_finished"
        assert records[0]["final_status"] == "complete"
        assert records[1]["type"] == "round_artifact"
        assert records[1]["changed_files"] == ["src/app.py"]
        assert records[1]["validation_status"] == "passed"
