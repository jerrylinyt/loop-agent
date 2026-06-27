#` 🔁 loop-engineering — 通用 Loop Engineering Agent 框架

把「**做不完、信不過、會中斷、會卡死**」的大任務，交給一個「由 AI agent 反覆執行、直到收斂達標」的迴圈。
本框架是**共享、唯讀**的：它只提供讀取，所有要改的東西（規劃書 + code）都落在你的 **code repo**。

> 設計緣由與完整取捨見 `rules/BLUEPRINT.md`（方法論藍圖）。

---

## 🤖 給 agent 的速覽（被使用者叫來讀這份 README 的你，先看這段）
若使用者只說了類似「讀這份 README 然後開始」、卻沒給更多細節：
1. 去讀 `generators/bootstrap.md` 全文——這是整個框架**唯一、agent-agnostic 的進入點**，不管你是
   Claude Code、gemini-cli、opencode、codex 或其他任何 CLI 都適用，本檔不假設特定工具。
2. 依它的 STEP 0~4 做：確認 `framework_path`(=這個 repo 的路徑) / 目標 code repo / workspace 名稱
   → 跑一次性的 `init-project.py` 腳手架 → 訪談需求 → 人類確認 → **停下來**,把下一步的 `run.py`
   指令交給人類自己貼上去跑。
3. ❗**絕對不要**自己接著跑 `plan_loop.py` / `run.py` / `loop.py`——那是長時間、會持續跑到收斂為止
   的 python 迴圈,必須由人類自己決定何時、用什麼模式啟動,不是技術限制,是刻意的人類決策點。
4. 若使用者額外要你「幫他的 CLI 裝一個可重複呼叫的捷徑(/指令、custom command 之類)」，見下方
   「給 agent 用的整合：自己產生捷徑」一節——一樣是你自己讀文件、自己生成，不靠任何安裝腳本。

（以下是給「人」看的完整說明，繼續往下讀即可了解整體架構與所有細節。）

---

## 三段生命週期（兩支 python 迴圈 + 一個入口）
> 框架支援 **「平 Phase (Flat)」** 與 **「樹形 Phase (Tree - 漸進拆解)」** 兩種模式（依專案 config 設定）。

```
① 需求討論          人類提供需求 → .loop/<name>/REQUIREMENTS.md（兩種方式，見下；<name>=一份需求）
      ↓
② 生成/規劃（收斂）  engine/plan_loop.py
   〔code1〕          - 平模式：Round A 生成 / Round B 審查，直到全計畫收斂。
                     - 樹模式：漸進生長樹結構，每輪拆解節點，直到全樹 PENDING 節點均完成拆解。
                     卡死處理：連續無進展 → 升級模型 → 仍卡 → 停下交人類（不會空轉到底）
      ↓〔gated: 停下交人類 review｜auto: 直接接③〕
③ 執行迴圈（收斂）   engine/loop.py  反覆觸發 agent 依規劃書執行：
   〔code2〕          - 平模式：依序跑階段，直到最終結果達標或交人類。
                     - 樹模式：針對葉子節點執行與整合驗證，具備自底向上的解鎖機制。
```
> 入口 `engine/run.py` 串接 ②③ 並提供兩種模式。**所有引擎都從 code repo 根目錄執行**（產出落 repo 根、控制檔在 `.loop/<name>/`）。
> 兩個引擎啟動時都會先跑 **preflight 健檢**（佔位模型、framework_path、git repo、REQUIREMENTS/CONTROL 是否存在…），有錯誤就擋下不空轉。

