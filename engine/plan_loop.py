#!/usr/bin/env python3
"""
plan_loop.py — 階段②：規劃書「生成收斂」迴圈（code1）。

把「產生規劃書」本身當成一個 Loop Engineering 收斂任務。每個「循環(cycle)」分兩輪：
  Round A（生成）：agent 從 REQUIREMENTS 獨立(重)推導/精修規劃書(loop.config.yaml + CONTROL.md + phases/*.md)。
  Round B（審查，獨立 context）：另一個 agent 呼叫只審不生,跑 Plan Gate,**不得修改規劃書檔**(read-only)。
這比「同一個 agent 自己生、自己審」更符合框架的「獨立驗證」原則(rules/convergence.md)。

收斂判準(客觀、外部判斷,不靠 agent 自述):
  - 用 git diff 看 Round A 有沒有改動到「規劃書檔」(.loop/ 下,排除 PLAN.md/log/state)。
  - 結合 Round B 回填的 plan_gate_last(PASS/FAIL)。
  - 一個 cycle「無變更 且 Gate PASS」→ plan_stable_rounds++;否則歸零。達門檻 → 規劃書收斂。

卡死處理(與 loop.py 對稱,三層:預設→增強→人類):
  - 連續 stall_threshold 個 cycle 無進展(有變更或 Gate FAIL)→ Round A 換【增強模型】重試。
  - 增強模型試滿 enhanced_max_rounds 個 cycle 仍無進展 → 設 plan_human_required,停下交人類
    (不再無聲空轉到 max_rounds)。

兩種模式(config.generation.mode 或 --mode):
  - gated:收斂後停下,印出 review 指示,交人類確認再執行 loop.py。
  - auto :收斂後直接觸發 engine/loop.py(由 run.py 串接;本檔僅負責階段②並回傳收斂與否)。

狀態落在 .loop/PLAN.md(生成控制檔,文件即狀態);詳細輸出 append 到 .loop/plan.log。
引擎共用基礎設施 import 自 loop.py(同目錄)。
"""

