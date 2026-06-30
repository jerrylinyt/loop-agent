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
from tree import (
    tree_enabled, tree_md_path, seed_tree,
    get_node, set_node_field, next_pending_node, tree_planning_complete,
    seed_decomp_file, decomp_file_path, read_proposed_children,
    finalize_node_children, check_leaf_min_unit, tree_summary,
    list_leaves, list_by_state, format_tree_for_human,
    check_depth_breaker, check_leaves_breaker,
    PENDING, DECOMPOSED, LEAF,
)
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
        if tree_enabled(cfg):
            return _run_tree_plan_locked(cfg, mode_override, lock_path)
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
        gen_model = select_model(cfg, "decompose", plan_stuck)
        tier = model_tier_label(cfg, "decompose", plan_stuck)

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


# ─────────────── 樹模式：漸進拆解迴圈 ───────────────

def _build_tree_decompose_prompt(cfg, fw, node_id, decomp_path, requirements):
    tpl = cfg["agent"]["prompts"]["tree_decompose"]
    mu = cfg.get("min_unit", {})
    return fmt_prompt(tpl, framework=fw, node_id=node_id,
                      decomp_file=decomp_path, requirements=requirements,
                      max_files=str(mu.get("max_files", 3)),
                      max_lines=str(mu.get("max_lines", 150)))


def _build_tree_gate_prompt(cfg, fw, node_id, decomp_path, requirements):
    tpl = cfg["agent"]["prompts"]["tree_decompose_gate"]
    mu = cfg.get("min_unit", {})
    return fmt_prompt(tpl, framework=fw, node_id=node_id,
                      decomp_file=decomp_path, requirements=requirements,
                      max_files=str(mu.get("max_files", 3)),
                      max_lines=str(mu.get("max_lines", 150)))


