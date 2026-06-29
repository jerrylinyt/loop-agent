#!/usr/bin/env python3
"""
loop.py — 通用 Loop Engineering 執行引擎（config 驅動、支援 N 階段）。

反覆觸發 coding agent 跑 CONTROL.md，偵測「改A壞B」震盪、自動三層升級模型（預設→增強→人類）。
"""

import os
import json
import sys
import time
import argparse
import subprocess
import shutil
import logging
from datetime import datetime

from config import load_config, fmt_prompt, select_model, model_tier_label
from git_utils import inspect_and_fix_blank, git_guard, expand_control_files, changed_files, git_head
from state import get_val, set_val, as_int, progress_signature, append_round_record, reconstruct_history_and_progress, check_stop_requested, set_human_required
from agent_runner import build_cmd, run_agent
from utils import (
    WorkspaceBusy, acquire_run_lock, release_run_lock, touch_run_lock, lock_stale_seconds,
    add_common_args, resolve_workspace, apply_quiet_flag, rotate_log_if_needed,
    update_index, report_preflight, fail_fingerprint, detect_oscillation, is_done, human_needed,
    sync_framework_docs
)
from tree import (
    tree_enabled, tree_md_path, get_node, set_node_field,
    next_ready_leaf, try_unlock_parent, mark_leaf_needs_revision,
    all_children_converged, list_by_state, format_tree_for_human,
    IN_PROGRESS, CONVERGED, NEEDS_REVISION, FROZEN, LEAF,
)

logger = logging.getLogger(__name__)

try:                          # Windows 主控台 cp950 → 強制 UTF-8 輸出
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass


def has_human_commits(start_sha: str, end_sha: str) -> bool:
    if start_sha == end_sha:
        return False
    try:
        res = subprocess.run(["git", "log", "--format=%s", f"{start_sha}..{end_sha}"], capture_output=True, text=True)
        if res.returncode != 0:
            return False
        for line in res.stdout.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            is_agent = (
                (line.startswith("R") and " | " in line) or
                line.startswith("loop-autocommit:") or
                line.startswith("chore:") or
                line.startswith("Revert") or
                line.startswith("Merge")
            )
            if not is_agent:
                return True
        return False
    except OSError:
        return False