### 階段① 怎麼提供需求（三選一）
- **A. 人類直接寫**:`init` 會放一份 `.loop/<name>/REQUIREMENTS.md` 樣板,填好即可(目標/DoD/逐條編號需求 R001…/輸入/限制)。
- **B. 互動訪談**:把 `generators/0-requirements-interview.md` 交給一個 agent,讓它一組一組問清楚,最後幫你寫成 `.loop/<name>/REQUIREMENTS.md`。
- **C. 一個指令做完整個前期準備（推薦）**:`generators/bootstrap.md` 是**整段前期準備的單一入口**——
  交給任何 agent,它會依序幫你「開 workspace(跑 `init-project.py`)→ 需求訪談 → 人類確認」,
  **做完就停下來**,把下一步該你自己貼上去跑的 `run.py` 指令印出來;agent 不會自己接著跑 ②③(那是長時間、燒用量的收斂迴圈,故意留給人類決定何時啟動)。
> 三種都產出同一份 `REQUIREMENTS.md`;**人類確認**後才進階段②。

### 你的 agent CLI 不是 Claude Code？直接用 C 選項就好
`generators/bootstrap.md` 本身不假設任何特定 CLI——gemini-cli、opencode、codex、Claude Code…
都一樣**直接把整份 `bootstrap.md` 貼給你的 agent**即可,不需要安裝任何東西,也不用讀下面這節。

### 給 agent 用的整合：自己產生捷徑（選用，不靠安裝腳本）
若使用者想要「幫我的 CLI 裝一個可重複呼叫的捷徑(/指令、custom command、skill 之類)」,**不要找安裝
腳本——這裡沒有,故意不做**。請你(agent)自己做這件事：

1. 看 `integrations/<你的 CLI>/` 底下是否已有現成範例(目前只有 `integrations/claude-code/skills/
   loop-prep/SKILL.template.md`,是 Claude Code 的格式範例)。
2. 若使用者用的就是那個 CLI:讀那份 template,把裡面所有 `{{FRAMEWORK_PATH}}` 換成**這個框架的絕對
   路徑**(也就是這個 repo 在使用者機器上的路徑),用 Write 工具存到該 CLI 慣例的位置
   (Claude Code 是 `~/.claude/skills/loop-prep/SKILL.md`,或專案層級 `<repo>/.claude/skills/loop-prep/SKILL.md`)。
3. 若沒有現成範例(用的是 gemini-cli/opencode/codex 等):讀 `generators/bootstrap.md` 全文,依**你
   自己這個 CLI 的官方文件**(自訂指令/skill/prompt 檔的慣例)生成一份等效的捷徑——格式以官方文件為準,
   不確定就直接告訴使用者「你的 CLI 沒有現成範例,我需要查一下官方怎麼定義自訂指令」,不要亂猜格式。
4. 裝完提醒使用者：若目標 skills/指令目錄是**第一次**建立,有些 CLI(如 Claude Code)需要**重啟 session**
   才會開始監看新目錄。

> 這份捷徑永遠只是**前期準備(bootstrap)的便利包裝**,核心邏輯都在 `generators/bootstrap.md`。
> 之後要支援其他 CLI,直接在 `integrations/<該CLI>/` 底下加範例即可,不影響核心。

### 兩種模式（--mode）
- **gated（預設，建議）**:`plan_loop` 把規劃書跑到收斂 → **停下交人類 review** → 你確認 `.loop/<name>/` 內的 config/CONTROL/phases 後,再跑執行迴圈。
- **auto**:規劃書收斂後**自動接續**執行迴圈,一路到最終結果收斂(中途靠震盪偵測/三層升級/human_required 自保)。

### 一個 repo、多份需求（--workspace / --name；一次跑一個）
`.loop/<name>/` 是一份**完整、互相獨立**的規劃書(REQUIREMENTS/config/CONTROL/phases/log/狀態)。
同一個 code repo 可以開多個 `<name>`(每個對應一份需求),把多份需求**整理**在一起。

