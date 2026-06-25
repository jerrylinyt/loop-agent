#!/usr/bin/env python3
"""
init-project.py — 在「既有 code repo」內建立 Loop Engineering 規劃書骨架（不複製框架）。

設計：框架是外部共享、唯讀的 clone（本檔所在目錄）；各專案只在 code repo 的 .loop/ 放規劃書，
      用 framework_path 指回這份共享框架（見 REFACTOR_PLAN §3.3.6：共享 clone、路徑引用）。

用法：
  python3 <framework_path>/init-project.py /path/to/code-repo
  python3 <framework_path>/init-project.py .          # 在當前 code repo

它做什麼：
  1. 在 <code-repo>/.loop/ 建 phases/ 結構。
  2. 複製樣板：REQUIREMENTS.md、loop.config.yaml（把 framework_path 寫成本框架的實際路徑）。
  3. 確保 ~/.loop/profile.yaml 存在（缺則從樣板複製）。
  4. 補 .gitignore（loop.log、.loop_state 不進版控）。
  5. 印出下一步（跑階段① 需求訪談）。
它「不」做：不複製/不 submodule 框架；不寫入框架；不碰 code 本身。
"""

import os
import sys
import shutil

try:                                      # Windows 主控台 cp950 → 強制 UTF-8 輸出
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

FRAMEWORK = os.path.dirname(os.path.abspath(__file__))
TPL = os.path.join(FRAMEWORK, "generators", "templates")


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 1
    repo = os.path.abspath(os.path.expanduser(argv[1]))
    if not os.path.isdir(repo):
        print(f"❌ 目標不是資料夾：{repo}")
        return 1

    loop_dir = os.path.join(repo, ".loop")
    phases_dir = os.path.join(loop_dir, "phases")
    os.makedirs(phases_dir, exist_ok=True)

    # 1) REQUIREMENTS.md（不覆蓋既有）
    req_dst = os.path.join(loop_dir, "REQUIREMENTS.md")
    if not os.path.exists(req_dst):
        shutil.copy(os.path.join(TPL, "REQUIREMENTS.template.md"), req_dst)
        print(f"  + {req_dst}")
    else:
        print(f"  = 已存在，略過 {req_dst}")

    # 2) loop.config.yaml（把 framework_path 換成本框架實際路徑）
    cfg_dst = os.path.join(loop_dir, "loop.config.yaml")
    if not os.path.exists(cfg_dst):
        with open(os.path.join(TPL, "loop.config.template.yaml"), encoding="utf-8") as f:
            cfg = f.read()
        cfg = cfg.replace("framework_path: ~/.loop/framework",
                          f"framework_path: {FRAMEWORK}")
        with open(cfg_dst, "w", encoding="utf-8") as f:
            f.write(cfg)
        print(f"  + {cfg_dst}  (framework_path → {FRAMEWORK})")
    else:
        print(f"  = 已存在，略過 {cfg_dst}")

    # 3) ~/.loop/profile.yaml（缺則複製樣板）
    home_loop = os.path.expanduser("~/.loop")
    os.makedirs(home_loop, exist_ok=True)
    profile = os.path.join(home_loop, "profile.yaml")
    if not os.path.exists(profile):
        shutil.copy(os.path.join(TPL, "profile.template.yaml"), profile)
        print(f"  + {profile}  (使用者定義區；請填入你的模型指令)")
    else:
        print(f"  = 已存在，略過 {profile}")

    # 4) .gitignore（補 loop 產物）
    gi = os.path.join(repo, ".gitignore")
    needed = [".loop/loop.log", ".loop/.loop_state/", ".loop/loop.log.*"]
    existing = ""
    if os.path.exists(gi):
        with open(gi, encoding="utf-8") as f:
            existing = f.read()
    add = [p for p in needed if p not in existing]
    if add:
        with open(gi, "a", encoding="utf-8") as f:
            f.write("\n# Loop Engineering 產物\n" + "\n".join(add) + "\n")
        print(f"  ~ 補 .gitignore：{', '.join(add)}")

    print("\n✅ 初始化完成。下一步：")
    print(f"  ① 需求訪談：把 {FRAMEWORK}/generators/0-requirements-interview.md")
    print(f"     交給 agent，產出 .loop/REQUIREMENTS.md（人類確認）。")
    print(f"  ② 生成規劃書：用 generators/1-plan-generator.md 產 CONTROL.md + phases/ + 補完 loop.config.yaml，")
    print(f"     再跑 generators/2-plan-review-gate.md 過關。")
    print(f"  ③ 執行：cd {loop_dir} && python3 {FRAMEWORK}/engine/loop.py")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