def _load_review_verdict(result_file: str) -> dict | None:
    """Load the Git Review Gate JSON verdict."""
    if not os.path.exists(result_file):
        return None
    try:
        with open(result_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _review_checklist_valid(verdict: dict) -> bool:
    checklist = verdict.get("checklist")
    if not isinstance(checklist, list) or len(checklist) < 6:
        return False
    for item in checklist:
        if not isinstance(item, dict):
            return False
        status = str(item.get("status", "")).upper()
        if status not in ("PASS", "FLAG"):
            return False
        if not str(item.get("item", "")).strip():
            return False
    return True


def run_git_review_gate(cfg: dict, control: str, log_both) -> tuple[bool, bool]:
    """獨立的 Git Review Gate：審查 last_safe_sha 到 HEAD 的 Diff。
    回傳 (通過與否, 是否因人類干預而需停機)。"""
    state_dir = cfg["runtime"]["state_dir"]
    
    # 取得目前的 HEAD
    res = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True)
    if res.returncode != 0:
        return True, False
    current_head = res.stdout.strip()
    
    # 讀取 last_safe_sha
    last_safe_sha = get_val(control, "last_safe_sha") or ""
            
    if not last_safe_sha:
        # 第一次執行，將目前的 HEAD 當作基準
        set_val(control, "last_safe_sha", current_head)
        return True, False
        
    if last_safe_sha == current_head:
        return True, False
        
    res = subprocess.run(["git", "diff", last_safe_sha, current_head], capture_output=True, text=True)
    diff = res.stdout.strip()
    if not diff:
        set_val(control, "last_safe_sha", current_head)
        return True, False
        
    log_both("  🔍 [Git Review Gate] 啟動，審查未驗證的 Commit...")
    prompt_template = cfg.get("agent", {}).get("prompts", {}).get("git_review", "")
    if not prompt_template:
        return True, False
        
    control_contents = []
    for cf in expand_control_files(cfg):
        if os.path.exists(cf):
            try:
                with open(cf, "r", encoding="utf-8", errors="replace") as f:
                    control_contents.append(f"=== {cf} ===\n{f.read()}")
            except OSError:
                pass
    control_str = "\n\n".join(control_contents) if control_contents else "(無狀態檔或無法讀取)"
        
    result_file = os.path.join(state_dir, "git_review_result")
    prompt = prompt_template.replace("{diff_content}", diff)\
                            .replace("{control_contents}", control_str)\
                            .replace("{result_file}", result_file)
                            
    model = cfg.get("agent", {}).get("models", {}).get("review", "")
    if not model:
        model = select_model(cfg, "review", 0)
        
    cmd = build_cmd(cfg, model, prompt)
    
    if os.path.exists(result_file):
        os.remove(result_file)
        
    log_both(f"  [Git Review Prompt]\n{'-'*40}\n{prompt}\n{'-'*40}")
        
    rc, killed = run_agent(cmd, cfg)
    
    verdict = _load_review_verdict(result_file)

    def _read_streak() -> int:
        return as_int(get_val(control, "review_invalid_streak"))

    def _write_streak(n: int):
        set_val(control, "review_invalid_streak", str(n))

    if verdict is None:
        reason = "Git Review Gate did not write valid JSON verdict."
    else:
        decision = str(verdict.get("verdict", "")).upper()
        reason = str(verdict.get("reason", "")).strip()
        if decision in ("REVERT", "FATAL_STATE"):
            _write_streak(0)
            is_fatal = decision == "FATAL_STATE"
            log_both(f"  [Git Review Gate] verdict={decision}: {reason}")

            if is_fatal:
                append_round_record(cfg, {
                    "run_id": cfg.get("run_id"),
                    "ts": datetime.now().strftime("%F %T"),
                    "type": "human_required",
                    "message": f"Git Review Gate fatal state: {reason}"
                })
                return False, True

            if has_human_commits(last_safe_sha, current_head):
                append_round_record(cfg, {
                    "run_id": cfg.get("run_id"),
                    "ts": datetime.now().strftime("%F %T"),
                    "type": "human_required",
                    "message": f"Git Review Gate human conflict: {reason}"
                })
                return False, True

            revert_res = subprocess.run(["git", "revert", "--no-edit", f"{last_safe_sha}..{current_head}"])
            if revert_res.returncode != 0:
                subprocess.run(["git", "revert", "--abort"])
                append_round_record(cfg, {
                    "run_id": cfg.get("run_id"),
                    "ts": datetime.now().strftime("%F %T"),
                    "type": "review_revert",
                    "message": f"Git Revert failed due to merge conflicts: {reason}"
                })
                return False, True

            append_round_record(cfg, {
                "run_id": cfg.get("run_id"),
                "ts": datetime.now().strftime("%F %T"),
                "type": "review_revert",
                "message": f"Git Review Gate reverted changes. Reason: {reason}"
            })
            return False, False

        if decision == "PASS" and _review_checklist_valid(verdict):
            _write_streak(0)
            set_val(control, "last_safe_sha", current_head)
            log_both("  [Git Review Gate] JSON verdict PASS.")
            return True, False

        if decision == "PASS":
            reason = "Git Review Gate PASS verdict missing valid checklist."
        elif not reason:
            reason = f"Git Review Gate invalid verdict: {decision or ''}."

    streak = _read_streak() + 1
    _write_streak(streak)
    limit = cfg.get("oscillation", {}).get("enhanced_max_rounds", 8)
    log_both(f"  [Git Review Gate] Invalid JSON verdict: {reason} (streak={streak})")
    if streak >= limit:
        _write_streak(0)
        append_round_record(cfg, {
            "run_id": cfg.get("run_id"),
            "ts": datetime.now().strftime("%F %T"),
            "type": "human_required",
            "message": f"Git Review Gate failed to produce valid JSON verdict {streak} times consecutively."
        })
        return False, True
    return False, False


