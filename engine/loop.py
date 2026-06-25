#!/usr/bin/env python3
"""
loop.py — 通用 Loop Engineering 執行引擎（config 驅動、支援 N 階段）。

反覆觸發 coding agent 跑 CONTROL.md，偵測「改A壞B」震盪、自動三層升級模型（預設→增強→人類）。
"""

import os
import sys
import time
import argparse
import subprocess
import shutil
import logging
from datetime import datetime

from .config import load_config, fmt_prompt
from .git_utils import inspect_and_fix_blank, git_guard
from .state import get_val, set_val, as_int, load_fail_history, save_fail_history, progress_signature, load_progress, save_progress
from .agent_runner import build_cmd, run_agent
from .utils import (
    WorkspaceBusy, acquire_run_lock, release_run_lock, touch_run_lock, lock_stale_seconds,
    add_common_args, resolve_workspace, apply_quiet_flag, rotate_log_if_needed,
    update_index, report_preflight, fail_fingerprint, detect_oscillation, is_done, human_needed
)

logger = logging.getLogger(__name__)

try:                          # Windows 主控台 cp950 → 強制 UTF-8 輸出
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass


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
        return _run_execute_locked(cfg, lock_path)
    finally:
        release_run_lock(lock_path)


def _run_execute_locked(cfg: dict, lock_path: str | None = None) -> int:
    rt = cfg["runtime"]
    control = cfg["control"]
    osc = cfg["oscillation"]
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
    fail_history = load_fail_history(cfg, osc["osc_window"])  # 持久化：重啟接續，不歸零
    if fail_history:
        log_both(f"  ↺ 從 .loop_state 接續震盪歷史（{len(fail_history)} 筆）。")
    progress = load_progress(cfg)        # 持久化：跨重啟正確判進展 + 無活動偵測,不歸零
    if progress:
        log_both(f"  ↺ 從 .loop_state 接續進度標記（idle={progress.get('idle', '0')}）。")

    for i in range(1, rt["max_rounds"] + 1):
        rotate_log_if_needed(cfg)
        inspect_and_fix_blank(cfg, log_both)
        if lock_path:
            touch_run_lock(lock_path)    # 鎖心跳：長跑時不被誤判殘留而被搶鎖

        if os.path.exists(control):
            if is_done(cfg, control):
                log_both(f"✅ 停止條件成立，於第 {i-1} 輪後完成。LOOP COMPLETE")
                return 0
            if human_needed(cfg, control):
                log_both("🧑‍⚖️ 偵測到 human_required：已凍結互卡任務，需你介入裁決。loop 停止。")
                return 2

        tier = get_val(control, "current_model_tier") or "default"
        models = cfg["agent"]["models"]
        model = models["enhanced"] if tier == "enhanced" else models["default"]
        prompt = base_prompt + ("\n" + escalation_prompt if tier == "enhanced" else "")
        cmd = build_cmd(cfg, model, prompt)

        ts = datetime.now().strftime("%F %T")
        hb(f"▶ Round {i} 開始  ({ts})  模型階層={tier}")
        log_line(f"\n════════════ Round {i}  ({ts})  tier={tier} model={model} ════════════")

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

        # 進展判定（跨 phase 正確；prev_* 持久化,重啟也準）
        prev_phase = progress.get("phase")
        prev_pass = progress.get("last_pass")
        phase_advanced = (prev_phase is not None and str(phase) != str(prev_phase))
        pass_climbed = (prev_pass is not None and cur_pass > as_int(prev_pass))
        progressed = phase_advanced or pass_climbed

        # 無活動偵測：簽章連續不變 = agent 沒提交、計數器沒動（空轉/反覆中斷/CLI 壞）
        sig = progress_signature(cfg, control)
        prev_sig = progress.get("sig")
        idle_rounds = as_int(progress.get("idle"))
        idle_rounds = 0 if (prev_sig is None or sig != prev_sig) else idle_rounds + 1
        # 連續被 watchdog 中斷的輪數（獨立於 git；防『中斷留半套被 commit 而 HEAD 移動』騙過 idle）
        killed_streak = (as_int(progress.get("killed_streak")) + 1) if killed else 0
        no_activity = max(idle_rounds, killed_streak)

        is_fail_verify = (not killed) and ("驗證" in mode) and (result == "FAIL")
        stuck_level = as_int(get_val(control, "stuck_level"))
        rounds_since = as_int(get_val(control, "rounds_since_progress"))
        enhanced_used = as_int(get_val(control, "enhanced_rounds_used"))

        if progressed:
            rounds_since = 0
            fail_history.clear()
            save_fail_history(cfg, fail_history)
            if stuck_level != 0:
                log_both("  ↩ 有進展，stuck 解除、換回預設模型。")
            stuck_level, enhanced_used = 0, 0
            set_val(control, "current_model_tier", "default")
            set_val(control, "human_required", "false")
        elif is_fail_verify:
            rounds_since += 1
            fail_history.append(fail_fingerprint(control))
            save_fail_history(cfg, fail_history)
            if stuck_level == 1:
                enhanced_used += 1
        elif no_activity and stuck_level == 1:
            # 無活動但已在增強層 → 也累計增強輪數,免得卡在 Lv1 永不升人類
            enhanced_used += 1

        # 卡死 = 失敗驗證無進展 / 震盪 / 無任何活動,任一達門檻
        oscillating = detect_oscillation(fail_history, osc["osc_window"], osc["osc_distinct_max"])
        idle_stalled = no_activity >= osc["stall_threshold"]
        fail_stalled = rounds_since >= osc["stall_threshold"]
        if stuck_level == 0 and (oscillating or fail_stalled or idle_stalled):
            stuck_level = 1
            set_val(control, "current_model_tier", "enhanced")
            enhanced_used = 0
            why = ("震盪 A↔B" if oscillating
                   else f"連續 {no_activity} 輪無任何活動（agent 未提交/計數器未動,疑似空轉或 CLI 逾時）"
                   if idle_stalled else f"連續 {rounds_since} 輪無進展")
            log_both(f"  ⬆ 偵測到卡住（{why}）→ 換【增強模型】重試。")
        elif stuck_level == 1 and enhanced_used >= osc["enhanced_max_rounds"]:
            stuck_level = 2
            log_both(f"  ⬆⬆ 增強模型試了 {enhanced_used} 輪仍卡 → 升級【人類】。"
                     f" 下一輪請 agent 開 BLOCKING Issue 並凍結互卡任務。")
        elif stuck_level == 2 and max(rounds_since, no_activity) >= (osc["stall_threshold"] + osc["human_stop_after"]):
            why = "無任何活動" if no_activity >= rounds_since else "無進展"
            log_both(f"  ⛔ 升級人類後仍{why}（硬性保險觸發）→ 停下交人類。")
            set_val(control, "stuck_level", "2")
            set_val(control, "rounds_since_progress", str(rounds_since))
            save_progress(cfg, sig=sig, idle=idle_rounds, killed_streak=killed_streak,
                          phase=phase, last_pass=cur_pass)
            return 2

        set_val(control, "rounds_since_progress", str(rounds_since))
        set_val(control, "stuck_level", str(stuck_level))
        set_val(control, "enhanced_rounds_used", str(enhanced_used))
        progress = {"sig": sig, "idle": idle_rounds, "killed_streak": killed_streak,
                    "phase": phase, "last_pass": cur_pass}   # 同步記憶體,供下一輪比對
        save_progress(cfg, **progress)

        time.sleep(rt["interval_seconds"])

    log_both(f"⛔ 已達 max_rounds={rt['max_rounds']}，停止（尚未完成，請檢查 {control}）。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
