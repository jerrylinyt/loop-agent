import os
import re
import json
import logging
import subprocess
from collections import deque
from datetime import datetime

logger = logging.getLogger(__name__)


class StateFileCorruptError(RuntimeError):
    pass

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
        raise StateFileCorruptError(f"state file is corrupt: {state_json_path}") from e


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
    "state_revision", "last_writer_run_id", "last_writer_source", "last_writer_ts",
    "current_phase", "plan_version", "framework_ref", "last_round_mode", "last_round_result",
    "last_round_fail_tasks", "rounds_since_progress", "stuck_level", "current_model_tier",
    "enhanced_rounds_used", "human_required", "human_required_code", "human_required_reason",
    "human_required_msg", "human_required_since", "suggested_human_action",
    "human_required_source", "human_required_run_id",
    "review_invalid_streak", "last_safe_sha", "stop_condition_met", "blocking_issues",
    "last_task_progress_run_id", "last_conv_progress_run_id",
    "tree_enabled", "tree_root", "tree_total_nodes", "tree_total_leaves", "tree_max_depth",
    "plan_human_required", "plan_human_required_code", "plan_human_required_reason",
    "plan_human_required_msg", "plan_human_required_since", "plan_suggested_human_action",
    "plan_human_required_source", "plan_human_required_run_id"
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
    root_keys = {
        "schema_version", "mode", "current_phase", "plan_version", "framework_ref",
        "state_revision"
    }
    if key in root_keys:
        val = data.get(key)
        return str(val) if val is not None else None

    if key == "last_writer_run_id":
        val = data.get("last_writer", {}).get("run_id")
        return str(val) if val is not None else ""
    if key == "last_writer_source":
        val = data.get("last_writer", {}).get("source")
        return str(val) if val is not None else ""
    if key == "last_writer_ts":
        val = data.get("last_writer", {}).get("ts")
        return str(val) if val is not None else ""

    # tree mode keys removed

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
        "enhanced_rounds_used", "human_required", "human_required_code",
        "human_required_reason", "human_required_msg", "human_required_since",
        "suggested_human_action", "human_required_source", "human_required_run_id",
        "review_invalid_streak", "last_safe_sha", "last_task_progress_run_id",
        "last_conv_progress_run_id",
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
    if key in {"schema_version", "mode", "current_phase", "plan_version", "framework_ref", "state_revision"}:
        if key in ("schema_version", "plan_version"):
            data[key] = to_int(value)
        elif key == "state_revision":
            data[key] = to_int(value)
        else:
            data[key] = value
        return

    if key in {"last_writer_run_id", "last_writer_source", "last_writer_ts"}:
        if "last_writer" not in data or not isinstance(data["last_writer"], dict):
            data["last_writer"] = {}
        field = key.replace("last_writer_", "")
        data["last_writer"][field] = value
        return

    # tree mode setters removed

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
        "enhanced_rounds_used", "human_required", "human_required_code",
        "human_required_reason", "human_required_msg", "human_required_since",
        "suggested_human_action", "human_required_source", "human_required_run_id",
        "review_invalid_streak", "last_safe_sha", "last_task_progress_run_id",
        "last_conv_progress_run_id",
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


def _state_revision(data: dict) -> int:
    try:
        return int(data.get("state_revision") or 0)
    except (TypeError, ValueError):
        return 0


def _stamp_last_writer(data: dict, source: str, run_id: str | None):
    data["schema_version"] = max(as_int(data.get("schema_version"), 1), 2)
    data["state_revision"] = _state_revision(data) + 1
    data["last_writer"] = {
        "run_id": run_id or "",
        "source": source,
        "ts": datetime.now().strftime("%F %T"),
    }


