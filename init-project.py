#!/usr/bin/env python3
"""
init-project.py — 在「既有 code repo」內建立 Loop Engineering 規劃書骨架（不複製框架）。

設計：框架是外部共享、唯讀的 clone（本檔所在目錄）；各專案只在 code repo 的 .loop/<workspace>/
      放規劃書，用 framework_path 指回這份共享框架（見 REFACTOR_PLAN §3.3.6：共享 clone、路徑引用）。

多 workspace（同一 repo 整理多份需求；一次跑一個）：
  每個 workspace 是 .loop/<name>/ 下一份完整、互相獨立的規劃書(REQUIREMENTS/config/state/phases/
  log/state)。同一個 repo 可重複呼叫本檔、用不同 --name 開多個 workspace，之後各自用
  `run.py --workspace <name>` 驅動。⚠️ 但**一次只跑一個**——本框架不支援同一 code repo 同時跑多個
  loop(loop 直接改 src/，兩個 agent 會邏輯互蓋)；engine 只有「單一啟動鎖」防同一 workspace 被啟動兩次。
  不帶 --name 預設建立 "default"。

用法：
  python3 <framework_path>/init-project.py /path/to/code-repo                # 建 .loop/default/
  python3 <framework_path>/init-project.py /path/to/code-repo --name feat-x  # 加一個新 workspace

它做什麼：
  1. 在 <code-repo>/.loop/<name>/ 建 phases/ 結構。
  2. 複製樣板：REQUIREMENTS.md、loop.config.yaml（{{LOOP_DIR}} 換成 .loop/<name>，
     framework_path 換成本框架的實際路徑）。
  3. 補 .gitignore（涵蓋所有 workspace 的 log/.loop_state/lock，不進版控）。
  4. 印出下一步（跑階段① 需求訪談）。
它「不」做：不複製/不 submodule 框架；不寫入框架；不碰 code 本身。
"""

import os
import sys
import shutil
import argparse

try:                                      # Windows 主控台 cp950 → 強制 UTF-8 輸出
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

FRAMEWORK = os.path.dirname(os.path.abspath(__file__))
TPL = os.path.join(FRAMEWORK, "generators", "templates")


def main(argv):
    ap = argparse.ArgumentParser(description="在 code repo 內建立 Loop Engineering workspace")
    ap.add_argument("repo", help="既有 code repo 的路徑")
    ap.add_argument("--name", "-n", default="default",
                    help="workspace 名稱（同 repo 帶多份需求時各取一個名字；預設 default）")
    args = ap.parse_args(argv[1:])

    repo = os.path.abspath(os.path.expanduser(args.repo))
    if not os.path.isdir(repo):
        print(f"❌ 目標不是資料夾：{repo}")
        return 1
    name = args.name

    ws_dir = os.path.join(repo, ".loop", name)
    phases_dir = os.path.join(ws_dir, "phases")
    os.makedirs(phases_dir, exist_ok=True)
    ws_rel = f".loop/{name}"   # 寫進 yaml 用正斜線，跨平台一致

    # 1) REQUIREMENTS.md（不覆蓋既有）
    req_dst = os.path.join(ws_dir, "REQUIREMENTS.md")
    if not os.path.exists(req_dst):
        shutil.copy(os.path.join(TPL, "REQUIREMENTS.template.md"), req_dst)
        print(f"  + {req_dst}")
    else:
        print(f"  = 已存在，略過 {req_dst}")

    # 2) loop.config.yaml（{{LOOP_DIR}} → .loop/<name>；framework_path → 本框架實際路徑）
    cfg_dst = os.path.join(ws_dir, "loop.config.yaml")
    if not os.path.exists(cfg_dst):
        with open(os.path.join(TPL, "loop.config.template.yaml"), encoding="utf-8") as f:
            cfg = f.read()
        cfg = cfg.replace("{{LOOP_DIR}}", ws_rel)
        cfg = cfg.replace("framework_path: ~/.loop/framework",
                          f"framework_path: {FRAMEWORK}")
        with open(cfg_dst, "w", encoding="utf-8") as f:
            f.write(cfg)
        print(f"  + {cfg_dst}  (workspace={name}, framework_path → {FRAMEWORK})")
    else:
        print(f"  = 已存在，略過 {cfg_dst}")

    # 3) .gitignore（補 loop 產物；用 glob 涵蓋所有 workspace，不必每個 --name 都補一次）
    gi = os.path.join(repo, ".gitignore")
    needed = [".loop/*/loop.log", ".loop/*/loop.log.*",
              ".loop/*/plan.log", ".loop/*/plan.log.*",
              ".loop/*/.loop_state/"]
    existing = ""
    if os.path.exists(gi):
        with open(gi, encoding="utf-8") as f:
            existing = f.read()
    add = [p for p in needed if p not in existing]
    if add:
        with open(gi, "a", encoding="utf-8") as f:
            f.write("\n# Loop Engineering 產物\n" + "\n".join(add) + "\n")
        print(f"  ~ 補 .gitignore：{', '.join(add)}")

    ws_flag = f" --workspace {name}" if name != "default" else ""
    print(f"\n✅ workspace「{name}」初始化完成。下一步（都在 code repo 根目錄執行）：")
    print(f"  ① 需求：編輯 {ws_rel}/REQUIREMENTS.md（人類直接寫完整需求），")
    print(f"     或把 {FRAMEWORK}/generators/0-requirements-interview.md 交給 agent 互動訪談產出。")
    print(f"  ②③ 一鍵跑（依 config.generation.mode）：")
    print(f"     python {FRAMEWORK}/engine/run.py{ws_flag}")
    print(f"     · gated（預設）：生成規劃書收斂 → 停下交你 review → 你確認後：")
    print(f"       python {FRAMEWORK}/engine/run.py --stage execute{ws_flag}")
    print(f"     · auto：加 --mode auto（生成收斂後自動接執行）")
    print(f"  同一 repo 想多帶一份需求（輪流跑）→ 重跑本檔換個 --name。")
    print(f"  想『同時』並行多條任務 → 用 git worktree（見 docs/parallel-multitasking.md / parallel.py），")
    print(f"  別在同一個工作目錄同時跑兩個 loop（會互蓋 src/）。")
    print(f"  詳細輸出已直接印主控台；想轉跑背景看 log 才用 tail -f {ws_rel}/plan.log 或 loop.log。")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