def update_stuck_state(cfg: dict, control: str, log_both, *, fail_fingerprints, progress: dict,
                        killed, mode: str, result: str, phase, cur_pass: int,
                        leaf_label: str = "") -> dict:
    """共用的『讀本輪結果 → 判進展/無活動/震盪 → 升降 stuck_level』邏輯。

    平模式（`_run_execute_locked`）與樹模式（`_run_tree_execute_locked`）此段邏輯完全一致，
    過去各自維護一份近乎逐行相同的拷貝；唯一差異是 log 訊息要不要帶葉子標籤
    （`leaf_label`，例如 `"葉子 [xxx] "`；平模式留空字串）。

    回傳 dict（`stuck_level` / `rounds_since` / `enhanced_used` / `no_activity` / `progressed` /
    `hard_stop` / `progress`）供呼叫端組裝 `append_round_record`。`hard_stop=True` 時本函式已在該
    分支內完成 `set_val`/`save_progress` 並提早結束，呼叫端應立即 `return 2`、不要再寫
    `append_round_record`（與既有『未完成輪不記錄趨勢圖』約定一致，見 docs/engine-rounds-history.md）。
    """
    osc = cfg["oscillation"]

    prev_phase = progress.get("phase")
    prev_pass = progress.get("last_pass")
    phase_advanced = (prev_phase is not None and str(phase) != str(prev_phase))
    pass_climbed = (prev_pass is not None and cur_pass > as_int(prev_pass))
    progressed = phase_advanced or pass_climbed

    sig = progress_signature(cfg, control)
    prev_sig = progress.get("sig")
    idle_rounds = as_int(progress.get("idle"))
    idle_rounds = 0 if (prev_sig is None or sig != prev_sig) else idle_rounds + 1
    killed_streak = (as_int(progress.get("killed_streak")) + 1) if killed else 0
    no_activity = max(idle_rounds, killed_streak)

    is_fail_verify = (not killed) and ("驗證" in mode) and (result == "FAIL")
    stuck_level = as_int(get_val(control, "stuck_level"))
    rounds_since = as_int(get_val(control, "rounds_since_progress"))
    enhanced_used = as_int(get_val(control, "enhanced_rounds_used"))

    if progressed:
        rounds_since = 0
        fail_fingerprints.clear()
        if stuck_level != 0:
            role_tier = model_tier_label(cfg, "execute", 0)
            log_both(f"  ↩ 有進展，stuck 解除、換回角色預設模型（{role_tier}）。")
        stuck_level, enhanced_used = 0, 0
        set_val(control, "current_model_tier", model_tier_label(cfg, "execute", 0))
        set_human_required(control, False)
    elif is_fail_verify:
        rounds_since += 1
        fail_fingerprints.append(fail_fingerprint(control))
        if stuck_level == 1:
            enhanced_used += 1
    elif no_activity and stuck_level == 1:
        enhanced_used += 1

    oscillating = detect_oscillation(fail_fingerprints, osc["osc_window"], osc["osc_distinct_max"])
    idle_stalled = no_activity >= osc["stall_threshold"]
    fail_stalled = rounds_since >= osc["stall_threshold"]
    hard_stop = False
    if stuck_level == 0 and (oscillating or fail_stalled or idle_stalled):
        stuck_level = 1
        upgraded_tier = model_tier_label(cfg, "execute", 1)
        set_val(control, "current_model_tier", upgraded_tier)
        enhanced_used = 0
        why = ("震盪 A↔B" if oscillating
               else f"連續 {no_activity} 輪無任何活動（agent 未提交/計數器未動,疑似空轉或 CLI 逾時）"
               if idle_stalled else f"連續 {rounds_since} 輪無進展")
        log_both(f"  ⬆ {leaf_label}偵測到卡住（{why}）→ 升級模型（{upgraded_tier}）。")
    elif stuck_level == 1 and enhanced_used >= osc["enhanced_max_rounds"]:
        stuck_level = 2
        final_tier = model_tier_label(cfg, "execute", 2)
        set_val(control, "current_model_tier", final_tier)
        log_both(f"  ⬆⬆ {leaf_label}升級模型（{model_tier_label(cfg, 'execute', 1)}）試了 {enhanced_used} 輪仍卡"
                 f" → 再升級（{final_tier}）。下一輪請 agent 開 BLOCKING Issue 並凍結互卡任務。")
    elif stuck_level == 2 and max(rounds_since, no_activity) >= (osc["stall_threshold"] + osc["human_stop_after"]):
        why = "無任何活動" if no_activity >= rounds_since else "無進展"
        log_both(f"  ⛔ {leaf_label}升級人類後仍{why}（硬性保險觸發）→ 停下交人類。")
        set_val(control, "stuck_level", "2")
        set_val(control, "rounds_since_progress", str(rounds_since))
        hard_stop = True

    out = {
        "stuck_level": stuck_level, "rounds_since": rounds_since, "enhanced_used": enhanced_used,
        "no_activity": no_activity, "progressed": progressed, "hard_stop": hard_stop,
    }
    if hard_stop:
        return out

    set_val(control, "rounds_since_progress", str(rounds_since))
    set_val(control, "stuck_level", str(stuck_level))
    set_val(control, "enhanced_rounds_used", str(enhanced_used))
    new_progress = {"sig": sig, "idle": idle_rounds, "killed_streak": killed_streak,
                     "phase": phase, "last_pass": cur_pass}
    out["progress"] = new_progress
    return out


def main():
    ap = argparse.ArgumentParser(description="階段③:執行收斂迴圈")
    add_common_args(ap)
    args = ap.parse_args()
    apply_quiet_flag(args.quiet)
    ws = resolve_workspace(args.workspace)

    cfg = load_config()
    cfg["_workspace"] = ws
    rc = _run_execute(cfg)
    status = {0: "done", 1: "stopped", 2: "human_required"}.get(rc, "stopped")
    update_index(cfg, status)
    return rc


