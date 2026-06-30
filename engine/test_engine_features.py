import json
import os
import subprocess
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
    guarded_state_write,
    rounds_log_path,
    set_human_required,
)
from run import reset_execute_state_data
from utils import structured_preflight


STATE_PY = ROOT / "state.py"


def run_state_cli(state_path: str, *args: str, env: dict | None = None):
    cmd = [sys.executable, str(STATE_PY), "--state", state_path, *args]
    return subprocess.run(cmd, capture_output=True, text=True, env=env)


def write_state(path: str, data: dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


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


def test_cli_set_uses_guarded_write_and_stamps_writer():
    with tempfile.TemporaryDirectory() as tmpdir:
        state_path = os.path.join(tmpdir, "state.json")
        write_state(state_path, {
            "current_phase": "1",
            "phases": [{"id": "1", "tasks": []}],
            "control": {},
        })

        first = run_state_cli(state_path, "--run-id", "run-1", "set", "human_required", "true")
        second = run_state_cli(state_path, "--run-id", "run-1", "set", "human_required", "false")

        assert first.returncode == 0
        assert second.returncode == 1
        assert "only be cleared" in second.stderr
        assert get_val(state_path, "state_revision") == "1"
        assert get_val(state_path, "last_writer_source") == "agent_cli"


def test_phase_gate_blocks_and_allows_forward_progress():
    with tempfile.TemporaryDirectory() as tmpdir:
        state_path = os.path.join(tmpdir, "state.json")
        write_state(state_path, {
            "current_phase": "1",
            "phases": [
                {"id": "1", "tasks": [{"id": "TASK-01", "status": "TODO", "conv": 0, "threshold": 1}]},
                {"id": "2", "tasks": []},
            ],
            "issues": [],
            "control": {},
        })

        blocked = run_state_cli(state_path, "set", "current_phase", "2")
        assert blocked.returncode == 1
        assert "blocked" in blocked.stderr

        write_state(state_path, {
            "current_phase": "1",
            "phases": [
                {"id": "1", "tasks": [{"id": "TASK-01", "status": "CONVERGED", "conv": 1, "threshold": 1}]},
                {"id": "2", "tasks": []},
            ],
            "issues": [],
            "control": {},
        })

        allowed = run_state_cli(state_path, "set", "current_phase", "2")
        jumped = run_state_cli(state_path, "set", "current_phase", "4")

        assert allowed.returncode == 0
        assert jumped.returncode == 1
        assert "jump forward" in jumped.stderr


def test_task_conv_rejects_duplicate_signature_and_reset_clears_it():
    with tempfile.TemporaryDirectory() as tmpdir:
        state_path = os.path.join(tmpdir, "state.json")
        write_state(state_path, {
            "current_phase": "1",
            "phases": [{
                "id": "1",
                "tasks": [{
                    "id": "TASK-01",
                    "status": "DRAFTED",
                    "conv": 0,
                    "threshold": 2,
                    "last_conv_sig": "",
                }],
            }],
            "issues": [],
            "control": {},
        })

        first = run_state_cli(state_path, "task-conv", "--phase", "1", "--task", "TASK-01", "--incr")
        second = run_state_cli(state_path, "task-conv", "--phase", "1", "--task", "TASK-01", "--incr")
        reset = run_state_cli(state_path, "task-conv", "--phase", "1", "--task", "TASK-01", "--reset")
        third = run_state_cli(state_path, "task-conv", "--phase", "1", "--task", "TASK-01", "--incr")

        assert first.returncode == 0
        assert second.returncode == 1
        assert "cannot increment twice" in second.stderr
        assert reset.returncode == 0
        assert third.returncode == 0


def test_reset_execute_state_defaults_to_all_phases():
    data = {
        "current_phase": "2",
        "phases": [
            {
                "id": "1",
                "consecutive_pass": 3,
                "total_validations": 4,
                "last_result": "PASS",
                "tasks": [{"id": "TASK-01", "status": "CONVERGED", "conv": 2, "threshold": 1, "last_round": 5, "last_conv_sig": "abc"}],
            },
            {
                "id": "2",
                "consecutive_pass": 1,
                "total_validations": 2,
                "last_result": "FAIL",
                "tasks": [{"id": "TASK-02", "status": "DRAFTED", "conv": 1, "threshold": 1, "last_round": 6, "last_conv_sig": "def"}],
            },
        ],
        "control": {"human_required": True, "stuck_level": 2, "stop_condition_met": True},
    }

    reset_execute_state_data(data)

    assert data["current_phase"] == "1"
    assert data["control"]["human_required"] is False
    assert data["control"]["stuck_level"] == 0
    assert data["control"]["stop_condition_met"] is False
    for phase in data["phases"]:
        assert phase["consecutive_pass"] == 0
        assert phase["total_validations"] == 0
        for task in phase["tasks"]:
            assert task["status"] == "TODO"
            assert task["conv"] == 0
            assert task["last_round"] is None
            assert task["last_conv_sig"] == ""


def test_reset_execute_state_can_start_at_phase():
    data = {
        "current_phase": "3",
        "phases": [
            {"id": "1", "consecutive_pass": 5, "tasks": [{"id": "TASK-01", "status": "CONVERGED", "conv": 5}]},
            {"id": "2", "consecutive_pass": 2, "tasks": [{"id": "TASK-02", "status": "CONVERGED", "conv": 3}]},
            {"id": "3", "consecutive_pass": 1, "tasks": [{"id": "TASK-03", "status": "DRAFTED", "conv": 1}]},
        ],
        "control": {},
    }

    reset_execute_state_data(data, phase="2")

    assert data["current_phase"] == "2"
    assert data["phases"][0]["consecutive_pass"] == 5
    assert data["phases"][0]["tasks"][0]["status"] == "CONVERGED"
    assert data["phases"][1]["consecutive_pass"] == 0
    assert data["phases"][1]["tasks"][0]["status"] == "TODO"
    assert data["phases"][2]["tasks"][0]["status"] == "TODO"


def test_reset_execute_state_can_start_at_task():
    data = {
        "current_phase": "1",
        "phases": [{
            "id": "1",
            "consecutive_pass": 4,
            "tasks": [
                {"id": "TASK-01", "order": 1, "status": "CONVERGED", "conv": 5},
                {"id": "TASK-02", "order": 2, "status": "CONVERGED", "conv": 5},
                {"id": "TASK-03", "order": 3, "status": "DRAFTED", "conv": 1},
            ],
        }],
        "control": {},
    }

    reset_execute_state_data(data, phase="1", task="TASK-02")

    assert data["current_phase"] == "1"
    assert data["phases"][0]["consecutive_pass"] == 0
    assert data["phases"][0]["tasks"][0]["status"] == "CONVERGED"
    assert data["phases"][0]["tasks"][0]["conv"] == 5
    assert data["phases"][0]["tasks"][1]["status"] == "TODO"
    assert data["phases"][0]["tasks"][2]["status"] == "TODO"


def test_guarded_write_appends_state_event():
    with tempfile.TemporaryDirectory() as tmpdir:
        state_path = os.path.join(tmpdir, "state.json")
        write_state(state_path, {
            "current_phase": "1",
            "phases": [{"id": "1", "tasks": []}],
            "issues": [],
            "control": {},
        })

        result = guarded_state_write(
            state_path,
            lambda data: data.setdefault("control", {}).__setitem__("human_required", True),
            source="agent_cli",
            run_id="run-evt",
        )

        events_path = os.path.join(tmpdir, "state_events.jsonl")
        with open(events_path, "r", encoding="utf-8") as f:
            records = [json.loads(line) for line in f if line.strip()]

        assert result["ok"] is True
        assert records[-1]["run_id"] == "run-evt"
        assert "control.human_required" in records[-1]["changed_keys"]


def test_dry_run_validates_without_bumping_revision():
    with tempfile.TemporaryDirectory() as tmpdir:
        state_path = os.path.join(tmpdir, "state.json")
        write_state(state_path, {
            "current_phase": "1",
            "phases": [{"id": "1", "tasks": []}],
            "issues": [],
            "control": {},
            "state_revision": 3,
        })

        result = run_state_cli(state_path, "set", "human_required", "true", "--dry-run")

        assert result.returncode == 0
        assert "DRY-RUN OK" in result.stdout
        assert get_val(state_path, "state_revision") == "3"


def test_task_progress_quota_falls_back_to_per_run_id_without_round():
    # No --round supplied (e.g. manual CLI usage): falls back to the coarser
    # run_id-only quota, same as before round-scoping was added.
    with tempfile.TemporaryDirectory() as tmpdir:
        state_path = os.path.join(tmpdir, "state.json")
        write_state(state_path, {
            "current_phase": "1",
            "phases": [{
                "id": "1",
                "tasks": [
                    {"id": "TASK-01", "status": "TODO", "conv": 0, "threshold": 1},
                    {"id": "TASK-02", "status": "TODO", "conv": 0, "threshold": 1},
                ],
            }],
            "issues": [],
            "control": {},
        })

        first = run_state_cli(state_path, "--run-id", "same-run", "task-status", "--phase", "1", "--task", "TASK-01", "--to", "DRAFTED")
        second = run_state_cli(state_path, "--run-id", "same-run", "task-status", "--phase", "1", "--task", "TASK-02", "--to", "DRAFTED")
        third = run_state_cli(state_path, "--run-id", "new-run", "task-status", "--phase", "1", "--task", "TASK-02", "--to", "DRAFTED")

        assert first.returncode == 0
        assert second.returncode == 1
        assert "already advanced one task" in second.stderr
        assert third.returncode == 0


def test_task_progress_quota_is_one_per_round_not_per_entire_run():
    # A "run" (one loop.py invocation, identified by run_id) can span many
    # rounds. The quota must reset every round (run_id+round), not block all
    # task progression for the rest of the run after the first one.
    with tempfile.TemporaryDirectory() as tmpdir:
        state_path = os.path.join(tmpdir, "state.json")
        write_state(state_path, {
            "current_phase": "1",
            "phases": [{
                "id": "1",
                "tasks": [
                    {"id": "TASK-01", "status": "TODO", "conv": 0, "threshold": 1},
                    {"id": "TASK-02", "status": "TODO", "conv": 0, "threshold": 1},
                ],
            }],
            "issues": [],
            "control": {},
        })

        round1 = run_state_cli(
            state_path, "--run-id", "same-run", "--round", "1",
            "task-status", "--phase", "1", "--task", "TASK-01", "--to", "DRAFTED",
        )
        blocked_same_round = run_state_cli(
            state_path, "--run-id", "same-run", "--round", "1",
            "task-status", "--phase", "1", "--task", "TASK-02", "--to", "DRAFTED",
        )
        next_round = run_state_cli(
            state_path, "--run-id", "same-run", "--round", "2",
            "task-status", "--phase", "1", "--task", "TASK-02", "--to", "DRAFTED",
        )

        assert round1.returncode == 0
        assert blocked_same_round.returncode == 1
        assert "already advanced one task" in blocked_same_round.stderr
        assert next_round.returncode == 0


def test_cli_run_id_equals_form_does_not_swallow_subcommand():
    # config.fmt_prompt renders state_cli with `--run-id=` / `--round=` (equals
    # form) precisely so an empty value never consumes the next token (the
    # agent's subcommand) as this flag's argument.
    with tempfile.TemporaryDirectory() as tmpdir:
        state_path = os.path.join(tmpdir, "state.json")
        write_state(state_path, {
            "current_phase": "1",
            "phases": [{"id": "1", "tasks": []}],
            "issues": [],
            "control": {},
        })

        cmd = [
            sys.executable, str(STATE_PY), "--state", state_path,
            "--run-id=", "--round=", "set", "current_phase", "1",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)

        assert result.returncode == 0
        assert "OK current_phase=1" in result.stdout


def test_invariants_scoped_to_changed_entities_not_legacy_data():
    # Pre-existing legacy values that predate the current enum/threshold rules
    # must not block writes that don't touch them.
    with tempfile.TemporaryDirectory() as tmpdir:
        state_path = os.path.join(tmpdir, "state.json")
        write_state(state_path, {
            "current_phase": "1",
            "phases": [{
                "id": "1",
                "tasks": [{"id": "TASK-01", "status": "DRAFTED", "conv": 7, "threshold": 5}],
            }],
            "issues": [{"id": "ISSUE-01", "level": "INFO", "status": "WONTFIX"}],
            "control": {},
        })

        result = run_state_cli(state_path, "set", "last_round_mode", "推進")

        assert result.returncode == 0


def test_corrupt_state_file_fails_closed():
    with tempfile.TemporaryDirectory() as tmpdir:
        state_path = os.path.join(tmpdir, "state.json")
        with open(state_path, "w", encoding="utf-8") as f:
            f.write("{bad json")

        result = run_state_cli(state_path, "get", "current_phase")

        assert result.returncode == 1
        assert "corrupt" in result.stderr


def test_guarded_state_write_rejects_duplicate_task_ids():
    with tempfile.TemporaryDirectory() as tmpdir:
        state_path = os.path.join(tmpdir, "state.json")
        write_state(state_path, {
            "current_phase": "1",
            "phases": [{"id": "1", "tasks": [{"id": "TASK-01", "status": "TODO", "conv": 0, "threshold": 1}]}],
            "issues": [],
            "control": {},
        })

        try:
            guarded_state_write(
                state_path,
                lambda data: data["phases"][0]["tasks"].append({"id": "TASK-01", "status": "TODO", "conv": 0, "threshold": 1}),
                source="agent_cli",
            )
            assert False, "expected duplicate task invariant failure"
        except ValueError as e:
            assert "duplicate task id" in str(e)


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
