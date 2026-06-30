#!/usr/bin/env python3
"""
plan_loop.py — 階段②：規劃書「生成收斂」迴圈（code1）。

把「產生規劃書」本身當成一個 Loop Engineering 收斂任務。每個「循環(cycle)」分兩輪：
  Round A（生成）：agent 從 REQUIREMENTS 獨立(重)推導/精修規劃書(loop.config.yaml + CONTROL.md + phases/*.md)。
  Round B（審查，獨立 context）：另一個 agent 呼叫只審不生,跑 Plan Gate,**不得修改規劃書檔**(read-only)。
"""

import os
import sys
import time
import argparse
import logging
from datetime import datetime

from config import load_config, fmt_prompt, select_model, model_tier_label
from git_utils import in_git_repo, changed_files, changed_files_between, git_guard, git_head
from state import get_val, set_val, as_int, append_round_record, append_round_artifact, append_run_finished, check_stop_requested, set_plan_human_required
from agent_runner import build_cmd, run_agent
# tree module imports removed
from utils import (
    WorkspaceBusy, acquire_run_lock, release_run_lock, touch_run_lock, lock_stale_seconds,
    add_common_args, resolve_workspace, apply_quiet_flag, rotate_log_if_needed,
    update_index, report_preflight, sync_framework_docs
)

logger = logging.getLogger(__name__)

try:                          # Windows 主控台 cp950 → 強制 UTF-8 輸出
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

PLAN_SEED = """# 📐 PLAN — 規劃書生成控制（階段②，由 plan_loop.py 驅動）

> 文件即狀態:記錄「規劃書」收斂進度。規劃書本體在 .loop/{{loop.config.yaml, CONTROL.md, phases/}}。
> 收斂 = 連續 plan_converge_threshold 個循環「無實質變更且 Plan Gate PASS」。

```yaml
plan_status: drafting          # drafting / converged / stuck_human
plan_stable_rounds: 0          # 連續「無實質變更且 Gate PASS」的循環數
plan_gate_last:                # PASS / FAIL（審查輪回填）
plan_changed_last:             # true / false（生成輪回填:本輪是否實質改動規劃書）
plan_version: 1

# 卡死偵測與升級（與 loop.py 對稱;多由 plan_loop.py 維護）
plan_rounds_since_progress: 0
plan_stuck_level: 0
plan_model_tier: ""            # 引擎回填：fast / normal / thinking
plan_enhanced_rounds_used: 0
plan_human_required: false
```
"""


def plan_md_path(cfg):
    return cfg["control"]


def seed_plan(path):
    return False


def plan_files_changed(cfg):
    """Round A 的 git 改動是否觸及『規劃書檔』(.loop/ 下,排除 state.json/log)。"""
    if not in_git_repo():
        return None  # 無 git → 交由 agent 回填的 plan_changed_last 判斷
    loop_dir = os.path.dirname(cfg["control"]).replace("\\", "/") or "."
    exclude = ("state.json", "plan.log", "loop.log")
    for c in changed_files():
        cn = c.replace("\\", "/")
        if not cn.startswith(loop_dir + "/"):
            continue
        base = os.path.basename(cn)
        if base in exclude or base.startswith("loop.log") or base.startswith("plan.log"):
            continue
        if ".loop_state" in cn:
            continue
        return True
    return False


def build_gen_prompt(cfg, fw, plan_md, requirements):
    tpl = cfg["agent"]["prompts"]["plan"]
    return fmt_prompt(tpl, framework=fw, plan_md=plan_md, requirements=requirements, control=cfg["control"])


def build_gate_prompt(cfg, fw, plan_md, requirements):
    tpl = cfg["agent"]["prompts"]["plan_gate"]
    return fmt_prompt(tpl, framework=fw, plan_md=plan_md, requirements=requirements, control=cfg["control"])


def main():
    ap = argparse.ArgumentParser(description="階段②:規劃書生成收斂迴圈")
    ap.add_argument("--mode", choices=["gated", "auto"], default=None,
                    help="覆蓋 config.generation.mode")
    add_common_args(ap)
    args = ap.parse_args()
    apply_quiet_flag(args.quiet)
    ws = resolve_workspace(args.workspace)

    cfg = load_config()
    cfg["_workspace"] = ws
    rc = _run_plan(cfg, args.mode)
    status = {0: "plan_proceeding", 1: "plan_stopped", 2: "plan_human_required"}.get(rc, "plan_stopped")
    update_index(cfg, status)
    return rc


def _run_plan(cfg, mode_override):
    lock_path = os.path.join(cfg["runtime"]["state_dir"], "run.lock")
    try:
        acquire_run_lock(lock_path, stale_seconds=lock_stale_seconds(cfg))
    except WorkspaceBusy as e:
        print(f"✋ {e}", flush=True)
        return 1
    try:
        return _run_plan_locked(cfg, mode_override, lock_path)
    finally:
        release_run_lock(lock_path)