⚠️ **但一次只跑一個**:本框架不支援在同一個 code repo 同時跑多個 loop——loop 會直接改 `src/`,
兩個 agent 在重疊輪次改到同一批檔案,git 擋不住「邏輯互蓋」。要換另一份需求,等前一個停了再跑。
(引擎有「單一啟動鎖」防你手滑把同一個 workspace 跑兩次;真要物理隔離請各自獨立 clone code repo。)
```bash
python3 $FW/init-project.py /path/to/repo --name featureA   # 開一個 workspace(需求)
python3 $FW/init-project.py /path/to/repo --name featureB   # 再開一個,互相獨立(但別同時跑)
python3 $FW/engine/run.py --workspace featureA              # 跑 A;停了之後再——
python3 $FW/engine/run.py --workspace featureB              # 跑 B
```

## 完整流程圖（從 init-project 到收斂）

> 上方 ①②③ 是高層次概念；這張圖把「實際會跑的指令、人類 gate 的位置、執行迴圈裡每輪疊了什麼防護」全部展開，方便第一次上手對齊心智模型。

```
┌──────────────────────────────────────────────────────────────┐
│ ① 前期準備（一次性；由人類或 agent 跑 generators/bootstrap.md）│
└──────────────────────────────────────────────────────────────┘
                            │
                            ▼
        ┌───────────────────────────────────────┐
        │ python3 $FW/init-project.py <repo>    │
        │   --name <workspace>                  │
        │ → 建 .loop/<name>/ 骨架               │
        │   (REQUIREMENTS 樣板、.gitignore、    │
        │    framework_path)                    │
        └───────────────────────────────────────┘
                            │
                            ▼
        ┌───────────────────────────────────────┐
        │ 填 .loop/<name>/REQUIREMENTS.md       │
        │  A) 人類自填樣板                      │
        │  B) generators/0-… 互動訪談           │
        │  C) bootstrap.md 一條龍               │
        └───────────────────────────────────────┘
                            │
                            ▼
              ╔════════════════════════╗
              ║ 🧑 人類確認需求 (gate#1) ║
              ╚════════════════════════╝
                            │
                            ▼
        ┌───────────────────────────────────────┐
        │ python3 $FW/engine/run.py             │
        │   入口；串接 ② plan_loop + ③ loop     │
        └───────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────┐
│ ② 規劃書生成迴圈（engine/plan_loop.py）                       │
│                                                              │
│   每輪兩個獨立 context 的 agent：                            │
│     ┌─ Round A：生成計畫（新 agent）                         │
│     │                                                        │
│     ▼                                                        │
│     Round B：獨立審查（另一個新 agent；Plan Gate）           │
│     │                                                        │
│     ▼                                                        │
│     收斂？── 否 ── 卡住偵測 → 升級模型 → 仍卡 → 🧑 交人類   │
│     │ 是                                                     │
│     ▼                                                        │
│   產出：CONTROL.md / phases/ / loop.config.yaml              │
└──────────────────────────────────────────────────────────────┘
                            │
                            ▼
              ╔════════════════════════╗
              ║ 模式分支？              ║
              ╚════════════════════════╝
                  │                  │
              gated (預設)         auto
                  │                  │
                  ▼                  │
        ╔════════════════════════╗   │
        ║ 🧑 人類 review (gate#2) ║   │
        ║ .loop/<name>/ 內       ║   │
        ║  config/CONTROL/       ║   │
        ║  phases/…              ║   │
        ╚════════════════════════╝   │
                  │                  │
                  └────────┬─────────┘
                           ▼
┌──────────────────────────────────────────────────────────────┐
│ ③ 執行迴圈（engine/loop.py）— 反覆喚醒「全新無狀態」agent    │
│                                                              │
│ ┌── for round in 1..max_rounds: ───────────────────────────┐ │
│ │                                                          │ │
│ │  ① 前置：log rotate / 鎖心跳 / 同步框架文件              │ │
│ │     ↓                                                    │ │
│ │  ② [G0] 主控檔毀損自檢 + 自動還原                        │ │
│ │     ↓                                                    │ │
│ │  ③ [Git Review Gate] 獨立 agent 審上一輪 commit diff     │ │
│ │     ├ PASS → 繼續                                        │ │
│ │     ├ REVERT → 自動 git revert,跳下一輪重試              │ │
│ │     └ FATAL_STATE → 🧑 停機交人                          │ │
│ │     ↓                                                    │ │
│ │  ④ 停止判定                                              │ │
│ │     ├ stop_condition_met → 🏁 LOOP COMPLETE              │ │
│ │     └ human_required → 🧑 停機交人                       │ │
│ │     ↓                                                    │ │
│ │  ⑤ 選模型:按 stuck_level 挑 fast/normal/thinking         │ │
│ │     ↓                                                    │ │
│ │  ┌──────────────────────────────────────────────────┐    │ │
│ │  │ ⑥ subprocess:啟動「全新無狀態 agent」             │    │ │
│ │  │    跑 boot sequence STEP G→0→…→10                │    │ │
│ │  │    🚨 一輪一任務 + 收斂留證據                     │    │ │
│ │  │    🚨 STEP 10 物理停機 → process exit             │    │ │
│ │  │   watchdog: round_timeout=1hr / idle_timeout=30m │    │ │
│ │  └──────────────────────────────────────────────────┘    │ │
│ │     ↓                                                    │ │
│ │  ⑦ git_guard:補 autocommit(本輪還原點)                   │ │
│ │     ↓                                                    │ │
│ │  ⑧ 震盪/卡住偵測:失敗指紋 + 無活動簽章                   │ │
│ │     └ 達門檻 → 升 stuck_level                            │ │
│ │       fast → normal → thinking → 🧑 Lv2 交人             │ │
│ │     ↓                                                    │ │
│ │  ⑨ sleep(interval) ────────── 回到迴圈頂 ────────────→   │ │
│ └──────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
                            │
                            ▼
              ╔══════════════════════════════════╗
              ║ 終止狀態                          ║
              ║  🏁 LOOP COMPLETE(全部收斂)       ║
              ║  🧑 human_required(卡死/破壞)     ║
              ║  ⛔ max_rounds(預算用盡)          ║
              ╚══════════════════════════════════╝
```