def _validate_guarded_transition(before: dict, after: dict, source: str):
    before_control = before.get("control", {}) if isinstance(before.get("control"), dict) else {}
    after_control = after.get("control", {}) if isinstance(after.get("control"), dict) else {}
    before_plan = before.get("plan", {}) if isinstance(before.get("plan"), dict) else {}
    after_plan = after.get("plan", {}) if isinstance(after.get("plan"), dict) else {}

    before_human = bool(before_control.get("human_required", False))
    after_human = bool(after_control.get("human_required", False))
    if before_human and not after_human and source not in {"dashboard_resume", "dashboard_clear_human_required", "resume"}:
        raise ValueError("human_required can only be cleared by an explicit resume action")

    before_plan_human = bool(before_plan.get("human_required", False))
    after_plan_human = bool(after_plan.get("human_required", False))
    if before_plan_human and not after_plan_human and source not in {"dashboard_resume", "dashboard_clear_human_required", "resume"}:
        raise ValueError("plan_human_required can only be cleared by an explicit resume action")

    before_phase = as_int(before.get("current_phase"), 0)
    after_phase = as_int(after.get("current_phase"), 0)
    if after_phase < before_phase and source not in {"reset_plan", "dashboard_reset_plan"}:
        raise ValueError("current_phase cannot move backward without a reset path")
    if source not in {"reset_plan", "dashboard_reset_plan"}:
        if after_phase > before_phase + 1:
            raise ValueError("current_phase cannot jump forward multiple phases at once")
        if after_phase == before_phase + 1 and before_phase > 0:
            if not _is_phase_converged(after, str(before_phase)) or _blocking_issue_count(after) != 0:
                raise ValueError(
                    f"phase {before_phase}->{after_phase} blocked: previous phase is not fully CONVERGED or has blocking issues"
                )


def _blocking_issue_count(data: dict) -> int:
    issues = data.get("issues", [])
    return len([i for i in issues if i.get("status") == "OPEN" and i.get("level") == "BLOCKING"])


def _find_phase(data: dict, phase_id: str):
    for ph in data.get("phases", []):
        if str(ph.get("id")) == str(phase_id):
            return ph
    return None


def _find_task(data: dict, phase_id: str, task_id: str):
    phase = _find_phase(data, phase_id)
    if not phase:
        return None
    for task in phase.get("tasks", []):
        if task.get("id") == task_id:
            return task
    return None


def _is_phase_converged(data: dict, phase_id: str) -> bool:
    target_ph = _find_phase(data, phase_id)
    if not target_ph:
        return False
    tasks = target_ph.get("tasks", [])
    if not tasks:
        return False
    return all(t.get("status") == "CONVERGED" for t in tasks)


def _check_invariants(data: dict, changed_keys: list[str] | None = None) -> list[str]:
    """Validate structural integrity of `data`.

    Duplicate/missing-id checks are always enforced (cheap, and the CLI already
    prevents duplicates on add, so legacy data should never trip them).
    Value-level checks (threshold/level/status) and the current_phase-existence
    check are scoped to entities this write actually touched (`changed_keys`),
    so a pre-existing legacy record elsewhere in the file (e.g. an issue with a
    status value that predates this schema) does not block unrelated writes.
    """
    errors = []
    changed = set(changed_keys) if changed_keys is not None else None
    changed_task_refs = set()
    changed_issue_ids = set()
    if changed is not None:
        for key in changed:
            parts = key.split(".")
            if len(parts) >= 4 and parts[0] == "phases" and parts[2] == "tasks":
                changed_task_refs.add((parts[1], parts[3]))
            elif len(parts) >= 2 and parts[0] == "issues":
                changed_issue_ids.add(parts[1])

    phase_ids = set()
    phases = data.get("phases", [])
    current_phase = str(data.get("current_phase") or "")

    for ph in phases:
        pid = str(ph.get("id") or "")
        if not pid:
            errors.append("phase missing id")
            continue
        phase_ids.add(pid)
        seen_tasks = set()
        for task in ph.get("tasks", []):
            task_id = str(task.get("id") or "")
            if not task_id:
                errors.append(f"phase {pid} has task without id")
                continue
            if task_id in seen_tasks:
                errors.append(f"duplicate task id in phase {pid}: {task_id}")
            seen_tasks.add(task_id)

            if changed is not None and (pid, task_id) not in changed_task_refs:
                continue
            conv = as_int(task.get("conv"), -1)
            threshold = as_int(task.get("threshold"), 0)
            if conv < 0:
                errors.append(f"task {task_id} has negative conv")
            if threshold < 1:
                errors.append(f"task {task_id} has invalid threshold")

    if phases and current_phase and (changed is None or "current_phase" in changed):
        if current_phase not in phase_ids:
            errors.append(f"current_phase {current_phase} does not exist in phases")

    seen_issue_ids = set()
    for issue in data.get("issues", []):
        issue_id = str(issue.get("id") or "")
        if not issue_id:
            errors.append("issue missing id")
            continue
        if issue_id in seen_issue_ids:
            errors.append(f"duplicate issue id: {issue_id}")
        seen_issue_ids.add(issue_id)

        if changed is not None and issue_id not in changed_issue_ids:
            continue
        if issue.get("level") not in {"BLOCKING", "NON_BLOCKING"}:
            errors.append(f"issue {issue_id} has invalid level")
        if issue.get("status") not in {"OPEN", "RESOLVED"}:
            errors.append(f"issue {issue_id} has invalid status")

    return errors


