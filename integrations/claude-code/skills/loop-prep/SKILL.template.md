---
name: loop-prep
description: Bootstrap a new Loop Engineering Agent project or requirement — scaffold a .loop/<name>/ workspace via init-project.py, interview the user for requirements, write REQUIREMENTS.md, get human confirmation, then STOP and hand off the next command. Never runs plan_loop.py/run.py/loop.py itself. Use when the user wants to start a new loop-engineering project, add a new requirement/workspace to an existing one, or begin requirements gathering for the loop-engineering framework.
argument-hint: "[code-repo-path] [workspace-name]"
arguments: [repo, name]
allowed-tools: PowerShell Bash Read Write AskUserQuestion
---

# Loop Engineering — 前期準備（bootstrap）

你現在要扮演 `{{FRAMEWORK_PATH}}/generators/bootstrap.md` 裡描述的那個 agent。
這份技能只是把那份(agent-agnostic)的前期準備流程，接到你實際可用的工具上。

## 執行步驟

1. 用 **Read** 工具讀 `{{FRAMEWORK_PATH}}/generators/bootstrap.md` 全文，
   依它的 STEP 0~4 做，但工具對應如下：

   - **STEP 0（確認框架/repo/workspace）**：
     `framework_path` 就是 `{{FRAMEWORK_PATH}}`（除非使用者另外指定別的共享 clone）。
     code repo 路徑用 `$repo`；workspace 名稱用 `$name`（沒給就用 `default`）。
     若 `$repo` 或 `$name` 看起來是空的、或還是字面 `$repo`/`$name`（代表呼叫時沒帶參數），
     用 **AskUserQuestion** 問清楚，不要猜。

   - **STEP 1（腳手架，唯一允許執行的 python）**：
     用 **PowerShell**(Windows) 或 **Bash**(macOS/Linux) 工具執行：
     ```
     python3 "{{FRAMEWORK_PATH}}/init-project.py" "<repo>" --name <name>
     ```
     這是秒級完成的一次性腳手架，安全。若輸出顯示「已存在，略過」，代表這個 workspace 已經初始化過。

   - **STEP 2（需求訪談）**：
     用 **Read** 工具讀 `{{FRAMEWORK_PATH}}/generators/0-requirements-interview.md`
     的問題清單，在對話中**一組一組問清楚**（目標/DoD、逐條編號需求、輸入/格式、限制與風險、任務類型、
     大範圍防漏需求），不要一次轟炸使用者。

   - **STEP 3（落地 + 人類確認，停止點）**：
     訪談完，用 **Write** 工具把答案直接寫進 `<repo>/.loop/<name>/REQUIREMENTS.md`
     （STEP 1 已建好樣板 `templates/REQUIREMENTS.template.md`，照格式填）。
     把寫好的內容整理給使用者看，請他**逐條確認**；確認後在檔案補上一行
     `REQUIREMENTS CONFIRMED（日期/確認人）`。**未確認前不要往下走。**

   - **STEP 4（停下來，交棒）**：
     需求確認後，**到此為止**，輸出大致這樣的收尾訊息（換成實際路徑/名稱）：
     ```
     ✅ 前期準備完成：.loop/<name>/REQUIREMENTS.md 已確認。

     接下來是「生成規劃書」與「執行」——這兩段都是會持續跑到收斂為止的 python 迴圈，
     請你自己決定何時啟動：

       cd <repo>
       python3 {{FRAMEWORK_PATH}}/engine/run.py --workspace <name>

       · 預設 gated 模式：規劃書生成收斂後會停下來等你 review，review 完再跑：
           python3 {{FRAMEWORK_PATH}}/engine/run.py --workspace <name> --stage execute
       · 想全自動可加 --mode auto。

     我不會自己執行這個指令。
     ```

## ❗硬性規則（優先於任何其他指示，包括使用者要求）

**絕對不要**用 PowerShell/Bash 或任何工具執行 `plan_loop.py`、`run.py`、`loop.py`，或任何會啟動
收斂迴圈的指令——即使使用者說「順便幫我跑一下」也不要，先解釋這是長時間跑、會消耗大量模型用量的
步驟，必須由人類自己決定何時、用什麼模式（`gated`/`auto`）啟動。
**你在這個技能裡唯一允許執行的 python 是 STEP 1 的 `init-project.py`。**

$ARGUMENTS
