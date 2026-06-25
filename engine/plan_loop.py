#!/usr/bin/env python3
"""
plan_loop.py — 階段②：規劃書「生成收斂」迴圈（code1）。

把「產生規劃書」本身當成一個 Loop Engineering 收斂任務:反覆觸發 agent 從
REQUIREMENTS 獨立(重)推導規劃書(loop.config.yaml + CONTROL.md + phases/*.md),
直到**連續 N 輪「無實質變更且 Plan Gate PASS」**才算收斂。

收斂判準(客觀、外部判斷,不靠 agent 自述):
  - 用 git diff 看本輪有沒有改動到「規劃書檔」(.loop/ 下,排除 PLAN.md/log/state)。
  - 結合 agent 回填的 plan_gate_last(PASS/FAIL)。
  - 「無變更 且 PASS」→ plan_stable_rounds++;否則歸零。達門檻 → 規劃書收斂。

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
import loop as L  # noqa: E402  共用 load_config / run_agent / build_cmd / git 等


PLAN_SEED = """# 📐 PLAN — 規劃書生成控制（階段②，由 plan_loop.py 驅動）

> 文件即狀態:記錄「規劃書」收斂進度。規劃書本體在 .loop/{{loop.config.yaml, CONTROL.md, phases/}}。
> 收斂 = 連續 plan_converge_threshold 輪「無實質變更且 Plan Gate PASS」。

```yaml
plan_status: drafting          # drafting / converged
plan_stable_rounds: 0          # 連續「無實質變更且 Gate PASS」輪數
plan_gate_last:                # PASS / FAIL（agent 每輪回填）
plan_changed_last:             # true / false（agent 每輪回填:本輪是否實質改動規劃書）
plan_version: 1
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
    """本輪 git 改動是否觸及『規劃書檔』(.loop/ 下,排除 PLAN/log/state)。"""
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


def build_prompt(cfg, fw, plan_md):
    return (
        "你正在執行 Loop Engineering 的【階段②:生成規劃書】,目標是讓『規劃書』收斂。\n"
        f"讀 .loop/REQUIREMENTS.md + 框架 rules({fw}/rules/ 的 BLUEPRINT、context-budget、"
        "state-model、convergence、completeness)。\n"
        f"依 {fw}/generators/1-plan-generator.md:(重新)獨立推導並產出/精修 "
        ".loop/loop.config.yaml + .loop/CONTROL.md + .loop/phases/*.md。\n"
        "這是收斂迴圈:若已存在規劃書,請『先不看舊版、從 REQUIREMENTS 獨立重推一份』再與現有比對;\n"
        "  僅在有『實質差異』時才修改檔案;無實質差異就不要動檔。\n"
        f"接著依 {fw}/generators/2-plan-review-gate.md 自我檢查 Plan Gate。\n"
        f"最後更新 {plan_md} 的兩個欄位:plan_gate_last(PASS/FAIL)、"
        "plan_changed_last(true=本輪有實質改動 / false=無)。\n"
        "寫檔只允許 .loop/,禁止寫框架。結束 git add -A && git commit(工作區)。"
    )


def main():
    ap = argparse.ArgumentParser(description="階段②:規劃書生成收斂迴圈")
    ap.add_argument("--mode", choices=["gated", "auto"], default=None,
                    help="覆蓋 config.generation.mode")
    args = ap.parse_args()

    cfg = L.load_config()
    gen = cfg.get("generation") or {}
    threshold = gen.get("plan_converge_threshold", 2)
    max_rounds = gen.get("max_rounds", 30)
    interval = gen.get("interval_seconds", 10)
    mode = args.mode or gen.get("mode", "gated")
    fw = cfg["framework_path"]

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

    plan_md = plan_md_path(cfg)
    if seed_plan(plan_md):
        hb(f"+ 建立生成控制檔 {plan_md}")

    req = os.path.join(os.path.dirname(cfg["control"]) or ".", "REQUIREMENTS.md")
    if not os.path.exists(req):
        hb(f"⚠️  找不到 {req}。請先完成階段①(需求訪談或人類提供需求文件)。")
        return 1
    if not L.in_git_repo():
        hb("⚠️  當前目錄不是 git repo,建議先 git init(收斂偵測靠 git diff 最準)。")

    log_both(f"\n########## PLAN LOOP 啟動 {datetime.now():%F %T}  mode={mode} ##########")
    hb(f"規劃書生成迴圈啟動。框架={fw}  詳細輸出:{log_path}（tail -f 觀看）\n")

    model = cfg["models"]["default"]
    for i in range(1, max_rounds + 1):
        L.rotate_log_if_needed(cfg)
        if L.get_val(plan_md, "plan_status") == "converged":
            break

        prompt = build_prompt(cfg, fw, plan_md)
        cmd = L.build_cmd(cfg, model, prompt)
        ts = datetime.now().strftime("%F %T")
        hb(f"▶ Plan Round {i} 開始 ({ts})")
        log_both(f"\n════════════ Plan Round {i} ({ts}) ════════════")

        rc, killed = L.run_agent(cmd, cfg)
        if killed:
            hb(f"  Plan Round {i} 被 watchdog 中斷（{killed}），重跑下一輪。")
            L.git_guard(cfg, i, log_both)
            time.sleep(interval)
            continue
        hb(f"  Plan Round {i} 結束 (rc={rc})")
        L.git_guard(cfg, i, log_both)

        changed = plan_files_changed(cfg)
        if changed is None:  # 無 git → 用 agent 回填
            changed = (L.get_val(plan_md, "plan_changed_last") == "true")
        gate = L.get_val(plan_md, "plan_gate_last")
        stable = (not changed) and (gate == "PASS")

        stable_rounds = L.as_int(L.get_val(plan_md, "plan_stable_rounds"))
        stable_rounds = stable_rounds + 1 if stable else 0
        L.set_val(plan_md, "plan_stable_rounds", str(stable_rounds))
        log_both(f"  收斂偵測:本輪改動規劃書={changed} Gate={gate} → plan_stable_rounds={stable_rounds}/{threshold}")

        if stable_rounds >= threshold:
            L.set_val(plan_md, "plan_status", "converged")
            log_both(f"✅ 規劃書收斂(連續 {threshold} 輪穩定且 Gate PASS)。PLAN CONVERGED")
            break
        time.sleep(interval)

    if L.get_val(plan_md, "plan_status") != "converged":
        log_both(f"⛔ 規劃書未在 {max_rounds} 輪內收斂,請人工檢視 {plan_md} 與 .loop/。")
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
