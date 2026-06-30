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
  reset-execute-state : 保留規劃書,重置執行狀態,可指定從 phase/task 開始。
"""

import glob
import json
import os
import sys
import argparse
import subprocess
from datetime import datetime

# 把當前目錄加進 sys.path 以便 import .utils 和 .config
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from utils import add_common_args, apply_quiet_flag, resolve_workspace, structured_preflight
from config import load_config
from state import load_state_json, save_state_json
# tree imports removed


def run_plan(mode: str) -> int:
    return subprocess.call([sys.executable, os.path.join(HERE, "plan_loop.py"), "--mode", mode])


def run_exec() -> int:
    return subprocess.call([sys.executable, os.path.join(HERE, "loop.py")])


def run_reset_plan(cfg) -> int:
    """重設 planning 狀態並立即重跑 plan_loop。

    清除 state.json 的 plan / phases 欄位，刪除 phases/*.md，
    留下 loop.config.yaml、control 欄位（執行期狀態）、issues 不動，
    然後直接接 run_plan("gated")。
    """
    control = cfg.get("control", "state.json")
    state_path = os.path.abspath(control)
    ws_dir = os.path.dirname(state_path)

    # 重設 state.json
    data = load_state_json(state_path)
    data["plan"] = {}
    data["phases"] = []
    save_state_json(state_path, data)
    print(f"✅ state.json plan/phases 已清除：{state_path}", flush=True)

    # 刪除 phases/*.md
    phases_dir = os.path.join(ws_dir, "phases")
    deleted = []
    for p in glob.glob(os.path.join(phases_dir, "*.md")):
        try:
            os.remove(p)
            deleted.append(os.path.basename(p))
        except OSError as e:
            print(f"⚠️  無法刪除 {p}：{e}", flush=True)
    if deleted:
        print(f"🗑️  已刪除 phases/：{', '.join(deleted)}", flush=True)
    else:
        print("   phases/ 無 .md 檔（或目錄不存在），跳過。", flush=True)

    # 留還原點
    subprocess.call(["git", "add", "-A"])
    subprocess.call(["git", "commit", "-m", "reset: reset plan state for replan"])

    print("\n▶ reset-plan 完成，接續跑規劃迴圈...\n", flush=True)
    return run_plan("gated")


def _phase_index(phases: list[dict], phase_id: str) -> int:
    for idx, phase in enumerate(phases):
        if str(phase.get("id")) == str(phase_id):
            return idx
    raise ValueError(f"phase '{phase_id}' not found in state.json")


def _task_sort_key(task: dict) -> tuple[int, str]:
    try:
        order = int(task.get("order"))
    except (TypeError, ValueError):
        order = 10**9
    return order, str(task.get("id") or "")


def _task_index(tasks: list[dict], task_id: str) -> int:
    ordered = sorted(enumerate(tasks), key=lambda item: _task_sort_key(item[1]))
    for ordered_idx, (_, task) in enumerate(ordered):
        if str(task.get("id")) == str(task_id):
            return ordered_idx
    raise ValueError(f"task '{task_id}' not found in selected phase")


def _reset_task(task: dict) -> None:
    task["status"] = "TODO"
    task["conv"] = 0
    task["last_round"] = None
    task["last_conv_sig"] = ""


def reset_execute_state_data(data: dict, *, phase: str | None = None, task: str | None = None) -> dict:
    """Reset execution progress while preserving generated plan files."""
    phases = data.get("phases") or []
    if not isinstance(phases, list) or not phases:
        raise ValueError("state.json has no phases to reset")

    target_phase = str(phase or phases[0].get("id") or "1")
    start_phase_idx = _phase_index(phases, target_phase)

    task_start_by_phase: dict[str, int] = {}
    if task:
        tasks = phases[start_phase_idx].get("tasks") or []
        if not isinstance(tasks, list):
            raise ValueError(f"phase '{target_phase}' has no task list")
        task_start_by_phase[target_phase] = _task_index(tasks, task)

    data["current_phase"] = target_phase
    control = data.setdefault("control", {})
    control.update({
        "last_round_mode": "",
        "last_round_result": "NA",
        "last_round_fail_tasks": "",
        "rounds_since_progress": 0,
        "stuck_level": 0,
        "current_model_tier": "",
        "enhanced_rounds_used": 0,
        "human_required": False,
        "human_required_code": "",
        "human_required_reason": "",
        "human_required_msg": "",
        "human_required_since": "",
        "suggested_human_action": "",
        "human_required_source": "",
        "human_required_run_id": "",
        "review_invalid_streak": 0,
        "last_task_progress_run_id": "",
        "stop_condition_met": False,
    })

    for idx, phase_obj in enumerate(phases):
        if idx < start_phase_idx:
            continue
        phase_id = str(phase_obj.get("id") or "")
        phase_obj["consecutive_pass"] = 0
        phase_obj["total_validations"] = 0
        phase_obj["last_result"] = ""

        tasks = phase_obj.get("tasks") or []
        if not isinstance(tasks, list):
            continue
        ordered = sorted(enumerate(tasks), key=lambda item: _task_sort_key(item[1]))
        start_task_idx = task_start_by_phase.get(phase_id, 0)
        for ordered_idx, (_, task_obj) in enumerate(ordered):
            if ordered_idx >= start_task_idx:
                _reset_task(task_obj)

    data.setdefault("reset_history", []).append({
        "ts": datetime.now().strftime("%F %T"),
        "type": "execute",
        "phase": target_phase,
        "task": task or "",
    })
    return data


def run_reset_execute(cfg, phase: str | None = None, task: str | None = None) -> int:
    control = cfg.get("control", "state.json")
    state_path = os.path.abspath(control)
    try:
        data = load_state_json(state_path)
        reset_execute_state_data(data, phase=phase, task=task)
        save_state_json(state_path, data)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr, flush=True)
        return 1

    scope = f"phase {data.get('current_phase') or '1'}"
    if task:
        scope += f", task {task}"
    print(f"✅ execute-state reset complete from {scope}: {state_path}", flush=True)
    return 0


# run_reject function removed


def main():
    ap = argparse.ArgumentParser(description="Loop Engineering 入口（生成 + 執行）")
    ap.add_argument("--mode", choices=["gated", "auto"], default=None,
                    help="預設取自 config.generation.mode")
    ap.add_argument("--stage", choices=["all", "plan", "execute", "reset-plan", "reset-execute-state", "reset-execute"], default="all")
    ap.add_argument("--reset-to-phase", default=None,
                    help="reset-execute-state 起點 phase；省略時從第一個 phase 開始全部重置")
    ap.add_argument("--reset-to-task", default=None,
                    help="reset-execute-state 起點 task；需搭配 --reset-to-phase，會重置該 task 以及後續 task")
    ap.add_argument("--preflight", action="store_true", help="只輸出結構化 preflight，不啟動 loop")
    ap.add_argument("--json", action="store_true", help="搭配 --preflight 輸出 JSON")
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

    if args.preflight:
        stage = "execute" if args.stage in ("all", "execute") else "plan"
        result = structured_preflight(cfg, stage, repo_path=os.getcwd(), workspace=ws)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            for check in result["checks"]:
                status = "OK" if check["ok"] else check["severity"].upper()
                print(f"[{status}] {check['id']}: {check['detail']}")
        return 0 if result["ok"] else 1

    if args.stage == "plan":
        return run_plan("gated")        # 只生成:不論 mode 都不接執行
    if args.stage == "execute":
        return run_exec()
    if args.stage == "reset-plan":
        return run_reset_plan(cfg)
    if args.stage in ("reset-execute-state", "reset-execute"):
        if args.reset_to_task and not args.reset_to_phase:
            print("Error: --reset-to-task requires --reset-to-phase", file=sys.stderr)
            return 1
        return run_reset_execute(cfg, phase=args.reset_to_phase, task=args.reset_to_task)

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
    print(f"   review {ws_dir}/{{loop.config.yaml, state.json, phases/}} 後,執行:")

    print(f"   python {os.path.join(HERE, 'run.py')} --stage execute{ws_flag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