def _state_events_path(state_json_path: str) -> str:
    return os.path.join(os.path.dirname(state_json_path) or ".", "state_events.jsonl")


def append_state_event(state_json_path: str, record: dict) -> None:
    p = _state_events_path(state_json_path)
    try:
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        line = json.dumps(record, ensure_ascii=False) + "\n"
        with open(p, "a", encoding="utf-8") as f:
            f.write(line)
    except (OSError, TypeError, ValueError) as e:
        logger.warning(f"Failed to append state event: {e}")


def _summarize_state(data: dict) -> dict:
    current_phase = str(data.get("current_phase") or "")
    control = data.get("control", {}) if isinstance(data.get("control"), dict) else {}
    return {
        "current_phase": current_phase,
        "state_revision": _state_revision(data),
        "human_required": bool(control.get("human_required", False)),
        "blocking_issues": _blocking_issue_count(data),
        "phase_task_statuses": {
            str(ph.get("id")): {
                str(task.get("id")): {
                    "status": task.get("status"),
                    "conv": as_int(task.get("conv"), 0),
                }
                for task in ph.get("tasks", [])
            }
            for ph in data.get("phases", [])
        },
    }


def _changed_keys(before: dict, after: dict) -> list[str]:
    changed = []
    if str(before.get("current_phase")) != str(after.get("current_phase")):
        changed.append("current_phase")

    before_control = before.get("control", {}) if isinstance(before.get("control"), dict) else {}
    after_control = after.get("control", {}) if isinstance(after.get("control"), dict) else {}
    for key in sorted(set(before_control) | set(after_control)):
        if before_control.get(key) != after_control.get(key):
            changed.append(f"control.{key}")

    before_plan = before.get("plan", {}) if isinstance(before.get("plan"), dict) else {}
    after_plan = after.get("plan", {}) if isinstance(after.get("plan"), dict) else {}
    for key in sorted(set(before_plan) | set(after_plan)):
        if before_plan.get(key) != after_plan.get(key):
            changed.append(f"plan.{key}")

    before_phase_map = {
        str(ph.get("id")): {
            str(task.get("id")): (task.get("status"), as_int(task.get("conv"), 0))
            for task in ph.get("tasks", [])
        }
        for ph in before.get("phases", [])
    }
    after_phase_map = {
        str(ph.get("id")): {
            str(task.get("id")): (task.get("status"), as_int(task.get("conv"), 0))
            for task in ph.get("tasks", [])
        }
        for ph in after.get("phases", [])
    }
    for phase_id in sorted(set(before_phase_map) | set(after_phase_map)):
        before_tasks = before_phase_map.get(phase_id, {})
        after_tasks = after_phase_map.get(phase_id, {})
        for task_id in sorted(set(before_tasks) | set(after_tasks)):
            if before_tasks.get(task_id) != after_tasks.get(task_id):
                changed.append(f"phases.{phase_id}.tasks.{task_id}")

    before_issues = {
        str(issue.get("id")): (issue.get("status"), issue.get("level"))
        for issue in before.get("issues", [])
    }
    after_issues = {
        str(issue.get("id")): (issue.get("status"), issue.get("level"))
        for issue in after.get("issues", [])
    }
    for issue_id in sorted(set(before_issues) | set(after_issues)):
        if before_issues.get(issue_id) != after_issues.get(issue_id):
            changed.append(f"issues.{issue_id}")

    return changed


