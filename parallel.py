#!/usr/bin/env python3
"""
parallel.py — Loop Engineering 並行多工輔助工具。

此工具使用 `git worktree` 機制讓同一個 repository 可以同時執行多個獨立的 loop 任務。
每個 worktree 具有獨立的工作目錄與分支，各自使用獨立的 workspace 鎖，防範修改衝突。

支援子指令：
  - add    : 建立新並行工作區 (git worktree) 並初始化 workspace
  - list   : 列出目前專案的所有並行工作區及其實時執行狀態
  - remove : 安全移除不再使用的並行工作區 (git worktree)
"""

import os
import sys
import re
import time
import shutil
import argparse
import subprocess
from datetime import datetime

try:
    # Windows 主控台 cp950 → 強制 UTF-8 輸出
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

FRAMEWORK = os.path.dirname(os.path.abspath(__file__))


def parse_control_file(control_path: str) -> tuple[str, str]:
    """????????? current_phase ? stuck_level ??"""
    if not os.path.exists(control_path):
        return "-", "-"
    try:
        import json
        with open(control_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        current_phase = str(data.get("current_phase", "-"))
        stuck_level = str(data.get("control", {}).get("stuck_level", "-"))
        return current_phase, stuck_level
    except Exception:
        return "-", "-"

def get_worktrees() -> list[dict]:
    """呼叫 git worktree list --porcelain 並解析"""
    res = subprocess.run(["git", "worktree", "list", "--porcelain"], capture_output=True, text=True, encoding="utf-8")
    if res.returncode != 0:
        print("❌ 錯誤：無法取得 git worktree 列表。")
        print(res.stderr)
        sys.exit(1)

    worktrees = []
    current_wt = {}
    for line in res.stdout.splitlines():
        line = line.strip()
        if not line:
            if current_wt:
                worktrees.append(current_wt)
                current_wt = {}
            continue
        parts = line.split(" ", 1)
        key = parts[0]
        value = parts[1] if len(parts) > 1 else ""
        if key == "worktree":
            if current_wt:
                worktrees.append(current_wt)
            current_wt = {"path": value, "head": None, "branch": None}
        elif key == "HEAD":
            current_wt["head"] = value
        elif key == "branch":
            branch = value
            if branch.startswith("refs/heads/"):
                branch = branch[len("refs/heads/"):]
            current_wt["branch"] = branch
    if current_wt:
        worktrees.append(current_wt)
    return worktrees


def cmd_add(args) -> int:
    branch = args.branch
    sanitized_branch = branch.replace("/", "-")

    # 1. 計算 worktree 路徑
    if args.path:
        target_path = os.path.abspath(os.path.expanduser(args.path))
    else:
        # 預設為同層 sibling 目錄
        # 先取得目前 repo 的 basename
        res = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, encoding="utf-8")
        if res.returncode != 0:
            print("❌ 錯誤：當前工作目錄不是 git 工作區。")
            return 1
        repo_root = os.path.abspath(res.stdout.strip())
        repo_name = os.path.basename(repo_root)
        parent_dir = os.path.dirname(repo_root)
        target_path = os.path.join(parent_dir, f"{repo_name}-{sanitized_branch}")

    # 邊界條件：路徑已存在且非空
    if os.path.exists(target_path):
        if os.path.isdir(target_path) and os.listdir(target_path):
            print(f"❌ 錯誤：目標工作區目錄已存在且不為空：{target_path}")
            return 1

    # 2. 判斷 branch 是否已存在
    res_chk = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"],
        capture_output=True, text=True, encoding="utf-8"
    )
    branch_exists = (res_chk.returncode == 0)

    # 執行 git worktree add
    if not branch_exists:
        cmd = ["git", "worktree", "add", target_path, "-b", branch]
        if args.base:
            cmd.append(args.base)
        print(f"~ 正在建立分支「{branch}」並掛載新 worktree 至：{target_path}")
    else:
        cmd = ["git", "worktree", "add", target_path, branch]
        print(f"~ 正在切換既有分支「{branch}」並掛載至新 worktree：{target_path}")

    res_wt = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if res_wt.returncode != 0:
        print("❌ 錯誤：建立 git worktree 失敗。")
        print(res_wt.stderr)
        return 1

    # 3. 建立 workspace 名字，並呼叫 init-project.py
    ws_name = args.name if args.name else sanitized_branch
    print(f"~ 正在初始化 workspace「{ws_name}」...")
    init_script = os.path.join(FRAMEWORK, "init-project.py")
    res_init = subprocess.run(
        [sys.executable, init_script, target_path, "--name", ws_name],
        capture_output=True, text=True, encoding="utf-8"
    )
    if res_init.returncode != 0:
        print("❌ 錯誤：初始化 workspace 失敗。")
        print(res_init.stderr)
        return 1

    print(res_init.stdout.strip())
    print("\n✅ 並行工作區建立完成！")
    print(f"👉 下一步（推薦使用 Dashboard 啟動與管理）：")
    print(f"   1. 若 Dashboard 尚未啟動，請在框架根目錄執行以下指令啟動：")
    print(f"      python dashboard/main.py")
    print(f"   2. 開啟瀏覽器進入 http://127.0.0.1:8000")
    print(f"   3. 點擊左上角的「+ Track」按鈕，將新工作區登錄至 Dashboard 中：")
    print(f"      - 專案路徑 (Project Path) 指向：{target_path}")
    print(f"      - Workspace 名稱填寫：{ws_name}")
    print(f"   4. 在網頁介面點擊「Start」按鈕一鍵啟動，即可在 Web 介面即時監控 Log！")
    return 0