def _run_plan_locked(cfg, mode_override, lock_path=None):
    repo_basename = os.path.basename(os.path.normpath(cfg["repo"]))
    ws_name = cfg["workspace"]
    start_epoch = int(time.time())
    run_id = f"{repo_basename}:{ws_name}:{start_epoch}"
    cfg["run_id"] = run_id
    cfg["run_id"] = run_id

    gen = cfg.get("generation") or {}
    threshold = gen.get("plan_converge_threshold", 2)
    max_rounds = gen.get("max_rounds", 30)
    interval = gen.get("interval_seconds", 10)
    mode = mode_override or gen.get("mode", "gated")
    fw = cfg["framework_path"]
    osc = cfg["oscillation"]

    cfg["runtime"]["log_file"] = gen.get("log_file", "./.loop/plan.log")
    log_path = cfg["runtime"]["log_file"]
    os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)

    def hb(m=""):
        print(m, flush=True)

    def log_both(m=""):
        hb(m)
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(m + "\n")
        except OSError:
            pass

    append_round_record(cfg, {
        "run_id": run_id,
        "ts": datetime.now().strftime("%F %T"),
        "type": "run_started",
        "workspace": ws_name,
        "mode": mode,
        "stage": "plan",
        "started_at": datetime.now().strftime("%F %T"),
    })

    def finish(status: str, code: int, human_code: str = "") -> int:
        append_run_finished(cfg, final_status=status, exit_code=code, stage="plan", human_required_code=human_code)
        return code

    if not report_preflight(cfg, "plan", log_both):
        return finish("preflight_failed", 1)

    plan_md = plan_md_path(cfg)
    if seed_plan(plan_md):
        hb(f"+ 建立生成控制檔 {plan_md}")

    req = os.path.join(os.path.dirname(cfg["control"]) or ".", "REQUIREMENTS.md")
    log_both(f"\n########## PLAN LOOP 啟動 {datetime.now():%F %T}  mode={mode} ##########")
    hb(f"規劃書生成迴圈啟動。框架={fw}  詳細輸出:{log_path}（tail -f 觀看）\n")

    rounds_since = as_int(get_val(plan_md, "plan_rounds_since_progress"))

    for i in range(1, max_rounds + 1):
        if check_stop_requested(cfg, log_both):
            return finish("stopped", 1)
        rotate_log_if_needed(cfg)
        if lock_path:
            touch_run_lock(lock_path)
        sync_framework_docs(cfg, log_both)
        if get_val(plan_md, "plan_status") == "converged":
            break
        if get_val(plan_md, "plan_human_required") == "true":
            log_both("🧑‍⚖️ plan_human_required=true：已停下交人類裁決規劃書，loop 停止。")
            return finish("human_required", 2, get_val(plan_md, "plan_human_required_code") or "")

        plan_stuck = as_int(get_val(plan_md, "plan_stuck_level"))
        gen_model = select_model(cfg, "plan", plan_stuck)
        tier = model_tier_label(cfg, "plan", plan_stuck)

        ts = datetime.now().strftime("%F %T")
        hb(f"▶ Plan Cycle {i} · Round A 生成 開始 ({ts})  模型階層={tier}")
        log_both(f"\n════════════ Plan Cycle {i} · Round A 生成 ({ts}) tier={tier} ════════════")
        cmd = build_cmd(cfg, gen_model, build_gen_prompt(cfg, fw, plan_md, req))
        git_head_before = git_head()
        git_head_before = git_head()
        rc, killed = run_agent(cmd, cfg)
        if killed:
            append_round_record(cfg, {
                "run_id": run_id,
                "ts": datetime.now().strftime("%F %T"),
                "type": "round_finished",
                "round": i,
                "loop_type": "plan",
                "phase": "plan",
                "leaf": None,
                "result": "NA",
                "mode": "plan",
                "killed": killed,
                "stuck_level": plan_stuck,
                "rounds_since_progress": rounds_since + 1,
                "enhanced_rounds_used": as_int(get_val(plan_md, "plan_enhanced_rounds_used")),
                "no_activity": 1,
                "consecutive_pass": 0,
                "progressed": False,
                "model_tier": tier,
            })
            hb(f"  Round A 被 watchdog 中斷（{killed}），清理後重跑下一個 cycle。")
            git_guard(cfg, i, log_both)
            time.sleep(interval)
            continue
        git_guard(cfg, i, log_both)

        changed = plan_files_changed(cfg)
        if changed is None:
            changed = (get_val(plan_md, "plan_changed_last") == "true")

        ts = datetime.now().strftime("%F %T")
        hb(f"▶ Plan Cycle {i} · Round B 審查(獨立) 開始 ({ts})")
        log_both(f"\n════════════ Plan Cycle {i} · Round B 審查 ({ts}) ════════════")
        review_model = select_model(cfg, "review", 0)
        cmd = build_cmd(cfg, review_model, build_gate_prompt(cfg, fw, plan_md, req))
        rc, killed = run_agent(cmd, cfg)
        if killed:
            hb(f"  Round B 被 watchdog 中斷（{killed}），本 cycle 視為無進展。")
            git_guard(cfg, i, log_both)
            gate = None
        else:
            git_guard(cfg, i, log_both)
            gate = get_val(plan_md, "plan_gate_last")

        stable = (not changed) and (gate == "PASS")
        stable_rounds = as_int(get_val(plan_md, "plan_stable_rounds"))
        rounds_since = as_int(get_val(plan_md, "plan_rounds_since_progress"))

        if stable:
            stable_rounds += 1
            rounds_since = 0
            if plan_stuck != 0:
                role_tier = model_tier_label(cfg, "decompose", 0)
                log_both(f"  ↩ 有進展，換回角色預設模型（{role_tier}）。")
            plan_stuck = 0
            set_val(plan_md, "plan_model_tier", model_tier_label(cfg, "decompose", 0))
        else:
            stable_rounds = 0
            rounds_since += 1

        log_both(f"  收斂偵測:本輪改動規劃書={changed} Gate={gate} → "
                 f"plan_stable_rounds={stable_rounds}/{threshold}  無進展計數={rounds_since}")

        if plan_stuck == 0 and rounds_since >= osc["stall_threshold"]:
            plan_stuck = 1
            set_val(plan_md, "plan_stuck_level", str(plan_stuck))
            upgraded_tier = model_tier_label(cfg, "decompose", 1)
            set_val(plan_md, "plan_model_tier", upgraded_tier)
            log_both(f"  ⬆ 規劃書連續 {rounds_since} 個 cycle 無進展 → 升級模型（{upgraded_tier}）。")
        elif plan_stuck >= 1 and rounds_since >= osc["stall_threshold"] + osc["enhanced_max_rounds"]:
            set_plan_human_required(plan_md, True, "plan_not_converging", f"規劃書連續 {rounds_since} 個 cycle 無進展，且已嘗試增強模型，停止交人。", run_id=run_id, source="plan_loop", suggested_action="檢查 PLAN.md、需求與 logs 後再重新規劃。")
            set_val(plan_md, "plan_status", "stuck_human")
            log_both(f"  ⛔ 升級模型仍無進展 → 規劃書交人類裁決,停止。")
            set_val(plan_md, "plan_rounds_since_progress", str(rounds_since))
            return finish("human_required", 2, "plan_not_converging")

        set_val(plan_md, "plan_stable_rounds", str(stable_rounds))
        set_val(plan_md, "plan_rounds_since_progress", str(rounds_since))

        append_round_record(cfg, {
            "run_id": run_id,
            "ts": datetime.now().strftime("%F %T"),
            "type": "round_finished",
            "round": i,
            "loop_type": "plan",
            "phase": "plan",
            "leaf": None,
            "result": gate or "NA",
            "mode": "plan",
            "killed": killed,
            "stuck_level": plan_stuck,
            "rounds_since_progress": rounds_since,
            "enhanced_rounds_used": as_int(get_val(plan_md, "plan_enhanced_rounds_used")),
            "no_activity": 0,
            "consecutive_pass": stable_rounds,
            "progressed": stable,
            "model_tier": tier,
        })
        current_head = git_head()
        append_round_artifact(
            cfg,
            round_no=i,
            loop_type="plan",
            phase="plan",
            changed_files=changed_files_between(git_head_before, current_head),
            git_head_before=git_head_before,
            git_head_after=current_head,
            validation_summary=f"plan gate -> {gate or 'NA'}",
            validation_status=str(gate or "NA").lower(),
            evidence_files=[],
        )

        if stable_rounds >= threshold:
            set_val(plan_md, "plan_status", "converged")
            log_both(f"✅ 規劃書收斂(連續 {threshold} 個 cycle 穩定且 Gate PASS)。PLAN CONVERGED")
            break
        time.sleep(interval)

    if get_val(plan_md, "plan_status") not in ("converged",):
        log_both(f"⛔ 規劃書未在 {max_rounds} 個 cycle 內收斂,請人工檢視 {plan_md} 與 .loop/。")
        set_plan_human_required(plan_md, True, "max_rounds_reached", f"規劃書未在 {max_rounds} 個 cycle 內收斂，達到硬性上限", run_id=run_id, source="plan_loop", suggested_action="檢查 PLAN.md、需求與 logs 後再重新規劃。")
        return finish("human_required", 2, "max_rounds_reached")

    loop_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), "loop.py")
    if mode == "auto":
        hb("\n▶ mode=auto:規劃書已收斂。接續執行請用 run.py（單一入口串接）：")
        hb(f"   python {os.path.join(os.path.dirname(os.path.abspath(__file__)), 'run.py')} --mode auto")
        hb(f"   （或直接跑 python {loop_py}）")
    else:
        hb("\n🧑 mode=gated:規劃書已收斂,停下交人類 review。")
        hb("   review .loop/{loop.config.yaml, CONTROL.md, phases/} 後,執行:")
        hb(f"   python {loop_py}")
    return finish("complete", 0)


# tree planning functions removed


if __name__ == "__main__":
    sys.exit(main())