def _record_task_progress_quota(
    data: dict, old_status: str, new_status: str, run_id: str | None, round_no: str | None = None
) -> None:
    if (old_status, new_status) not in {("TODO", "DRAFTED"), ("DRAFTED", "CONVERGED")}:
        return
    # quota is scoped per-round (run_id+round_no). A "run" can span many rounds
    # (loop.py loops up to max_rounds), so keying on run_id alone would allow only
    # one task progression for the *entire* run instead of one per round.
    if run_id and round_no:
        quota_key = f"{run_id}#{round_no}"
    elif run_id:
        quota_key = run_id
    else:
        logger.warning("task progress quota skipped because run_id is empty")
        return
    control = data.setdefault("control", {})
    last_quota_key = str(control.get("last_task_progress_run_id") or "")
    if last_quota_key == quota_key:
        raise ValueError("this run has already advanced one task; finish the round before progressing another task")
    control["last_task_progress_run_id"] = quota_key


def _cli_progress_signature(data: dict) -> str:
    from git_utils import git_head

    return f"{data.get('current_phase') or ''}|{git_head()}"


def _record_conv_progress_quota(data: dict, run_id: str | None, round_no: str | None = None) -> None:
    if run_id and round_no:
        quota_key = f"{run_id}#{round_no}"
    elif run_id:
        quota_key = run_id
    else:
        logger.warning("conv progress quota skipped because run_id is empty")
        return
    control = data.setdefault("control", {})
    last_quota_key = str(control.get("last_conv_progress_run_id") or "")
    if last_quota_key == quota_key:
        raise ValueError("this run has already incremented conv once; finish the round before incrementing again")
    control["last_conv_progress_run_id"] = quota_key


def guarded_state_write(
    control: str,
    mutate,
    *,
    source: str,
    run_id: str | None = None,
    expected_revision: int | None = None,
    dry_run: bool = False,
):
    state_json = _state_json_path(control)
    data = load_state_json(state_json)
    if not isinstance(data, dict):
        data = {}

    before = json.loads(json.dumps(data))
    current_revision = _state_revision(data)
    if expected_revision is not None and current_revision != expected_revision:
        return {
            "ok": False,
            "conflict": True,
            "current_revision": current_revision,
            "last_writer": data.get("last_writer") or {},
        }

    mutate(data)
    _validate_guarded_transition(before, data, source)
    changed_keys = _changed_keys(before, data)
    invariant_errors = _check_invariants(data, changed_keys)
    if invariant_errors:
        raise ValueError("invariant violated: " + "; ".join(invariant_errors))
    if dry_run:
        return {
            "ok": True,
            "conflict": False,
            "dry_run": True,
            "changed_keys": changed_keys,
            "current_revision": current_revision,
            "last_writer": data.get("last_writer") or {},
        }
    _stamp_last_writer(data, source, run_id)
    save_state_json(state_json, data)
    append_state_event(state_json, {
        "ts": datetime.now().strftime("%F %T"),
        "run_id": run_id or "",
        "source": source,
        "revision": data.get("state_revision"),
        "changed_keys": changed_keys,
        "before_summary": _summarize_state(before),
        "after_summary": _summarize_state(data),
    })
    render_all(state_json)
    return {
        "ok": True,
        "conflict": False,
        "current_revision": data.get("state_revision"),
        "last_writer": data.get("last_writer") or {},
        "changed_keys": changed_keys,
    }


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
                        
                        result = record.get("result") or ""
                        is_objective_fail = (not record.get("killed")) and (result == "FAIL")
                        if is_objective_fail:
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


