# 🔁 loop-engineering — 通用 Loop Engineering Agent 框架

把「**做不完、信不過、會中斷、會卡死**」的大任務，交給一個「由 AI agent 反覆執行、直到收斂達標」的迴圈。
本框架是**共享、唯讀**的：它只提供讀取，所有要改的東西（規劃書 + code）都落在你的 **code repo**。

> 設計緣由與完整取捨見 `../loop-agent/REFACTOR_PLAN.md`。方法論見 `rules/BLUEPRINT.md`。

## 三段生命週期（兩支 python 迴圈 + 一個入口）
```
① 需求討論          人類提供需求 → .loop/<name>/REQUIREMENTS.md（兩種方式，見下；<name>=一份需求）
      ↓
② 生成規劃書（收斂） engine/plan_loop.py  每個 cycle 兩輪：
   〔code1〕            Round A 生成（從 REQUIREMENTS 獨立重推/精修規劃書）
                       Round B 審查（獨立 context，只審不生，跑 Plan Gate）
                     直到「連續 N 個 cycle 無實質變更且 Gate PASS」→ 收斂；
                     卡死處理：連續無進展 → 升【增強模型】→ 仍卡 → 停下交人類（不會空轉到底）
      ↓〔gated: 停下交人類 review｜auto: 直接接③〕
③ 執行迴圈（收斂）   engine/loop.py  反覆觸發 agent 依規劃書執行 → 收斂/自我修正/震盪升級
   〔code2〕         → 直到最終結果達標或交人類
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
都一樣**直接把整份 `bootstrap.md` 貼給你的 agent**即可,不需要安裝任何東西。下面這段 `/loop-prep`
skill 純粹是**選用的 Claude Code 專屬便利包裝**(在 `integrations/claude-code/` 底下,跟框架核心
分開放;未來要加其他 CLI 的整合,也會放在 `integrations/<其他CLI>/`,不影響核心)。

### Claude Code 整合（選用）：`/loop-prep` skill
`bootstrap.md` 在 Claude Code 裡有對應的 skill 包裝,裝好後直接打 `/loop-prep <repo路徑> <workspace名稱>`
就會觸發上面 C 選項那套流程。Skill 來源在 `integrations/claude-code/skills/loop-prep/SKILL.template.md`
(`{{FRAMEWORK_PATH}}` 是唯一需要代換的 token),**三種裝法任選**：
```bash
# 1) 跑安裝腳本（最簡單；自動代換 token，預設裝到使用者層級全機共用）
python3 integrations/claude-code/install-skill.py                          # → ~/.claude/skills/loop-prep/SKILL.md
python3 integrations/claude-code/install-skill.py --project /path/to/repo  # → 改裝到該 repo 的 .claude/skills/（專案層級）

# 2) 自己手動複製
#    把 integrations/claude-code/skills/loop-prep/SKILL.template.md 複製到
#    ~/.claude/skills/loop-prep/SKILL.md，並把檔內所有 {{FRAMEWORK_PATH}} 換成這個框架的實際路徑。