def _run_execute(cfg: dict) -> int:
    lock_path = os.path.join(cfg["runtime"]["state_dir"], "run.lock")
    try:
        acquire_run_lock(lock_path, stale_seconds=lock_stale_seconds(cfg))
    except WorkspaceBusy as e:
        print(f"✋ {e}", flush=True)
        return 1
    try:
        if tree_enabled(cfg):
            return _run_tree_execute_locked(cfg, lock_path)
        return _run_execute_locked(cfg, lock_path)
    finally:
        release_run_lock(lock_path)


def _run_execute_locked(cfg: dict, lock_path: str | None = None) -> int:
    repo_basename = os.path.basename(os.path.normpath(cfg["repo"]))
    ws_name = cfg["workspace"]
    start_epoch = int(time.time())
    run_id = f"{repo_basename}:{ws_name}:{start_epoch}"
    cfg["run_id"] = run_id

    rt = cfg["runtime"]
    control = cfg["control"]
    osc = cfg["oscillation"]
    
    # Log run_started event
    append_round_record(cfg, {
        "run_id": run_id,
        "ts": datetime.now().strftime("%F %T"),
        "type": "run_started",
        "payload": {
            "mode": cfg.get("generation", {}).get("mode", "gated"),
            "stage": "execute"
        }
    })
    log_path = rt["log_file"]

    def hb(msg=""):
        print(msg, flush=True)

    def log_line(msg=""):
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(msg + "\n")
        except OSError as e:
            logger.error(f"Failed to write log: {e}")

    def log_both(msg=""):
        hb(msg)
        log_line(msg)

    os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
    if not report_preflight(cfg, "execute", log_both):
        return 1

    log_line("")
    log_line(f"########## LOOP 啟動 {datetime.now():%F %T} ##########")
    hb(f"Loop 啟動。框架={cfg['framework_path']}  詳細輸出：{log_path}（tail -f 觀看）\n")

    # 把框架 commit 快照寫進 CONTROL（供追溯）
    fw = cfg["framework_path"]
    if os.path.isdir(fw) and shutil.which("git"):
        try:
            r = subprocess.run(["git", "-C", fw, "rev-parse", "--short", "HEAD"],
                               capture_output=True, text=True)
            if r.returncode == 0 and r.stdout.strip():
                set_val(control, "framework_ref", r.stdout.strip())
        except OSError:
            pass

    prompts = cfg["agent"]["prompts"]
    base_prompt = fmt_prompt(prompts.get("base", ""), control=control, framework=fw)
    escalation_prompt = fmt_prompt(prompts.get("escalation", ""), control=control, framework=fw)

    state_dir = rt["state_dir"]
    os.makedirs(state_dir, exist_ok=True)
    fail_fingerprints, progress = reconstruct_history_and_progress(cfg, osc["osc_window"])
    if fail_fingerprints:
        log_both(f"  ↺ 從 rounds.jsonl 接續震盪歷史（{len(fail_fingerprints)} 筆）。")
    if progress:
        log_both(f"  ↺ 從 rounds.jsonl 接續進度標記（idle={progress.get('idle', '0')}）。")

    for i in range(1, rt["max_rounds"] + 1):
        if check_stop_requested(cfg, log_both):
            return 1
        rotate_log_if_needed(cfg)
        if not inspect_and_fix_blank(cfg, log_both):
            log_both("🧑‍⚖️ 偵測到 human_required：核心狀態檔毀損且無法自動修復，loop 停止。")
            set_human_required(control, True, "broken_control_file", "核心狀態檔毀損且無法自動修復")
            return 2
        if lock_path:
            touch_run_lock(lock_path)    # 鎖心跳：長跑時不被誤判殘留而被搶鎖
        sync_framework_docs(cfg, log_both)

        passed, human_conflict = run_git_review_gate(cfg, control, log_both)
        if human_conflict:
            set_human_required(control, True, "git_review_human_conflict", "偵測到人類與 Agent 的 Commit 衝突，停止自動 Revert")
            log_both("🧑‍⚖️ 偵測到 human_required：因人類與 Agent 衝突，loop 停止。")
            return 2
        if not passed:
            log_both("  [Git Review Gate] 已還原，跳過本輪執行以重試。")
            continue

        if os.path.exists(control):
            if is_done(cfg, control):
                log_both(f"✅ 停止條件成立，於第 {i-1} 輪後完成。LOOP COMPLETE")
                append_round_record(cfg, {
                    "run_id": run_id,
                    "ts": datetime.now().strftime("%F %T"),
                    "type": "loop_complete",
                    "message": f"停止條件成立，於第 {i-1} 輪後完成。"
                })
                return 0
            if human_needed(cfg, control):
                log_both("🧑‍⚖️ 偵測到 human_required：已凍結互卡任務，需你介入裁決。loop 停止。")
                reason = get_val(control, "human_required_reason")
                if not reason:
                    set_human_required(control, True, "agent_requested", "已凍結互卡任務，需你介入裁決。")
                append_round_record(cfg, {
                    "run_id": run_id,
                    "ts": datetime.now().strftime("%F %T"),
                    "type": "human_required",
                    "message": "已凍結互卡任務，需你介入裁決。"
                })
                return 2

        stuck_level = as_int(get_val(control, "stuck_level"))
        model = select_model(cfg, "execute", stuck_level)
        tier = model_tier_label(cfg, "execute", stuck_level)
        prompt = base_prompt + ("\n" + escalation_prompt if stuck_level >= 1 else "")
        cmd = build_cmd(cfg, model, prompt)

        ts = datetime.now().strftime("%F %T")
        hb(f"▶ Round {i} 開始  ({ts})  模型階層={tier}")
        log_line(f"\n════════════ Round {i}  ({ts})  tier={tier} model={model} ════════════")
        log_both(f"  [Execute Prompt]\n{'-'*40}\n{prompt}\n{'-'*40}")

        rc, killed = run_agent(cmd, cfg)
        git_guard(cfg, i, log_both)
        if killed:
            hb(f"  Round {i} 被 watchdog 中斷（{killed}），清理後重跑下一輪。")
            set_val(control, "last_round_result", "NA")
            set_val(control, "last_round_mode", "中斷")
        else:
            hb(f"  Round {i} 結束 (rc={rc})")

        # 讀本輪結果，更新震盪偵測
        phase = get_val(control, "current_phase")
        cur_pass = as_int(get_val(control, f"p{phase}_consecutive_pass"))
        mode = get_val(control, "last_round_mode") or ""
        result = get_val(control, "last_round_result") or ""

        upd = update_stuck_state(cfg, control, log_both, fail_fingerprints=fail_fingerprints, progress=progress,
                                  killed=killed, mode=mode, result=result, phase=phase, cur_pass=cur_pass)
        if upd["hard_stop"]:
            set_human_required(control, True, "stuck_level_2_hard_stop", f"連續 {upd.get('rounds_since')} 輪無進展，觸發硬性保險")
            return 2

        progress = upd["progress"]   # 同步記憶體,供下一輪比對
        
        last_safe_sha = get_val(control, "last_safe_sha") or ""
        current_head = git_head()
        
        # Oscillation fingerprint tracking
        fail_fp = None
        is_fail_verify = (not killed) and ("驗證" in mode) and (result == "FAIL")
        if is_fail_verify:
            fail_fp = fail_fingerprint(control)
            
        append_round_record(cfg, {
            "run_id": run_id,
            "ts": datetime.now().strftime("%F %T"),
            "type": "round_finished",
            "round": i,
            "loop_type": "execute",
            "phase": phase,
            "leaf": None,
            "result": result,
            "mode": mode,
            "killed": killed,
            "stuck_level": upd["stuck_level"],
            "rounds_since_progress": upd["rounds_since"],
            "enhanced_rounds_used": upd["enhanced_used"],
            "no_activity": upd["no_activity"],
            "consecutive_pass": cur_pass,
            "progressed": upd["progressed"],
            "model_tier": tier,
            "progress_sig": progress.get("sig") or "",
            "idle_rounds": as_int(progress.get("idle")),
            "killed_streak": as_int(progress.get("killed_streak")),
            "fail_fingerprint": fail_fp,
            "artifacts": {
                "changed_files": changed_files(),
                "git_head_before": last_safe_sha,
                "git_head_after": current_head,
                "commit": current_head,
            }
        })

        time.sleep(rt["interval_seconds"])

    log_both(f"⛔ 已達 max_rounds={rt['max_rounds']}，停止（尚未完成，請檢查 {control}）。")
    set_human_required(control, True, "max_rounds_reached", f"執行輪數已達上限 max_rounds={rt['max_rounds']}")
    append_round_record(cfg, {
        "run_id": run_id,
        "ts": datetime.now().strftime("%F %T"),
        "type": "human_required",
        "message": f"已達 max_rounds={rt['max_rounds']}，停止（尚未完成）。"
    })
    return 2


