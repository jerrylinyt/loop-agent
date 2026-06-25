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
"""

import os
import sys
import argparse
import subprocess

# 把當前目錄加進 sys.path 以便 import .utils 和 .config
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from utils import add_common_args, apply_quiet_flag, resolve_workspace
from config import load_config


def run_plan(mode: str) -> int:
    return subprocess.call([sys.executable, os.path.join(HERE, "plan_loop.py"), "--mode", mode])


def run_exec() -> int:
    return subprocess.call([sys.executable, os.path.join(HERE, "loop.py")])


def main():
    ap = argparse.ArgumentParser(description="Loop Engineering 入口（生成 + 執行）")
    ap.add_argument("--mode", choices=["gated", "auto"], default=None,
                    help="預設取自 config.generation.mode")
    ap.add_argument("--stage", choices=["all", "plan", "execute"], default="all")
    add_common_args(ap)
    args = ap.parse_args()

    # 先解析 workspace/quiet 並寫入 os.environ —— 下面 spawn 的子程序(plan_loop.py/loop.py)
    # 會自動繼承這個行程的環境變數,藉此把同一個 workspace 帶過去,不需在 argv 額外傳遞。
    apply_quiet_flag(args.quiet)
    ws = resolve_workspace(args.workspace)

    cfg = load_config()
    cfg["_workspace"] = ws
    if args.mode is None:
        args.mode = (cfg.get("generation") or {}).get("mode", "gated")

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
    ws_dir = os.path.dirname(os.environ.get("LOOP_CONFIG", ".loop/default/loop.config.yaml"))
    ws_flag = f" --workspace {ws}" if ws != "default" else ""
    print("\n🧑 mode=gated:規劃書已收斂,停下交人類 review。")
    print(f"   review {ws_dir}/{{loop.config.yaml, CONTROL.md, phases/}} 後,執行:")
    print(f"   python {os.path.join(HERE, 'run.py')} --stage execute{ws_flag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