def append_run_finished(
    cfg: dict,
    *,
    final_status: str,
    exit_code: int,
    stage: str,
    human_required_code: str = "",
):
    append_round_record(cfg, {
        "type": "run_finished",
        "ts": datetime.now().strftime("%F %T"),
        "run_id": cfg.get("run_id"),
        "workspace": cfg.get("_workspace") or "default",
        "mode": (cfg.get("generation") or {}).get("mode", "gated"),
        "stage": stage,
        "ended_at": datetime.now().strftime("%F %T"),
        "exit_code": exit_code,
        "final_status": final_status,
        "human_required_code": human_required_code,
    })


def append_round_artifact(
    cfg: dict,
    *,
    round_no: int,
    loop_type: str,
    phase: str,
    changed_files: list[str],
    git_head_before: str,
    git_head_after: str,
    validation_summary: str,
    validation_status: str,
    evidence_files: list[str] | None = None,
    leaf: str | None = None,
):
    append_round_record(cfg, {
        "type": "round_artifact",
        "ts": datetime.now().strftime("%F %T"),
        "run_id": cfg.get("run_id"),
        "round": round_no,
        "loop_type": loop_type,
        "phase": phase,
        "leaf": leaf,
        "changed_files": changed_files,
        "git_head_before": git_head_before,
        "git_head_after": git_head_after,
        "commit": git_head_after,
        "validation_summary": validation_summary,
        "validation_status": validation_status,
        "evidence_files": evidence_files or [],
    })


def check_stop_requested(cfg: dict, log_both=None) -> bool:
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


def set_human_required(
    control: str,
    required: bool,
    reason: str = "",
    msg: str = "",
    *,
    run_id: str | None = None,
    source: str = "execute_loop",
    suggested_action: str = "",
    expected_revision: int | None = None,
):
    def mutate(data: dict):
        control_data = data.setdefault("control", {})
        control_data["human_required"] = required
        if required:
            control_data["human_required_code"] = reason
            control_data["human_required_reason"] = msg
            control_data["human_required_msg"] = msg
            control_data["human_required_since"] = datetime.now().strftime("%F %T")
            control_data["suggested_human_action"] = suggested_action
            control_data["human_required_source"] = source
            control_data["human_required_run_id"] = run_id or ""
        else:
            control_data["human_required"] = False
            control_data["human_required_code"] = ""
            control_data["human_required_reason"] = ""
            control_data["human_required_msg"] = ""
            control_data["human_required_since"] = ""
            control_data["suggested_human_action"] = ""
            control_data["human_required_source"] = ""
            control_data["human_required_run_id"] = ""

    return guarded_state_write(
        control,
        mutate,
        source=source,
        run_id=run_id,
        expected_revision=expected_revision,
    )


