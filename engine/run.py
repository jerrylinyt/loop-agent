#!/usr/bin/env python3
"""
run.py — 單一入口,串接「階段②生成」與「階段③執行」兩支引擎,提供兩種模式。

模式（--mode，預設取自 config.generation.mode）:
  gated（建議）: 跑 plan_loop.py 讓規劃書收斂 → 停下,交人類 review → 人類確認後再跑執行。
  auto       : 跑 plan_loop.py 收斂 → 自動接 loop.py 執行,直到最終結果收斂。

階段控制（--stage）:
  all（預設）: 依 mode 跑(gated 只到生成收斂;auto 一路到執行收斂)。
  plan       : 只跑階段②(plan_loop.py)。
  execute    : 只跑階段③(loop.py)。← gated 模式下人類 review 完用這個。

用法（在 code repo 根目錄執行）:
  python <framework_path>/engine/run.py                 # 依 config.generation.mode
  python <framework_path>/engine/run.py --mode auto      # 全自動:生成→執行
  python <framework_path>/engine/run.py --stage plan     # 只生成規劃書
  python <framework_path>/engine/run.py --stage execute  # 只執行(review 後)
"""

import os
import sys
import argparse
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import loop as L  # noqa: E402


def run_plan(mode):
    return subprocess.call([sys.executable, os.path.join(HERE, "plan_loop.py"), "--mode", mode])


def run_exec():
    return subprocess.call([sys.executable, os.path.join(HERE, "loop.py")])


def main():
    cfg = L.load_config()
    default_mode = (cfg.get("generation") or {}).get("mode", "gated")

    ap = argparse.ArgumentParser(description="Loop Engineering 入口（生成 + 執行）")
    ap.add_argument("--mode", choices=["gated", "auto"], default=default_mode)
    ap.add_argument("--stage", choices=["all", "plan", "execute"], default="all")
    args = ap.parse_args()

    if args.stage == "plan":
        return run_plan("gated")        # 只生成:不論 mode 都不接執行
    if args.stage == "execute":
        return run_exec()

    # stage=all
    if args.mode == "auto":
        # plan_loop 在 auto 下會自己接 loop.py;這裡用 gated 跑生成再由本檔接,語意更清楚且單一處串接
        rc = run_plan("gated")
        if rc != 0:
            print("⛔ 規劃書未收斂,停止(不進入執行)。")
            return rc
        print("\n▶ mode=auto:規劃書已收斂 → 接續執行迴圈。")
        return run_exec()

    # gated
    rc = run_plan("gated")
    if rc != 0:
        return rc
    print("\n🧑 mode=gated:規劃書已收斂,停下交人類 review。")
    print("   review .loop/{loop.config.yaml, CONTROL.md, phases/} 後,執行:")
    print(f"   python {os.path.join(HERE, 'run.py')} --stage execute")
    return 0


if __name__ == "__main__":
    sys.exit(main())