def cmd_list(args) -> int:
    worktrees = get_worktrees()
    rows = []
    now = time.time()

    for wt in worktrees:
        wt_path = wt["path"]
        branch = wt["branch"] or "(detached)"

        loop_dir = os.path.join(wt_path, ".loop")
        workspaces = []
        if os.path.isdir(loop_dir):
            try:
                for item in os.listdir(loop_dir):
                    if os.path.isdir(os.path.join(loop_dir, item)):
                        workspaces.append(item)
            except OSError:
                pass

        if not workspaces:
            rows.append({
                "path": wt_path,
                "branch": branch,
                "workspace": "-",
                "status": "-",
                "phase": "-",
                "stuck": "-"
            })
        else:
            for ws in workspaces:
                # 執行中判斷 (run.lock)
                lock_file = os.path.join(wt_path, ".loop", ws, ".loop_state", "run.lock")
                if os.path.exists(lock_file):
                    try:
                        mtime = os.path.getmtime(lock_file)
                        age = now - mtime
                        if age < 3600:
                            status = "🟢 running"
                        else:
                            status = "⚠️ stale-lock"
                    except OSError:
                        status = "⏸ idle"
                else:
                    status = "⏸ idle"

                # 讀取 state.json 狀態
                control_path = os.path.join(wt_path, ".loop", ws, "state.json")
                phase, stuck = parse_control_file(control_path)


                rows.append({
                    "path": wt_path,
                    "branch": branch,
                    "workspace": ws,
                    "status": status,
                    "phase": phase,
                    "stuck": stuck
                })

    # 表格欄位設定
    headers = ["Worktree Path", "Branch", "Workspace", "Status", "Phase", "Stuck"]
    keys = ["path", "branch", "workspace", "status", "phase", "stuck"]

    # 計算寬度
    widths = {k: len(h) for k, h in zip(keys, headers)}
    for row in rows:
        for k in keys:
            widths[k] = max(widths[k], len(str(row[k])))

    # 印出表格
    border = "+-" + "-+-".join("-" * widths[k] for k in keys) + "-+"
    header_row = "| " + " | ".join(f"{h:<{widths[k]}}" for k, h in zip(keys, headers)) + " |"

    print(border)
    print(header_row)
    print(border)
    for row in rows:
        print("| " + " | ".join(f"{str(row[k]):<{widths[k]}}" for k in keys) + " |")
    print(border)

    return 0


