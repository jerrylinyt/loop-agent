#!/usr/bin/env python3
"""
install-skill.py — 把框架附帶的 Claude Code skill 安裝到 ~/.claude/skills/(預設,使用者層級)
或某個 repo 的 .claude/skills/(--project <repo>,專案層級)。

來源在 integrations/claude-code/skills/<name>/SKILL.template.md,安裝時把 {{FRAMEWORK_PATH}}
換成這個框架實際所在路徑(本檔所在目錄),寫到目的地的 SKILL.md。這支腳本只是其中一種安裝方式;
其他兩種(見 README)：
  - 使用者自己手動複製 SKILL.template.md,把 {{FRAMEWORK_PATH}} 換成框架路徑。
  - 請任何 agent(用 Read + Write 工具)做跟本腳本一樣的事——不需要先裝好 skill 才能用 agent 裝,
    一個剛開始、什麼 skill 都還沒裝的 agent session 也能讀這份檔案後直接照做。

本檔位於 integrations/claude-code/，是框架眾多「選用整合」之一（只給用 Claude Code 的人用）。
若你用的是 gemini-cli / opencode / codex 等其他 agent CLI，不需要這支腳本——直接把
generators/bootstrap.md 整份內容交給你的 agent 即可，bootstrap.md 不假設任何特定 CLI。

用法：
  python3 integrations/claude-code/install-skill.py                       # 裝到 ~/.claude/skills/loop-prep/（建議）
  python3 integrations/claude-code/install-skill.py --project /path/repo  # 裝到 /path/repo/.claude/skills/loop-prep/
  python3 integrations/claude-code/install-skill.py --name loop-prep      # 指定要裝哪個 skill（目前只有這一個）
"""

import os
import sys
import argparse

try:                                      # Windows 主控台 cp950 → 強制 UTF-8 輸出
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

FRAMEWORK = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SKILLS_SRC = os.path.join(FRAMEWORK, "integrations", "claude-code", "skills")


def install_one(name, dest_root):
    src = os.path.join(SKILLS_SRC, name, "SKILL.template.md")
    if not os.path.exists(src):
        available = [d for d in os.listdir(SKILLS_SRC)] if os.path.isdir(SKILLS_SRC) else []
        print(f"❌ 找不到 skill 來源：{src}")
        if available:
            print(f"   可用的 skill：{', '.join(available)}")
        return None
    with open(src, encoding="utf-8") as f:
        content = f.read()
    content = content.replace("{{FRAMEWORK_PATH}}", FRAMEWORK.replace("\\", "/"))
    dest_dir = os.path.join(dest_root, name)
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, "SKILL.md")
    with open(dest, "w", encoding="utf-8") as f:
        f.write(content)
    return dest


def main():
    ap = argparse.ArgumentParser(description="安裝框架附帶的 Claude Code skill")
    ap.add_argument("--project", default=None,
                    help="裝到指定 repo 的 .claude/skills/（專案層級），不指定則裝使用者層級 ~/.claude/skills/")
    ap.add_argument("--name", default="loop-prep", help="要安裝的 skill 名稱（預設 loop-prep）")
    args = ap.parse_args()

    if args.project:
        repo = os.path.abspath(os.path.expanduser(args.project))
        dest_root = os.path.join(repo, ".claude", "skills")
        scope = f"專案層級（{repo}）"
    else:
        dest_root = os.path.expanduser("~/.claude/skills")
        scope = "使用者層級（全機共用）"

    skills_dir_existed = os.path.isdir(dest_root)
    dest = install_one(args.name, dest_root)
    if not dest:
        return 1

    print(f"✅ 已安裝 skill「{args.name}」→ {dest}（{scope}）")
    print(f"   framework_path 已寫死為：{FRAMEWORK}")
    if not skills_dir_existed:
        print(f"⚠️  {dest_root} 是第一次建立。Claude Code 需要重啟 session 才會開始監看這個新目錄，"
              f"之後新增/修改同層級的 skill 才會即時生效（這次是例外，要重啟一次）。")
    print(f"   裝好後在 Claude Code 打 /{args.name} 即可觸發。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