# 3) 請 agent 自己裝（不需要先裝好任何 skill 才能用這招）
#    在任何全新 Claude Code session 說「幫我把 integrations/claude-code/skills/loop-prep/ 這個
#    skill 裝起來」，agent 用 Read 讀 SKILL.template.md、把 {{FRAMEWORK_PATH}} 換成這個框架的
#    絕對路徑、用 Write 寫到 ~/.claude/skills/loop-prep/SKILL.md ——就是 install-skill.py 做的事，
#    agent 用 Read+Write 工具一樣做得到。
```
> ⚠️ 若 `~/.claude/skills/`(或目標 repo 的 `.claude/skills/`)是**第一次**建立,Claude Code 需要
> **重啟 session** 才會開始監看這個新目錄;之後新增/修改同層級的 skill 才會即時生效。

### 兩種模式（--mode）
- **gated（預設，建議）**:`plan_loop` 把規劃書跑到收斂 → **停下交人類 review** → 你確認 `.loop/<name>/` 內的 config/CONTROL/phases 後,再跑執行迴圈。
- **auto**:規劃書收斂後**自動接續**執行迴圈,一路到最終結果收斂(中途靠震盪偵測/三層升級/human_required 自保)。

### 一個 repo、多份需求並行（--workspace / --name）
`.loop/<name>/` 是一份**完整、互相獨立**的規劃書(REQUIREMENTS/config/CONTROL/phases/log/狀態)。
同一個 code repo 可以開多個 `<name>`(每個對應一份需求),想同時跑哪幾個 **就各開一個 terminal**,
分別執行 `run.py --workspace <name>` 即可——不需要、也沒有額外的「一鍵全部啟動」腳本(每個 terminal
原生顯示完整輸出比把多個程序輸出混在一起好讀)。並行安全由引擎內建兩種鎖保證(workspace 鎖防同一份
被重複啟動;repo 級 git 鎖序列化跨 workspace 的 git commit),細節見 `engine/README.md`。
```bash
python3 $FW/init-project.py /path/to/repo --name featureA   # 開一個新 workspace(需求)
python3 $FW/init-project.py /path/to/repo --name featureB   # 再開一個,互相獨立
# terminal 1:
python3 $FW/engine/run.py --workspace featureA
# terminal 2（同 repo、不同需求，並行跑）:
python3 $FW/engine/run.py --workspace featureB
```

## 目錄
```
loop-engineering/            ← 共享、唯讀框架（不進任何 code repo）
├── rules/                   規則區（通用方法論，技術中立）
│   ├── BLUEPRINT.md             設計藍圖（九大原則、反模式）
│   ├── boot-sequence.md         每輪開機程序（STEP G→10）
│   ├── git-safety.md            Git 安全網（只作用工作區；禁寫框架）
│   ├── convergence.md           單任務收斂（不信單次）
│   ├── completeness.md          大範圍防漏（列舉清單+行覆蓋）
│   ├── oscillation-escalation.md 震盪偵測 + 三層升級 + FROZEN
│   ├── issues.md                Issue 分級 + 修正記錄
│   ├── state-model.md           狀態/流程控制（N 階段、config 驅動）
│   └── context-budget.md        ★Context 防爆（橫切硬約束）
├── generators/              生成區（前期：需求 → 規劃書）
│   ├── bootstrap.md             ★前期準備總入口（開 workspace + 訪談 + 確認，停在你跑 python 之前）
│   ├── 0-requirements-interview.md / 1-plan-generator.md / 2-plan-review-gate.md
│   └── templates/           CONTROL / PHASE / REQUIREMENTS / loop.config / profile 樣板
├── engine/                  引擎區（兩支迴圈 + 入口，config 驅動、N 階段）
│   ├── plan_loop.py             ②規劃書生成收斂迴圈（code1）
│   ├── loop.py                  ③執行收斂迴圈（code2）
│   └── run.py                   入口：串接 ②③、提供 gated/auto 兩種模式
├── init-project.py          腳手架：在 code repo 內建 .loop/<name>/、寫 framework_path（--name 開新需求）
└── integrations/            選用整合（核心不依賴這裡的任何東西；未用對應 CLI 可整個忽略）
    └── claude-code/             Claude Code 專屬
        ├── install-skill.py         安裝 skill 到 ~/.claude/skills/ 或某 repo 的 .claude/skills/
        └── skills/loop-prep/SKILL.template.md   {{FRAMEWORK_PATH}} 代換後即可用 /loop-prep