def _run_tree_execute_locked(cfg: dict, lock_path: str | None = None) -> int:
    """樹模式執行：葉子逐一跑、父等子解鎖、回流分兩種。

    排程：pick ready leaf → agent 跑葉子 → 收斂 → 解鎖父 → 整合驗證。
    回流 (a) 葉子內容錯 → NEEDS_REVISION（受 max_leaf_reflow 管）。
    回流 (b) 結構錯（缺葉子/需再拆）→ 停、交人（授權紅線）。
    """
    repo_basename = os.path.basename(os.path.normpath(cfg["repo"]))
    ws_name = cfg["workspace"]
    start_epoch = int(time.time())
    run_id = f"{repo_basename}:{ws_name}:{start_epoch}"
    cfg["run_id"] = run_id

    rt = cfg["runtime"]
    control = cfg["control"]
    osc = cfg["oscillation"]
    
    # Log run_started event
    append_round_record(cfg, {
        "run_id": run_id,
        "ts": datetime.now().strftime("%F %T"),
        "type": "run_started",
        "payload": {
            "mode": cfg.get("generation", {}).get("mode", "gated"),
            "stage": "execute"
        }
    })
    breaker = cfg.get("breaker", {})
    # ── 硬 BREAKER：max_leaf_reflow（Chunk 7 三條硬 BREAKER 之一）──
    # 單葉被整合打回超過 R 次 = 跨層垂直震盪，撞線即凍結交人。
    max_leaf_reflow = breaker.get("max_leaf_reflow", 3)
    log_path = rt["log_file"]
    tree_path = tree_md_path(cfg)

    def hb(msg=""):
        print(msg, flush=True)

    def log_line(msg=""):
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(msg + "\n")
        except OSError as e:
            logger.error(f"Failed to write log: {e}")

    def log_both(msg=""):
        hb(msg)
        log_line(msg)

    os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
    if not report_preflight(cfg, "tree_execute", log_both):
        return 1

    log_line("")
    log_line(f"########## TREE EXECUTE 啟動 {datetime.now():%F %T} ##########")
    hb(f"Tree Execute 啟動。框架={cfg['framework_path']}  詳細輸出：{log_path}\n")

    fw = cfg["framework_path"]
    if os.path.isdir(fw) and shutil.which("git"):
        try:
            r = subprocess.run(["git", "-C", fw, "rev-parse", "--short", "HEAD"],
                               capture_output=True, text=True)
            if r.returncode == 0 and r.stdout.strip():
                set_val(control, "framework_ref", r.stdout.strip())
        except OSError:
            pass

    prompts = cfg["agent"]["prompts"]
    base_prompt = fmt_prompt(prompts.get("base", ""), control=control, framework=fw)
    escalation_prompt = fmt_prompt(prompts.get("escalation", ""), control=control, framework=fw)

    state_dir = rt["state_dir"]
    os.makedirs(state_dir, exist_ok=True)
    fail_fingerprints, progress = reconstruct_history_and_progress(cfg, osc["osc_window"])
    if fail_fingerprints:
        log_both(f"  ↺ 從 rounds.jsonl 接續震盪歷史（{len(fail_fingerprints)} 筆）。")
    if progress:
        log_both(f"  ↺ 從 rounds.jsonl 接續進度標記（idle={progress.get('idle', '0')}）。")

    current_leaf = None

    for i in range(1, rt["max_rounds"] + 1):
        if check_stop_requested(cfg, log_both):
            return 1
        rotate_log_if_needed(cfg)
        if not inspect_and_fix_blank(cfg, log_both):
            log_both("🧑‍⚖️ 偵測到 human_required：核心狀態檔毀損且無法自動修復，loop 停止。")
            set_human_required(control, True, "broken_control_file", "核心狀態檔毀損且無法自動修復")
            return 2
        if lock_path:
            touch_run_lock(lock_path)
        sync_framework_docs(cfg, log_both)

        # ── 獨立 Git Review Gate：審查上一輪 commit，破壞性改動自動 revert（與平模式一致，稽核 #2）──
        passed, human_conflict = run_git_review_gate(cfg, control, log_both)
        if human_conflict:
            set_human_required(control, True, "git_review_human_conflict", "偵測到人類與 Agent 的 Commit 衝突，停止自動 Revert")
            log_both("🧑‍⚖️ 偵測到 human_required：Git Review Gate 判定需人類介入，loop 停止。")
            return 2
        if not passed:
            log_both("  [Git Review Gate] 已還原/退回，跳過本輪執行以重試。")
            current_leaf = None    # 被 revert 後重新挑葉子,避免指向已回退狀態
            continue

        # ── 選下一個可執行葉子 ──
        if current_leaf is None:
            current_leaf = next_ready_leaf(tree_path)
            if current_leaf is None:
                root_id = get_val(tree_path, "tree_root")
                if root_id and all_children_converged(tree_path, root_id):
                    log_both(f"✅ 樹的所有節點已收斂，於第 {i-1} 輪後完成。TREE EXECUTE COMPLETE")
                    append_round_record(cfg, {
                        "run_id": run_id,
                        "ts": datetime.now().strftime("%F %T"),
                        "type": "loop_complete",
                        "message": f"樹的所有節點已收斂，於第 {i-1} 輪後完成。"
                    })
                    return 0
                log_both("⚠️ 無可執行葉子但樹未完成 → 停下交人。")
                append_round_record(cfg, {
                    "run_id": run_id,
                    "ts": datetime.now().strftime("%F %T"),
                    "type": "human_required",
                    "message": "無可執行葉子但樹未完成。"
                })
                return 2

        node = get_node(tree_path, current_leaf)
        if node and node["state"] in (LEAF, NEEDS_REVISION):
            set_node_field(tree_path, current_leaf, "state", IN_PROGRESS)

        # ── 模型選擇（沿用既有 stuck_level 階梯）──
        if os.path.exists(control):
            if is_done(cfg, control):
                set_node_field(tree_path, current_leaf, "state", CONVERGED)
                log_both(f"  🍃 葉子 [{current_leaf}] 收斂。")
                rc = _tree_try_unlock(cfg, tree_path, current_leaf, max_leaf_reflow, log_both)
                if rc is not None:
                    return rc
                current_leaf = None
                continue
            if human_needed(cfg, control):
                log_both("🧑‍⚖️ 偵測到 human_required → 停下交人。")
                append_round_record(cfg, {
                    "run_id": run_id,
                    "ts": datetime.now().strftime("%F %T"),
                    "type": "human_required",
                    "message": "偵測到 human_required。"
                })
                return 2

        stuck_level = as_int(get_val(control, "stuck_level"))
        model = select_model(cfg, "execute", stuck_level)
        tier = model_tier_label(cfg, "execute", stuck_level)
        prompt = base_prompt + ("\n" + escalation_prompt if stuck_level >= 1 else "")
        cmd = build_cmd(cfg, model, prompt)

        ts = datetime.now().strftime("%F %T")
        hb(f"▶ Round {i} 葉子=[{current_leaf}] ({ts}) tier={tier}")
        log_line(f"\n════════════ Round {i}  leaf={current_leaf}  ({ts})  tier={tier} model={model} ════════════")
        log_both(f"  [Tree Execute Prompt]\n{'-'*40}\n{prompt}\n{'-'*40}")

        rc, killed = run_agent(cmd, cfg)
        git_guard(cfg, i, log_both)
        if killed:
            hb(f"  Round {i} 被 watchdog 中斷（{killed}）。")
            set_val(control, "last_round_result", "NA")
            set_val(control, "last_round_mode", "中斷")
        else:
            hb(f"  Round {i} 結束 (rc={rc})")

        # ── 進展判定 + stuck 升級（沿用既有邏輯）──
        phase = get_val(control, "current_phase")
        cur_pass = as_int(get_val(control, f"p{phase}_consecutive_pass"))
        mode = get_val(control, "last_round_mode") or ""
        result = get_val(control, "last_round_result") or ""

        upd = update_stuck_state(cfg, control, log_both, fail_fingerprints=fail_fingerprints, progress=progress,
                                  killed=killed, mode=mode, result=result, phase=phase, cur_pass=cur_pass,
                                  leaf_label=f"葉子 [{current_leaf}] ")
        if upd["hard_stop"]:
            return 2

        progress = upd["progress"]
        
        last_safe_sha = get_val(control, "last_safe_sha") or ""
        current_head = git_head()
        
        # Oscillation fingerprint tracking
        fail_fp = None
        is_fail_verify = (not killed) and ("驗證" in mode) and (result == "FAIL")
        if is_fail_verify:
            fail_fp = fail_fingerprint(control)
            
        append_round_record(cfg, {
            "run_id": run_id,
            "ts": datetime.now().strftime("%F %T"),
            "type": "round_finished",
            "round": i,
            "loop_type": "tree",
            "phase": phase,
            "leaf": current_leaf,
            "result": result,
            "mode": mode,
            "killed": killed,
            "stuck_level": upd["stuck_level"],
            "rounds_since_progress": upd["rounds_since"],
            "enhanced_rounds_used": upd["enhanced_used"],
            "no_activity": upd["no_activity"],
            "consecutive_pass": cur_pass,
            "progressed": upd["progressed"],
            "model_tier": tier,
            "progress_sig": progress.get("sig") or "",
            "idle_rounds": as_int(progress.get("idle")),
            "killed_streak": as_int(progress.get("killed_streak")),
            "fail_fingerprint": fail_fp,
            "artifacts": {
                "changed_files": changed_files(),
                "git_head_before": last_safe_sha,
                "git_head_after": current_head,
                "commit": current_head,
            }
        })

        # ── 回流偵測：agent 寫 CONTROL 欄位觸發 ──
        structure_err = get_val(control, "tree_structure_error") or ""
        if structure_err.lower() == "true":
            log_both(f"  ⛔ 整合發現結構錯誤（缺葉子/需再拆）→ 停下交人（結構變動屬授權紅線）。")
            set_human_required(control, True, "tree_structure_error", "整合發現結構錯誤（缺葉子/需再拆），結構變動屬授權紅線。")
            return 2

        reflow_target = get_val(control, "tree_reflow_target") or ""
        if reflow_target:
            did_reflow = False
            for tid in (t.strip() for t in reflow_target.split(",") if t.strip()):
                tnode = get_node(tree_path, tid)
                if tnode is None:
                    continue
                if tnode["reflow_count"] >= max_leaf_reflow:
                    # ── 硬 BREAKER：max_leaf_reflow（Chunk 7）──
                    # 跨層垂直震盪：整合 ↔ 葉子反覆打回，既有水平震盪偵測抓不到。
                    # 撞線即凍結交人，程式不准升級/重試/自我放寬。
                    log_both(f"  ⛔ 葉子 [{tid}] 回流次數已達上限 ({max_leaf_reflow})"
                             f" → 凍結交人（垂直震盪 breaker）。")
                    set_node_field(tree_path, tid, "state", FROZEN)
                    set_human_required(control, True, "max_leaf_reflow_exceeded", f"葉子 [{tid}] 回流次數已達上限 ({max_leaf_reflow})，觸發垂直震盪硬性斷路器。")
                    return 2
                mark_leaf_needs_revision(tree_path, tid)
                log_both(f"  ↩ 葉子 [{tid}] 退回修改（回流 #{tnode['reflow_count']+1}）。")
                did_reflow = True
            set_val(control, "tree_reflow_target", "")
            if did_reflow:
                current_leaf = None
                continue

        # ── 葉子收斂判定 ──
        if os.path.exists(control) and is_done(cfg, control):
            set_node_field(tree_path, current_leaf, "state", CONVERGED)
            log_both(f"  🍃 葉子 [{current_leaf}] 收斂。")
            # stuck 歸零供下一葉子
            stuck_level, enhanced_used, rounds_since = 0, 0, 0
            set_val(control, "stuck_level", "0")
            set_val(control, "enhanced_rounds_used", "0")
            set_val(control, "rounds_since_progress", "0")
            fail_fingerprints.clear()

            rc = _tree_try_unlock(cfg, tree_path, current_leaf, max_leaf_reflow, log_both)
            if rc is not None:
                return rc
            current_leaf = None
            continue

        time.sleep(rt["interval_seconds"])

    log_both(f"⛔ 已達 max_rounds={rt['max_rounds']}，停止。")
    set_human_required(control, True, "max_rounds_reached", f"執行輪數已達上限 max_rounds={rt['max_rounds']}")
    append_round_record(cfg, {
        "run_id": cfg.get("run_id"),
        "ts": datetime.now().strftime("%F %T"),
        "type": "human_required",
        "message": f"已達 max_rounds={rt['max_rounds']}，停止。"
    })
    return 2