def _run_tree_plan_locked(cfg, mode_override, lock_path=None):
    """樹模式規劃迴圈：每 cycle 只拆一個 PENDING 節點。"""
    repo_basename = os.path.basename(os.path.normpath(cfg["repo"]))
    ws_name = cfg["workspace"]
    start_epoch = int(time.time())
    run_id = f"{repo_basename}:{ws_name}:{start_epoch}"

    gen = cfg.get("generation") or {}
    threshold = gen.get("plan_converge_threshold", 2)
    max_rounds = gen.get("max_rounds", 30)
    interval = gen.get("interval_seconds", 10)
    mode = mode_override or gen.get("mode", "gated")
    fw = cfg["framework_path"]
    osc = cfg["oscillation"]

    # ── 硬 BREAKER 旋鈕（Chunk 7）：撞線即凍結交人，程式不准自我放寬 ──
    breaker = cfg.get("breaker", {})
    brk_max_depth = breaker.get("max_depth", 5)
    brk_max_leaves = breaker.get("max_leaves", 1000)
    brk_growth_stall = breaker.get("growth_stall_rounds", 6)

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

    tree_path = tree_md_path(cfg)
    req = os.path.join(os.path.dirname(cfg["control"]) or ".", "REQUIREMENTS.md")

    log_both(f"\n########## TREE PLAN LOOP 啟動 {datetime.now():%F %T}  mode={mode} ##########")
    hb(f"樹模式規劃迴圈啟動。框架={fw}  詳細輸出:{log_path}\n")

    # 卡住偵測（per-node，跨 cycle 持續追蹤同一節點）
    current_target = None
    rounds_since_progress = 0
    node_stuck_level = 0
    # 全樹級生長停滯偵測（Chunk 7 BREAKER）
    growth_stall_count = 0
    prev_decomposed_count = len(list_by_state(tree_path, DECOMPOSED))

    plan_md = plan_md_path(cfg)
    for i in range(1, max_rounds + 1):
        if check_stop_requested(cfg, log_both):
            return finish("stopped", 1)
        rotate_log_if_needed(cfg)
        if lock_path:
            touch_run_lock(lock_path)
        sync_framework_docs(cfg, log_both)
        if get_val(plan_md, "plan_human_required") == "true":
            log_both("🧑‍⚖️ plan_human_required=true：已停下交人類裁決規劃書，loop 停止。")
            return finish("human_required", 2, "plan_not_converging")

        # ── 選目標節點 ──
        target = next_pending_node(tree_path)
        if target is None:
            if tree_planning_complete(tree_path):
                summary = tree_summary(tree_path)
                log_both(f"✅ 樹規劃完成：{summary.get('total_nodes', 0)} 節點、"
                         f"{summary.get('total_leaves', 0)} 葉子、深度 {summary.get('max_depth', 0)}。")
                # min_unit proxy 檢查（warning，不 block——proxy 不精確，真正把關在人類 gate）
                all_violations = []
                for leaf_id in list_leaves(tree_path):
                    dp = decomp_file_path(cfg, leaf_id)
                    if os.path.exists(dp):
                        vs = check_leaf_min_unit(dp, cfg)
                        all_violations.extend(vs)
                    # 葉子本身可能來自父的 decomp，也檢查父的
                    node = get_node(tree_path, leaf_id)
                    if node and node["parent"]:
                        pdp = decomp_file_path(cfg, node["parent"])
                        if os.path.exists(pdp):
                            vs = check_leaf_min_unit(pdp, cfg)
                            for v in vs:
                                if v == leaf_id and v not in all_violations:
                                    all_violations.append(v)
                if all_violations:
                    log_both(f"  ⚠️ min_unit proxy 超標的葉子：{', '.join(all_violations)}"
                             f"（建議人類 gate 時特別檢視）")
                break
            log_both("⚠️ 無 PENDING 節點但樹未完成（異常狀態），停止。")
            return finish("stopped", 1)

        # 換了目標節點 → 重置 per-node 卡住計數
        if target != current_target:
            current_target = target
            rounds_since_progress = 0
            node_stuck_level = 0

        node = get_node(tree_path, target)
        decomp_path = seed_decomp_file(cfg, target)
        prev_children = read_proposed_children(decomp_path)

        # ── Round A：拆解（角色=decompose） ──
        gen_model = select_model(cfg, "decompose", node_stuck_level)
        tier = model_tier_label(cfg, "decompose", node_stuck_level)
        ts = datetime.now().strftime("%F %T")
        hb(f"▶ Tree Cycle {i} · 節點 [{target}] · Round A 拆解 ({ts})  tier={tier}")
        log_both(f"\n════════════ Tree Cycle {i} · [{target}] Round A 拆解 ({ts}) tier={tier} ════════════")

        cmd = build_cmd(cfg, gen_model,
                        _build_tree_decompose_prompt(cfg, fw, target, decomp_path, req))
        rc, killed = run_agent(cmd, cfg)
        if killed:
            append_round_record(cfg, {
                "run_id": run_id,
                "ts": datetime.now().strftime("%F %T"),
                "type": "round_finished",
                "round": i,
                "loop_type": "plan",
                "phase": "plan",
                "leaf": target,
                "result": "NA",
                "mode": "plan",
                "killed": killed,
                "stuck_level": node_stuck_level,
                "rounds_since_progress": rounds_since_progress + 1,
                "enhanced_rounds_used": 0,
                "no_activity": 1,
                "consecutive_pass": 0,
                "progressed": False,
                "model_tier": tier,
            })
            hb(f"  Round A 被 watchdog 中斷（{killed}），清理後重跑。")
            git_guard(cfg, i, log_both)
            time.sleep(interval)
            continue
        git_guard(cfg, i, log_both)

        # ── Round B：審查（角色=review） ──
        review_model = select_model(cfg, "review", 0)
        ts = datetime.now().strftime("%F %T")
        hb(f"▶ Tree Cycle {i} · 節點 [{target}] · Round B 審查 ({ts})")
        log_both(f"\n════════════ Tree Cycle {i} · [{target}] Round B 審查 ({ts}) ════════════")

        cmd = build_cmd(cfg, review_model,
                        _build_tree_gate_prompt(cfg, fw, target, decomp_path, req))
        rc, killed = run_agent(cmd, cfg)
        if killed:
            hb(f"  Round B 被 watchdog 中斷（{killed}），本 cycle 視為無進展。")
            git_guard(cfg, i, log_both)
            gate = None
        else:
            git_guard(cfg, i, log_both)
            gate = get_val(decomp_path, "decomp_gate_last")

        # ── 收斂判定 ──
        cur_children = read_proposed_children(decomp_path)
        changed = (cur_children != prev_children)
        stable = (not changed) and (gate == "PASS")

        node_stable = get_node(tree_path, target)
        node_stable_rounds = node_stable["stable_rounds"] if node_stable else 0

        if stable:
            node_stable_rounds += 1
            rounds_since_progress = 0
            if node_stuck_level != 0:
                role_tier = model_tier_label(cfg, "decompose", 0)
                log_both(f"  ↩ 有進展，換回角色預設模型（{role_tier}）。")
                node_stuck_level = 0
        else:
            node_stable_rounds = 0
            rounds_since_progress += 1

        # ⚠️ 集合穩定 ≠ 正確：穩定只代表弱模型連續 N 輪提出相同子項，
        # 可能是真收斂也可能是沒梗。正確性由 Chunk 4 人類 gate 承接。
        set_node_field(tree_path, target, "stable_rounds", str(node_stable_rounds))

        log_both(f"  收斂偵測：children_changed={changed} gate={gate} → "
                 f"node_stable_rounds={node_stable_rounds}/{threshold}  無進展={rounds_since_progress}")

        # ── 節點收斂 → 定案子節點 ──
        if node_stable_rounds >= threshold:
            created = finalize_node_children(tree_path, cfg, target)
            set_node_field(tree_path, target, "state", DECOMPOSED)
            pending_count = sum(1 for c in created
                                if get_node(tree_path, c) and get_node(tree_path, c)["state"] == PENDING)
            leaf_count = len(created) - pending_count
            log_both(f"  ✅ 節點 [{target}] 拆解收斂 → {len(created)} 子節點"
                     f"（{leaf_count} LEAF + {pending_count} PENDING）")

            # ── 硬 BREAKER：max_depth（Chunk 7）──
            depth_violations = check_depth_breaker(tree_path, brk_max_depth)
            if depth_violations:
                log_both(f"  ⛔ 拆解深度超限（max_depth={brk_max_depth}）→ 凍結交人。"
                         f" 超標節點：{', '.join(depth_violations)}")
                set_plan_human_required(plan_md, True, "tree_structure_error", f"拆解深度超限（max_depth={brk_max_depth}）。超標節點：{', '.join(depth_violations)}", run_id=run_id, source="plan_loop", suggested_action="先調整樹分解策略與限制，再重新規劃。")
                return finish("human_required", 2, "tree_structure_error")

            # ── 硬 BREAKER：max_leaves（Chunk 7）──
            # 刻意設大——明顯壞掉才觸發的跳閘，非壓樹目標
            leaf_count_total, exceeded = check_leaves_breaker(tree_path, brk_max_leaves)
            if exceeded:
                log_both(f"  ⛔ 葉子總數超限（{leaf_count_total} > max_leaves={brk_max_leaves}）→ 凍結交人。")
                set_plan_human_required(plan_md, True, "tree_structure_error", f"葉子總數超限（{leaf_count_total} > max_leaves={brk_max_leaves}）", run_id=run_id, source="plan_loop", suggested_action="先調整樹分解策略與限制，再重新規劃。")
                return finish("human_required", 2, "tree_structure_error")

            # 生長停滯歸零（有節點成功拆解 = 有進展）
            growth_stall_count = 0

            # 重置 per-node 追蹤
            current_target = None
            rounds_since_progress = 0
            node_stuck_level = 0

        # ── 卡住升級（沿用既有 stuck_level 階梯：0→1→2→人類） ──
        elif node_stuck_level == 0 and rounds_since_progress >= osc["stall_threshold"]:
            node_stuck_level = 1
            upgraded_tier = model_tier_label(cfg, "decompose", 1)
            log_both(f"  ⬆ 節點 [{target}] 連續 {rounds_since_progress} cycle 無進展 → 升級模型（{upgraded_tier}）。")
        elif node_stuck_level >= 1 and rounds_since_progress >= osc["stall_threshold"] + osc["enhanced_max_rounds"]:
            log_both(f"  ⛔ 節點 [{target}] 升級模型仍無進展 → 交人類裁決。")
            set_plan_human_required(plan_md, True, "plan_not_converging", f"節點 [{target}] 升級模型仍無進展", run_id=run_id, source="plan_loop", suggested_action="檢查該節點需求與拆解策略後再重新規劃。")
            return finish("human_required", 2, "plan_not_converging")

        # ── 硬 BREAKER：growth_stall_rounds（Chunk 7）──
        # 全樹級偵測：連續 N 個 cycle 沒有任何節點從 PENDING → DECOMPOSED/LEAF
        cur_decomposed_count = len(list_by_state(tree_path, DECOMPOSED))
        if cur_decomposed_count == prev_decomposed_count:
            growth_stall_count += 1
        else:
            growth_stall_count = 0
            prev_decomposed_count = cur_decomposed_count
        if growth_stall_count >= brk_growth_stall:
            log_both(f"  ⛔ 樹生長停滯（連續 {growth_stall_count} cycle 無拆解進展，"
                     f"growth_stall_rounds={brk_growth_stall}）→ 凍結交人。")
            set_plan_human_required(plan_md, True, "tree_growth_stalled", f"樹生長停滯（連續 {growth_stall_count} cycle 無拆解進展）", run_id=run_id, source="plan_loop", suggested_action="檢查樹分解策略與需求缺口後再重新規劃。")
            return finish("human_required", 2, "tree_growth_stalled")

        append_round_record(cfg, {
            "run_id": run_id,
            "ts": datetime.now().strftime("%F %T"),
            "type": "round_finished",
            "round": i,
            "loop_type": "plan",
            "phase": "plan",
            "leaf": target,
            "result": gate or "NA",
            "mode": "plan",
            "killed": killed,
            "stuck_level": node_stuck_level,
            "rounds_since_progress": rounds_since_progress,
            "enhanced_rounds_used": 0,
            "no_activity": 0,
            "consecutive_pass": node_stable_rounds,
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
            validation_summary=f"tree gate -> {gate or 'NA'}",
            validation_status=str(gate or "NA").lower(),
            evidence_files=[],
            leaf=target,
        )

        time.sleep(interval)

    # ── 完成後的出口 ──
    if not tree_planning_complete(tree_path):
        log_both(f"⛔ 樹規劃未在 {max_rounds} cycle 內完成，請人工檢視。")
        set_plan_human_required(plan_md, True, "max_rounds_reached", f"樹規劃未在 {max_rounds} cycle 內完成", run_id=run_id, source="plan_loop", suggested_action="檢查樹規劃與需求缺口後再重新規劃。")
        return finish("human_required", 2, "max_rounds_reached")

    loop_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), "loop.py")
    if mode == "auto":
        hb("\n▶ mode=auto：樹規劃已完成。接續執行請用 run.py：")
        hb(f"   python {os.path.join(os.path.dirname(os.path.abspath(__file__)), 'run.py')} --mode auto")
    else:
        hb("\n🧑 mode=gated：樹規劃已完成，停下交人類 review 整棵樹。")
        hb("   收斂只代表「穩定」，正確性由您驗收。\n")
        hb("── 整棵拆解樹 ──")
        hb(format_tree_for_human(tree_path))
        hb("")
        hb("   review .loop/TREE.md + .loop/tree/*.decomp.md 後：")
        hb(f"   ✅ 通過 → python {loop_py}")
        ws = cfg.get("_workspace", "default")
        ws_flag = f" --workspace {ws}" if ws != "default" else ""
        run_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), "run.py")
        hb(f"   ❌ 局部重拆 → python {run_py} --stage reject --subtree <node_id>{ws_flag}")
    return finish("complete", 0)


if __name__ == "__main__":
    sys.exit(main())