```

## 四區 + 使用者定義區
> `<name>` = workspace 名稱 = 一份需求(`init-project.py --name <name>` 開的)，預設 `default`。

| 區 | 放什麼 | 位置 |
|----|--------|------|
| 規則區 | 通用方法論 | 本框架 `rules/`（唯讀） |
| 設定區 | 階段/門檻/模型/停止條件 | code repo `.loop/<name>/loop.config.yaml` |
| 專屬規則區 | 狀態表/任務規格/coverage | code repo `.loop/<name>/CONTROL.md` + `phases/` |
| 工作區 | 輸入/產出/log/活計數器 | code repo（產出 `src/` 跨 workspace 共用；分析文件 `.loop/<name>/docs/` 各 workspace 獨立） |
| 使用者定義區 | 模型/風格/門檻預設（跨專案） | `~/.loop/profile.yaml` |

cascade：**框架預設 < `~/.loop/profile.yaml` < 專案 `.loop/<name>/loop.config.yaml` < 環境變數**。

## 可靠性機制（兩個引擎共用，code 只讀設定/狀態）
- **Preflight 健檢**：啟動先檢查佔位模型、`framework_path`、git repo、`build_cmd` 執行檔、REQUIREMENTS/CONTROL 是否存在；有錯誤直接擋下，不會空轉到 max_rounds 才發現設定沒填。
- **Console echo**：agent 詳細輸出預設**直接印主控台**，不用另開視窗 `tail -f`；同時仍寫進 log 檔。`--quiet`/`LOOP_QUIET=1` 可關閉。
- **震盪歷史持久化**：失敗指紋存 `.loop/<name>/.loop_state/fail_history`，loop 中斷重啟後接續判斷，不會因重啟而歸零震盪偵測。
- **獨立 Plan Gate**：規劃書的「生成」與「審查」是兩個獨立 context 的 agent 呼叫（Round A / Round B），審查輪只審不生,避免同一個 agent 自己生、自己審的橡皮圖章問題。
- **Workspace 鎖 + repo 級 git 鎖**：同一份需求不會被重複啟動;同 repo 不同需求並行跑,git commit 不互踩(見上節)。
- **跨專案總覽**：每次 run 結束自動 upsert 一行到 `~/.loop/index.md`（專案/repo/workspace/phase/stuck/狀態/時間），一人多專案好追蹤。

## 快速開始

**最快路徑**：把 `generators/bootstrap.md` 交給任何 agent(或 Claude Code 打 `/loop-prep`),
它會幫你做完下面的 0~2 步,做完就停下來等你貼指令。以下是它背後實際做的事、也可以自己手動走：

```bash
# 0) 框架放在固定位置（本資料夾就是；或 clone 到 ~/.loop/framework）
FW=<此框架路徑>

# 1) 在你的 code repo 初始化一個 workspace(=一份需求；建 .loop/<name>/、寫 framework_path、補 .gitignore)
python3 $FW/init-project.py /path/to/your-code-repo --name default
cd /path/to/your-code-repo            # ★所有引擎都從 repo 根目錄執行

# 2) 階段①：填好 .loop/default/REQUIREMENTS.md（或用 generators/0 互動訪談產出），人類確認

# 3) 一鍵跑（依 config.generation.mode；詳細輸出已直接印在這個終端機）
python3 $FW/engine/run.py                      # gated（預設）：生成收斂→停下交你 review
#   → review .loop/default/ 後執行：
python3 $FW/engine/run.py --stage execute      # 開始實作執行迴圈
#   或全自動：
python3 $FW/engine/run.py --mode auto          # 生成收斂後自動接執行
```
> 也可分開跑:`python3 $FW/engine/plan_loop.py`（只生成）/ `python3 $FW/engine/loop.py`（只執行）；
> 都吃同樣的 `--workspace`/`--quiet` 參數。想背景執行才需要 `tail -f .loop/default/{plan,loop}.log`。

## 核心原則（為什麼這樣設計）
- **文件即狀態**：換 agent / 換模型 / 中斷後，只靠 `.loop/` 就能接手。
- **不信單次**：收斂協定（獨立重推 + 連續 N 次一致）。
- **不會漏看**：列舉清單（分母）+ 行覆蓋 + 集合穩定收斂。
- **卡死有逃生門**：震盪偵測 → 三層升級 → FROZEN → 交人類。
- **Git 是安全網**：一輪一 commit（只在工作區）；框架唯讀、絕不寫入。
- **Context 防爆**：log 不進 context、CONTROL 保持決策最小集、不整批讀資料。