import os
import sys
import time
import argparse
import subprocess
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import loop as L  # noqa: E402  共用 load_config / run_agent / build_cmd / git / preflight 等


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
plan_model_tier: default       # default / enhanced
plan_enhanced_rounds_used: 0
plan_human_required: false
```
"""


def plan_md_path(cfg):
    # PLAN.md 與 CONTROL.md 放同一個 .loop/ 目錄
    return os.path.join(os.path.dirname(cfg["control"]) or ".", "PLAN.md")


def seed_plan(path):
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(PLAN_SEED)
        return True
    return False


def plan_files_changed(cfg):
    """Round A 的 git 改動是否觸及『規劃書檔』(.loop/ 下,排除 PLAN/log/state)。"""
    if not L.in_git_repo():
        return None  # 無 git → 交由 agent 回填的 plan_changed_last 判斷
    loop_dir = os.path.dirname(cfg["control"]).replace("\\", "/") or "."
    exclude = ("PLAN.md", "plan.log", "loop.log")
    for c in L.changed_files():
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
    return L.fmt_prompt(tpl, framework=fw, plan_md=plan_md, requirements=requirements, control=cfg["control"])


def build_gate_prompt(cfg, fw, plan_md, requirements):
    tpl = cfg["agent"]["prompts"]["plan_gate"]
    return L.fmt_prompt(tpl, framework=fw, plan_md=plan_md, requirements=requirements, control=cfg["control"])


def main():
    ap = argparse.ArgumentParser(description="階段②:規劃書生成收斂迴圈")
    ap.add_argument("--mode", choices=["gated", "auto"], default=None,
                    help="覆蓋 config.generation.mode")
    L.add_common_args(ap)
    args = ap.parse_args()
    L.apply_quiet_flag(args.quiet)
    ws = L.resolve_workspace(args.workspace)

    cfg = L.load_config()
    cfg["_workspace"] = ws
    rc = _run_plan(cfg, args.mode)
    status = {0: "plan_proceeding", 1: "plan_stopped", 2: "plan_human_required"}.get(rc, "plan_stopped")
    L.update_index(cfg, status)
    return rc


def _run_plan(cfg, mode_override):
    lock_path = os.path.join(cfg["runtime"]["state_dir"], "run.lock")
    try:
        L.acquire_run_lock(lock_path)
    except L.WorkspaceBusy as e:
        print(f"✋ {e}", flush=True)
        return 1
    try:
        return _run_plan_locked(cfg, mode_override)
    finally:
        L.release_run_lock(lock_path)


def _run_plan_locked(cfg, mode_override):
    gen = cfg.get("generation") or {}
    threshold = gen.get("plan_converge_threshold", 2)
    max_rounds = gen.get("max_rounds", 30)
    interval = gen.get("interval_seconds", 10)
    mode = mode_override or gen.get("mode", "gated")
    fw = cfg["framework_path"]
    osc = cfg["oscillation"]  # 沿用同一組門檻(stall_threshold/enhanced_max_rounds)，避免另設一份重複設定

    # 把引擎的 log/rotate 導向 plan.log(階段②專用,不與 loop.log 混)
    cfg["runtime"]["log_file"] = gen.get("log_file", "./.loop/plan.log")
    log_path = cfg["runtime"]["log_file"]
    os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)

    def hb(m=""):
        print(m, flush=True)

    def log_both(m=""):
        hb(m)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(m + "\n")

    if not L.report_preflight(cfg, "plan", log_both):
        return 1

    plan_md = plan_md_path(cfg)
    if seed_plan(plan_md):
        hb(f"+ 建立生成控制檔 {plan_md}")

    req = os.path.join(os.path.dirname(cfg["control"]) or ".", "REQUIREMENTS.md")
    log_both(f"\n########## PLAN LOOP 啟動 {datetime.now():%F %T}  mode={mode} ##########")
    hb(f"規劃書生成迴圈啟動。框架={fw}  詳細輸出:{log_path}（tail -f 觀看）\n")

    models = cfg["agent"]["models"]
    for i in range(1, max_rounds + 1):
        L.rotate_log_if_needed(cfg)
        if L.get_val(plan_md, "plan_status") == "converged":
            break
        if L.get_val(plan_md, "plan_human_required") == "true":
            log_both("🧑‍⚖️ plan_human_required=true：已停下交人類裁決規劃書，loop 停止。")
            return 2

        tier = L.get_val(plan_md, "plan_model_tier") or "default"
        gen_model = models["enhanced"] if tier == "enhanced" else models["default"]

        # ── Round A：生成（用當前模型階層）──
        ts = datetime.now().strftime("%F %T")
        hb(f"▶ Plan Cycle {i} · Round A 生成 開始 ({ts})  模型階層={tier}")
        log_both(f"\n════════════ Plan Cycle {i} · Round A 生成 ({ts}) tier={tier} ════════════")
        cmd = L.build_cmd(cfg, gen_model, build_gen_prompt(cfg, fw, plan_md, req))
        rc, killed = L.run_agent(cmd, cfg)
        if killed:
            hb(f"  Round A 被 watchdog 中斷（{killed}），清理後重跑下一個 cycle。")
            L.with_git_lock(cfg, L.git_guard, cfg, i, log_both)
            time.sleep(interval)
            continue
        L.with_git_lock(cfg, L.git_guard, cfg, i, log_both)

        changed = plan_files_changed(cfg)
        if changed is None:  # 無 git → 用 agent 回填
            changed = (L.get_val(plan_md, "plan_changed_last") == "true")

        # ── Round B：獨立審查（永遠用預設模型；只審不生，避免汙染收斂判準）──
        ts = datetime.now().strftime("%F %T")
        hb(f"▶ Plan Cycle {i} · Round B 審查(獨立) 開始 ({ts})")
        log_both(f"\n════════════ Plan Cycle {i} · Round B 審查 ({ts}) ════════════")
        cmd = L.build_cmd(cfg, models["default"], build_gate_prompt(cfg, fw, plan_md, req))
        rc, killed = L.run_agent(cmd, cfg)
        if killed:
            hb(f"  Round B 被 watchdog 中斷（{killed}），本 cycle 視為無進展。")
            L.with_git_lock(cfg, L.git_guard, cfg, i, log_both)
            gate = None
        else:
            L.with_git_lock(cfg, L.git_guard, cfg, i, log_both)
            gate = L.get_val(plan_md, "plan_gate_last")

        stable = (not changed) and (gate == "PASS")
        stable_rounds = L.as_int(L.get_val(plan_md, "plan_stable_rounds"))
        rounds_since = L.as_int(L.get_val(plan_md, "plan_rounds_since_progress"))
        enhanced_used = L.as_int(L.get_val(plan_md, "plan_enhanced_rounds_used"))

        if stable:
            stable_rounds += 1
            rounds_since = 0
            if tier != "default":
                log_both("  ↩ 有進展，換回預設模型。")
            L.set_val(plan_md, "plan_model_tier", "default")
            enhanced_used = 0
        else:
            stable_rounds = 0
            rounds_since += 1
            if tier == "enhanced":
                enhanced_used += 1

        log_both(f"  收斂偵測:本輪改動規劃書={changed} Gate={gate} → "
                 f"plan_stable_rounds={stable_rounds}/{threshold}  無進展計數={rounds_since}")

        # ── 卡死升級（三層:預設→增強→人類,對稱 loop.py） ──
        if tier == "default" and rounds_since >= osc["stall_threshold"]:
            L.set_val(plan_md, "plan_model_tier", "enhanced")
            enhanced_used = 0
            log_both(f"  ⬆ 規劃書連續 {rounds_since} 個 cycle 無進展 → Round A 換【增強模型】重試。")
        elif tier == "enhanced" and enhanced_used >= osc["enhanced_max_rounds"]:
            L.set_val(plan_md, "plan_human_required", "true")
            L.set_val(plan_md, "plan_status", "stuck_human")
            log_both(f"  ⛔ 增強模型試了 {enhanced_used} 個 cycle 仍無進展 → 規劃書交人類裁決,停止。")
            L.set_val(plan_md, "plan_rounds_since_progress", str(rounds_since))
            L.set_val(plan_md, "plan_enhanced_rounds_used", str(enhanced_used))
            return 2

        L.set_val(plan_md, "plan_stable_rounds", str(stable_rounds))
        L.set_val(plan_md, "plan_rounds_since_progress", str(rounds_since))
        L.set_val(plan_md, "plan_enhanced_rounds_used", str(enhanced_used))

        if stable_rounds >= threshold:
            L.set_val(plan_md, "plan_status", "converged")
            log_both(f"✅ 規劃書收斂(連續 {threshold} 個 cycle 穩定且 Gate PASS)。PLAN CONVERGED")
            break
        time.sleep(interval)

    if L.get_val(plan_md, "plan_status") not in ("converged",):
        log_both(f"⛔ 規劃書未在 {max_rounds} 個 cycle 內收斂,請人工檢視 {plan_md} 與 .loop/。")
        return 1

    if mode == "auto":
        hb("\n▶ mode=auto:規劃書已收斂,接續執行迴圈(loop.py)…")
        loop_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), "loop.py")
        return subprocess.call([sys.executable, loop_py])

    hb("\n🧑 mode=gated:規劃書已收斂,停下交人類 review。")
    hb("   review .loop/{loop.config.yaml, CONTROL.md, phases/} 後,執行:")
    hb(f"   python {os.path.join(os.path.dirname(os.path.abspath(__file__)), 'loop.py')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