**讀圖三個重點：**
1. **兩道人類 gate**:確認需求(gate#1)、review 規劃書(gate#2,僅 gated 模式);其餘自動。
2. **agent 是被「外部迴圈」反覆呼叫的無狀態 subprocess**,每輪一個全新 process,做完一個任務就 exit、把控制權交還引擎——這是「一輪一任務 + STEP 10 物理停機」設計的底層原因。
3. **執行迴圈每輪疊了 7 層防護**(G0 自檢 / Git Review Gate / 停止判定 / 選模型 / watchdog / autocommit / 震盪偵測),agent 行為層之外還有完整的機器副防線。

## 目錄
```
loop-engineering/            ← 共享、唯讀框架（不進任何 code repo）
├── rules/                   規則區（通用方法論，技術中立）
│   ├── BLUEPRINT.md             設計藍圖（九大原則、反模式）
│   ├── boot-sequence.md         每輪開機程序（STEP G→10；含一輪一任務 + 物理停機鐵則）
│   ├── git-safety.md            Git 安全網（只作用工作區；禁寫框架）
│   ├── git-review-gate.md       獨立審查輪（每輪自動審 commit diff，破壞性改動自動 revert）
│   ├── convergence.md           單任務收斂（不信單次；重推留痕、從嚴歸類）
│   ├── completeness.md          大範圍防漏（列舉清單+行覆蓋；DEAD 需機械證據）
│   ├── oscillation-escalation.md 震盪偵測 + 三層升級 + FROZEN
│   ├── issues.md                Issue 分級 + 修正記錄
│   ├── state-model.md           狀態/流程控制（N 階段、config 驅動）
│   └── context-budget.md        ★Context 防爆（橫切硬約束）
├── generators/              生成區（前期：需求 → 規劃書）
│   ├── bootstrap.md             ★前期準備總入口（開 workspace + 訪談 + 確認，停在你跑 python 之前）
│   ├── 0-requirements-interview.md / 1-plan-generator.md / 2-plan-review-gate.md
│   └── templates/           CONTROL / PHASE / REQUIREMENTS / loop.config 樣板
├── engine/                  引擎區（兩支迴圈 + 入口，config 驅動、N 階段）
│   ├── plan_loop.py             ②規劃書生成收斂迴圈（code1）
│   ├── loop.py                  ③執行收斂迴圈（code2）
│   ├── prompts.yaml             agent 提示樣板（外部化；只指向 rules，不重述方法論）
│   └── run.py                   入口：串接 ②③、提供 gated/auto 兩種模式
├── maintenance/             框架開發期工具（不進 runtime 流程、不會 sync 進 user 專案）
│   └── rule-loophole-audit.md   ★對抗式語意稽核 prompt：改完 rules/prompts 後，交給 agent 重複跑找「鑽空子」的縫
├── init-project.py          腳手架：在 code repo 內建 .loop/<name>/、寫 framework_path（--name 開新需求）
└── integrations/            選用整合範例（核心不依賴這裡的任何東西；未用對應 CLI 可整個忽略）
    └── claude-code/             Claude Code 格式範例（無安裝腳本——由 agent 讀範例自己生成，見上節）
        └── skills/loop-prep/SKILL.template.md   {{FRAMEWORK_PATH}} 代換後存到 ~/.claude/skills/ 即可用 /loop-prep
```

## 四區
> `<name>` = workspace 名稱 = 一份需求(`init-project.py --name <name>` 開的)，預設 `default`。

| 區 | 放什麼 | 位置 |
|----|--------|------|
| 規則區 | 通用方法論 | 本框架 `rules/`（唯讀） |
| 設定區 | 階段/門檻/模型/停止條件 | code repo `.loop/<name>/loop.config.yaml` |
| 專屬規則區 | 狀態表/任務規格/coverage | code repo `.loop/<name>/CONTROL.md` + `phases/` |
| 工作區 | 輸入/產出/log/活計數器 | code repo（產出 `src/` 跨 workspace 共用；分析文件 `.loop/<name>/docs/` 各 workspace 獨立） |

cascade：**框架預設 < 專案 `.loop/<name>/loop.config.yaml`**。

## 可靠性機制（兩個引擎共用，code 只讀設定/狀態）
- **Preflight 健檢**：啟動先檢查佔位模型、`framework_path`、git repo、`build_cmd` 執行檔、REQUIREMENTS/CONTROL 是否存在；有錯誤直接擋下，不會空轉到 max_rounds 才發現設定沒填。
- **三模型二維調度**：順風時按角色（thinking/normal/fast）指派模型，逆風時（卡住）沿階梯升級。
- **硬 Breaker 防護**：`max_depth`、`max_leaves`、`max_leaf_reflow`、`growth_stall_rounds`，一旦撞線即凍結交人，程式不得自我放寬。
- **Console echo**：agent 詳細輸出預設**直接印主控台**，不用另開視窗 `tail -f`；同時仍寫進 log 檔。`--quiet`/`LOOP_QUIET=1` 可關閉。
- **震盪歷史持久化**：失敗指紋存 `.loop/<name>/.loop_state/fail_history`，loop 中斷重啟後接續判斷，不會因重啟而歸零震盪偵測。進度/活動標記同樣存 `.loop_state/progress`（跨重啟正確判進展、不誤判卡死）。
- **無活動逃生門**：除了「不收斂 / 震盪」，引擎還偵測「連續多輪沒提交也沒推進計數器」（反覆被 watchdog 中斷、CLI 逾時、空轉），一樣走階梯升級到人類——壞掉的環境不會無聲燒到 `max_rounds` 才停。
- **獨立 Plan Gate**：規劃書的「生成」與「審查」是兩個獨立 context 的 agent 呼叫（Round A / Round B），審查輪只審不生,避免同一個 agent 自己生、自己審的橡皮圖章問題。
- **獨立 Git Review Gate**：執行迴圈每輪開始前,引擎自動把上一輪的 commit diff 交給**另一個獨立 context 的審查 agent**(見 `rules/git-review-gate.md`),抓中斷殘留、排版破壞、思考過程外洩、佔位符偷懶、衝突標記、計數器暴衝灌水等十條紅線——發現破壞性改動就**自動 revert**,致命級狀態檔毀損則停下交人。是 agent 行為層之外的機器副防線。
- **單一啟動鎖（含心跳）**：同一份需求(workspace)不會被手滑啟動兩次(防呆/冪等;非並行機制——同 repo 一次只跑一個,見上節)。鎖檔每輪心跳更新,長跑(超過 1 小時)也不會被誤判成殘留而被第二個程序搶鎖並行。
- **跨專案總覽**：每次 run 結束自動 upsert 一行到 `~/.loop/index.md`（專案/repo/workspace/phase/stuck/狀態/時間），一人多專案好追蹤。

## 快速開始

**最快路徑**：把 `generators/bootstrap.md` 交給任何 agent(或 Claude Code 打 `/loop-prep`),
它會幫你做完下面的 0~2 步,做完就停下來等你貼指令。以下是它背後實際做的事、也可以自己手動走：

```bash
# 0) 框架放在固定位置（本資料夾就是；或 clone 到 ~/.loop/framework）
FW=<此框架路徑>
pip install -r $FW/requirements.txt  # 安裝依賴（如 PyYAML）

# 1) 在你的 code repo 初始化一個 workspace(=一份需求；建 .loop/<name>/、寫 framework_path、補 .gitignore)
python3 $FW/init-project.py /path/to/your-code-repo --name default
cd /path/to/your-code-repo            # ★所有引擎都從 repo 根目錄執行

# 2) 階段①：填好 .loop/default/REQUIREMENTS.md（或用 generators/0 互動訪談產出），人類確認

# 3) 一鍵跑（依 config.generation.mode；詳細輸出已直接印在這個終端機）
python3 $FW/engine/run.py                      # gated（預設# ）：生成收斂→停下交你 review
#   → review .loop/default/ 後執行：
python3 $FW/engine/run.py --stage execute      # 開始實作執行迴圈
#   或全自動：
python3 $FW/engine/run.py --mode auto          # 生成收斂後自動接執行
```
> 也可分開跑:`python3 $FW/engine/plan_loop.py`（只生成）/ `python3 $FW/engine/loop.py`（只執行）；
> 都吃同樣的 `--workspace`/`--quiet` 參數。想背景執行才需要 `tail -f .loop/default/{plan,loop}.log`。

## 核心原則（為什麼這樣設計）
- **文件即狀態**：換 agent / 換模型 / 中斷後，只靠 `.loop/` 就能接手。
- **每輪只做一件事**：agent 每次被喚醒只推進【單一一個】任務或【單一一次】驗證,做完即停機交還外部迴圈;穩定交棒 > 一次衝完(防多工幻覺與生命週期失控)。
- **不信單次**：收斂協定（獨立重推 + 連續 N 次一致；重推稿留痕可稽核、有疑義一律從嚴）。
- **不會漏看**：列舉清單（分母）+ 行覆蓋 + 集合穩定收斂（DEAD 狀態需機械式零引用證據）。
- **卡死有逃生門**：震盪偵測 → 二維調度升級 → FROZEN → 交人類。
- **授權紅線**：程式只判斷客觀數據（如輪數、深度），價值判斷與 Breaker 放寬一律交人類。
- **Git 是安全網**：一輪一 commit（只在工作區）；框架唯讀、絕不寫入。
- **Context 防爆**：log 不進 context、CONTROL 保持決策最小集、不整批讀資料。