def cmd_remove(args) -> int:
    target = args.target
    force = args.force

    worktrees = get_worktrees()
    target_wt = None

    # 解析輸入：可接受完整路徑，或 branch 名稱
    abs_target = os.path.abspath(os.path.expanduser(target))
    for wt in worktrees:
        if os.path.abspath(wt["path"]) == abs_target:
            target_wt = wt
            break

    if not target_wt:
        for wt in worktrees:
            if wt["branch"] == target:
                target_wt = wt
                break

    if not target_wt:
        print(f"❌ 錯誤：未找到與「{target}」相符的 worktree 路徑或分支名稱。")
        return 1

    target_path = target_wt["path"]
    target_branch = target_wt["branch"]

    # 取得主 worktree (通常是第一個 worktree，或是我們目前所在的)
    res_top = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, encoding="utf-8")
    if res_top.returncode == 0:
        main_root = os.path.abspath(res_top.stdout.strip())
        if os.path.abspath(target_path) == main_root:
            print("❌ 錯誤：無法移除目前所在的主工作區。")
            return 1

    # 安全閘檢查
    if not force:
        loop_dir = os.path.join(target_path, ".loop")
        now = time.time()
        if os.path.isdir(loop_dir):
            try:
                for ws in os.listdir(loop_dir):
                    ws_path = os.path.join(loop_dir, ws)
                    if os.path.isdir(ws_path):
                        lock_file = os.path.join(ws_path, ".loop_state", "run.lock")
                        if os.path.exists(lock_file):
                            mtime = os.path.getmtime(lock_file)
                            if now - mtime < 3600:
                                print(f"❌ 錯誤：工作區「{ws}」中尚有執行中的 loop (lock 存在且新鮮)。")
                                print("請先停下 loop 後再移除，或加上 --force 強制移除。")
                                return 1
            except OSError:
                pass

    # 執行移除
    cmd = ["git", "worktree", "remove"]
    if force:
        cmd.append("--force")
    cmd.append(target_path)

    print(f"~ 正在移除並行工作區：{target_path} ...")
    res_rm = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if res_rm.returncode != 0:
        print("❌ 錯誤：移除 git worktree 失敗。")
        print(res_rm.stderr)
        return 1

    print(f"✅ 成功移除工作區：{target_path}")
    if target_branch and target_branch != "(detached)":
        print(f"💡 提醒：分支「{target_branch}」尚未被刪除。若不需使用，可手動執行：")
        print(f"   git branch -d {target_branch}")
        print(f"   (或是由 AI Agent 代勞為您執行刪除指令)")

    return 0


def main(argv) -> int:
    # 驗證 cwd 是 git 工作區
    res_chk = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, encoding="utf-8")
    if res_chk.returncode != 0:
        print("❌ 錯誤：當前工作目錄不是 git 工作區，請在 git repo 底下執行。")
        return 1

    ap = argparse.ArgumentParser(description="Loop Engineering 同 repo 並行多工工具 (git worktree)")
    subparsers = ap.add_subparsers(dest="cmd", required=True)

    # add
    p_add = subparsers.add_parser("add", help="建立新工作區並初始化 workspace")
    p_add.add_argument("branch", help="欲建立或使用的分支名稱")
    p_add.add_argument("--name", "-n", default=None, help="指定 workspace 名稱 (預設為 sanitized branch)")
    p_add.add_argument("--path", "-p", default=None, help="指定 worktree 目的路徑 (預設為同層 sibling)")
    p_add.add_argument("--base", "-b", default=None, help="基底 Commit/Branch (僅在建立新分支時使用)")

    # list
    p_list = subparsers.add_parser("list", help="列出各工作區與 loop 狀態")

    # remove
    p_remove = subparsers.add_parser("remove", help="移除工作區")
    p_remove.add_argument("target", metavar="branch-or-path", help="指定移除的 worktree 路徑或分支名稱")
    p_remove.add_argument("--force", "-f", action="store_true", help="強制移除 (忽略執行中狀態或未保存變更)")

    args = ap.parse_args(argv[1:])

    if args.cmd == "add":
        return cmd_add(args)
    elif args.cmd == "list":
        return cmd_list(args)
    elif args.cmd == "remove":
        return cmd_remove(args)

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