def _tree_try_unlock(cfg, tree_path, leaf_id, max_leaf_reflow, log_both) -> int | None:
    """葉子收斂後：嘗試解鎖父節點、觸發整合驗證。

    回傳 int = 該值應直接 return（完成/停下交人）；None = 繼續迴圈。
    """
    parent_id = try_unlock_parent(tree_path, leaf_id)
    if parent_id is None:
        return None

    log_both(f"  📦 父節點 [{parent_id}] 所有子都已收斂 → 解鎖。")

    # 遞迴往上：父也可能解鎖祖父
    root_id = get_val(tree_path, "tree_root")
    if parent_id == root_id:
        if all_children_converged(tree_path, root_id):
            log_both(f"✅ 根節點 [{root_id}] 所有子都已收斂。TREE EXECUTE COMPLETE")
            append_round_record(cfg, {
                "run_id": cfg.get("run_id"),
                "ts": datetime.now().strftime("%F %T"),
                "type": "loop_complete",
                "message": f"根節點 [{root_id}] 所有子都已收斂。TREE EXECUTE COMPLETE"
            })
            return 0
    else:
        grandparent_id = try_unlock_parent(tree_path, parent_id)
        if grandparent_id:
            log_both(f"  📦 祖父節點 [{grandparent_id}] 也已解鎖。")

    return None


if __name__ == "__main__":
    sys.exit(main())