def set_plan_human_required(
    control: str,
    required: bool,
    reason: str = "",
    msg: str = "",
    *,
    run_id: str | None = None,
    source: str = "plan_loop",
    suggested_action: str = "",
    expected_revision: int | None = None,
):
    def mutate(data: dict):
        plan_data = data.setdefault("plan", {})
        plan_data["human_required"] = required
        if required:
            plan_data["human_required_code"] = reason
            plan_data["human_required_reason"] = msg
            plan_data["human_required_msg"] = msg
            plan_data["human_required_since"] = datetime.now().strftime("%F %T")
            plan_data["suggested_human_action"] = suggested_action
            plan_data["human_required_source"] = source
            plan_data["human_required_run_id"] = run_id or ""
        else:
            plan_data["human_required"] = False
            plan_data["human_required_code"] = ""
            plan_data["human_required_reason"] = ""
            plan_data["human_required_msg"] = ""
            plan_data["human_required_since"] = ""
            plan_data["suggested_human_action"] = ""
            plan_data["human_required_source"] = ""
            plan_data["human_required_run_id"] = ""

    return guarded_state_write(
        control,
        mutate,
        source=source,
        run_id=run_id,
        expected_revision=expected_revision,
    )


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
        "plan": {},
        "stop_condition": {
            "final_phase_pass_gte": 10,
            "blocking_eq": 0,
        },
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

    def load_state_or_exit(path: str):
        try:
            return load_state_json(path)
        except StateFileCorruptError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    def run_guarded_write(mutate, success_message: str, *, dry_run: bool = False):
        try:
            result = guarded_state_write(
                state_path,
                mutate,
                source="agent_cli",
                run_id=args.run_id,
                dry_run=dry_run,
            )
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        except StateFileCorruptError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

        if not result.get("ok"):
            print("Error: state write conflict.", file=sys.stderr)
            sys.exit(1)

        if result.get("dry_run"):
            changes = ", ".join(result.get("changed_keys") or []) or "no changes"
            print(f"DRY-RUN OK: {changes}")
        else:
            print(success_message)
        sys.exit(0)

    def legal_task_targets(old_status: str) -> tuple[str, ...]:
        transitions = {
            "TODO": ("TODO", "DRAFTED", "FROZEN"),
            "DRAFTED": ("DRAFTED", "CONVERGED", "NEEDS_REVISION", "FROZEN"),
            "NEEDS_REVISION": ("NEEDS_REVISION", "DRAFTED", "FROZEN"),
            "FROZEN": ("FROZEN", "TODO", "DRAFTED", "NEEDS_REVISION"),
            "CONVERGED": ("CONVERGED", "NEEDS_REVISION", "FROZEN"),
        }
        return transitions.get(old_status, (old_status,))

    parser = argparse.ArgumentParser(description="Loop Engineering State CLI Tool")
    parser.add_argument("--control", help="Path to control file")
    parser.add_argument("--state", help="Path to state file")
    parser.add_argument("--run-id", default=os.environ.get("LOOP_RUN_ID", ""))
    parser.add_argument("--round", default=os.environ.get("LOOP_ROUND_NO", ""))
    subparsers = parser.add_subparsers(dest="cmd", required=True)
    
    # get
    get_p = subparsers.add_parser("get")
    get_p.add_argument("key")
    
    # set
    set_p = subparsers.add_parser("set")
    set_p.add_argument("key")
    set_p.add_argument("value")
    set_p.add_argument("--dry-run", action="store_true")
    
    # incr
    incr_p = subparsers.add_parser("incr")
    incr_p.add_argument("key")
    incr_p.add_argument("--by", type=int, default=1)
    incr_p.add_argument("--dry-run", action="store_true")
    
    # task-status
    ts_p = subparsers.add_parser("task-status")
    ts_p.add_argument("--phase", required=True)
    ts_p.add_argument("--task", required=True)
    ts_p.add_argument("--to", required=True, choices=["TODO", "DRAFTED", "CONVERGED", "NEEDS_REVISION", "FROZEN"])
    ts_p.add_argument("--dry-run", action="store_true")
    
    # task-conv
    tc_p = subparsers.add_parser("task-conv")
    tc_p.add_argument("--phase", required=True)
    tc_p.add_argument("--task", required=True)
    tc_group = tc_p.add_mutually_exclusive_group(required=True)
    tc_group.add_argument("--incr", action="store_true")
    tc_group.add_argument("--reset", action="store_true")
    tc_p.add_argument("--dry-run", action="store_true")
    
    # task-add
    ta_p = subparsers.add_parser("task-add")
    ta_p.add_argument("--phase", required=True)
    ta_p.add_argument("--id", required=True)
    ta_p.add_argument("--order", type=int, required=True)
    ta_p.add_argument("--threshold", type=int, default=5)
    ta_p.add_argument("--depends", default="")
    ta_p.add_argument("--output", default="")
    ta_p.add_argument("--spec", default="")
    ta_p.add_argument("--dry-run", action="store_true")
    
    # issue-add
    ia_p = subparsers.add_parser("issue-add")
    ia_p.add_argument("--id", required=True)
    ia_p.add_argument("--level", required=True, choices=["BLOCKING", "NON_BLOCKING"])
    ia_p.add_argument("--task", default="")
    ia_p.add_argument("--phase", default="")
    ia_p.add_argument("--title", required=True)
    ia_p.add_argument("--dry-run", action="store_true")
    
    # issue-set-status
    is_p = subparsers.add_parser("issue-set-status")
    is_p.add_argument("--id", required=True)
    is_p.add_argument("--to", required=True, choices=["OPEN", "RESOLVED"])
    is_p.add_argument("--dry-run", action="store_true")
    
    # node subcommand parser definitions removed
    
    # render-control
    rc_p = subparsers.add_parser("render-control")
    rc_p.add_argument("--out", required=True)
    
    # derive
    dv_p = subparsers.add_parser("derive")
    dv_p.add_argument("expr")
    
    # migrate
    mg_p = subparsers.add_parser("migrate")
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
        if not getattr(args, "control", None):
            print("Error: --control is required for migrate command.", file=sys.stderr)
            sys.exit(1)
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

        data = load_state_or_exit(state_path)
        
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
            def mutate(data: dict):
                set_val_in_json_data(data, args.key, args.value)
            run_guarded_write(mutate, f"OK {args.key}={args.value}", dry_run=args.dry_run)
            
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
            def mutate(data: dict):
                set_val_in_json_data(data, args.key, str(new_val))
            run_guarded_write(mutate, f"OK {args.key}={new_val}", dry_run=args.dry_run)
            
    elif args.cmd in ("task-status", "task-conv", "task-add"):
        data = load_state_or_exit(state_path)
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
            def mutate(data: dict):
                target_phase = _find_phase(data, args.phase)
                if not target_phase:
                    target_phase = {"id": args.phase, "name": f"Phase {args.phase}", "tasks": [], "coverage": []}
                    data.setdefault("phases", []).append(target_phase)
                for task in target_phase["tasks"]:
                    if task.get("id") == args.id:
                        raise ValueError(f"Task '{args.id}' already exists in phase '{args.phase}'.")
                target_phase["tasks"].append({
                    "id": args.id,
                    "order": args.order,
                    "spec_ref": args.spec,
                    "status": "TODO",
                    "conv": 0,
                    "threshold": args.threshold,
                    "depends_on": depends,
                    "verify_method": "re_derive",
                    "output": args.output,
                    "last_round": None,
                    "last_conv_sig": "",
                })
            run_guarded_write(mutate, f"OK task-add {args.id}", dry_run=args.dry_run)
            
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
                legal_targets = ", ".join(t for t in legal_task_targets(old_status) if t != old_status)
                print(
                    f"Error: illegal transition {old_status}->{new_status}. {old_status} can move to: {legal_targets}.",
                    file=sys.stderr,
                )
                sys.exit(1)

            if new_status == "CONVERGED":
                # 加驗 conv 是否達 threshold
                if target_task.get("conv", 0) < target_task.get("threshold", 5):
                    print(f"Error: Task conv {target_task.get('conv')} < threshold {target_task.get('threshold')}.", file=sys.stderr)
                    sys.exit(1)

            def mutate(data: dict):
                live_task = _find_task(data, args.phase, args.task)
                if not live_task:
                    raise ValueError(f"Task '{args.task}' not found in phase '{args.phase}'.")
                live_old_status = live_task.get("status", "TODO")
                if new_status == "CONVERGED" and live_task.get("conv", 0) < live_task.get("threshold", 5):
                    raise ValueError(
                        f"Task conv {live_task.get('conv')} < threshold {live_task.get('threshold')}."
                    )
                _record_task_progress_quota(data, live_old_status, new_status, args.run_id, args.round)
                live_task["status"] = new_status

            run_guarded_write(mutate, f"OK task-status {args.task} to {new_status}", dry_run=args.dry_run)
            
        elif args.cmd == "task-conv":
            def mutate(data: dict):
                live_task = _find_task(data, args.phase, args.task)
                if not live_task:
                    raise ValueError(f"Task '{args.task}' not found in phase '{args.phase}'.")
                if args.incr:
                    sig = _cli_progress_signature(data)
                    if sig == (live_task.get("last_conv_sig") or ""):
                        raise ValueError(
                            "conv unchanged: the same progress signature cannot increment twice without real progress"
                        )
                    _record_conv_progress_quota(data, args.run_id, args.round)
                    live_task["conv"] = as_int(live_task.get("conv"), 0) + 1
                    live_task["last_conv_sig"] = sig
                elif args.reset:
                    live_task["conv"] = 0
                    live_task["last_conv_sig"] = ""

            next_conv = (as_int(target_task.get("conv"), 0) + 1) if args.incr else 0
            run_guarded_write(
                mutate,
                f"OK task-conv {args.task} (conv={next_conv})",
                dry_run=args.dry_run,
            )
            
    elif args.cmd in ("issue-add", "issue-set-status"):
        data = load_state_or_exit(state_path)
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
            def mutate(data: dict):
                issues = data.setdefault("issues", [])
                for issue in issues:
                    if issue.get("id") == args.id:
                        raise ValueError(f"Issue '{args.id}' already exists.")
                issues.append({
                    "id": args.id,
                    "level": args.level,
                    "title": args.title,
                    "phase": args.phase,
                    "task": args.task,
                    "status": "OPEN",
                    "round": ""
                })
            run_guarded_write(mutate, f"OK issue-add {args.id}", dry_run=args.dry_run)
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
            def mutate(data: dict):
                issues = data.setdefault("issues", [])
                for issue in issues:
                    if issue.get("id") == args.id:
                        issue["status"] = args.to
                        return
                raise ValueError(f"Issue '{args.id}' not found.")
            run_guarded_write(mutate, f"OK issue-set-status {args.id} to {args.to}", dry_run=args.dry_run)
            
    # node handlers removed
            
    elif args.cmd == "render-control":
        print(f"OK render-control to {args.out} (noop)")
        sys.exit(0)

        
    elif args.cmd == "derive":
        data = load_state_or_exit(state_path)
        expr = args.expr
        
        if expr == "blocking_issues":
            issues = data.get("issues", [])
            blocking = [i for i in issues if i.get("status") == "OPEN" and i.get("level") == "BLOCKING"]
            print(len(blocking))
            sys.exit(0)
            
        elif expr.startswith("phase-converged:"):
            phase_id = expr.split(":", 1)[1]
            print("true" if _is_phase_converged(data, phase_id) else "false")
            sys.exit(0)
            
        elif expr == "is-done":
            # 平模式下的 is-done
            phases = data.get("phases", [])
            if not phases:
                print("false")
                sys.exit(0)
            last_ph = phases[-1]
            last_ph_id = last_ph.get("id")
            
            sc = data.get("stop_condition") or {
                "final_phase_pass_gte": 10,
                "blocking_eq": 0,
            }
            # 取得計數器
            consecutive_pass = last_ph.get("consecutive_pass", 0)
            current_phase = data.get("current_phase", "1")
            
            blocking_count = _blocking_issue_count(data)
            all_conv = _is_phase_converged(data, str(last_ph_id))
            
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
