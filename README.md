# 🔁 loop-engineering — 通用 Loop Engineering Agent 框架

把「**做不完、信不過、會中斷、會卡死**」的大任務,交給一個「由 AI agent 反覆執行、直到收斂達標」的迴圈。
你只要**給需求、把關兩個決策點**;其餘交給迴圈自己跑到收斂、卡死了才回頭找你。

> 框架是**共享、唯讀**的:它只被讀取,所有要改的東西(規劃書 + code)都落在你的 **code repo** 的 `.loop/<name>/`。
> 這份 README 只講「人會在意的」;運作細節、每輪防護、收斂協定都在 `rules/`,需要時叫你的 agent 去讀即可。

---

## 🤖 給 agent 的速覽（使用者只說「讀這份 README 然後開始」時，你看這段就好）
1. 讀 `generators/bootstrap.md` 全文——這是**唯一、不分 CLI** 的進入點(Claude Code / gemini-cli / opencode / codex 皆適用)。
2. 依它做:確認 `framework_path` / 目標 code repo / workspace 名稱 → 跑一次性的 `init-project.py` → 訪談需求 →
   人類確認 → **停下來**,把下一步的 `run.py` 指令交給人類自己貼上去跑。
3. ❗**絕不要**自己接著跑 `plan_loop.py` / `run.py` / `loop.py`——那是會跑到收斂為止的長迴圈、會燒用量,
   啟動與否是刻意保留給人類的決策點,不是技術限制。

---

## 給人類：你需要知道的

**怎麼運作(三段)**:① 你提供需求 → ② 規劃迴圈([plan_loop.py](engine/plan_loop.py))把規劃書跑到收斂 →
③ 執行迴圈([loop.py](engine/loop.py))反覆喚醒全新 agent 做到達標。中途卡死/震盪會自動升級模型,真的卡住才停下交你。

**你只有兩個決策點(human gate)**:
1. **確認需求**——agent 訪談完、產出 `REQUIREMENTS.md`,你確認。
2. **review 規劃書**(只在 gated 模式)——規劃收斂後停下,你看過 `.loop/<name>/` 的 `loop.config.yaml` / `state.json` / `phases/` 再放行執行。

**你要選 gated 還是 auto**:
- **gated(預設,建議)**:規劃收斂後**停下交你 review**,確認後你再手動跑執行。
- **auto**:規劃收斂後**自動接執行**,一路到達標(中途靠震盪偵測 / 三層升級 / 交人自保)。

**一次只跑一個**:同一個 code repo 不要同時跑兩個 loop(會直接改 `src/`,邏輯互蓋);要換另一份需求,等前一個停了再跑。

---

## 怎麼開始

最省事:把 `generators/bootstrap.md` 交給你的 agent,它會幫你開 workspace、訪談需求,
**停在你該跑 python 之前**。以下是它背後實際做的事,也可以自己手動走:

```bash
FW=<此框架路徑>
pip install -r $FW/requirements.txt        # 安裝依賴(如 PyYAML)

# 1) 在你的 code repo 開一個 workspace(=一份需求)
python3 $FW/init-project.py /path/to/your-code-repo --name default
cd /path/to/your-code-repo                  # ★引擎一律從 code repo 根目錄跑

# 2) 填好 .loop/default/REQUIREMENTS.md(或讓 agent 訪談產出),你確認

# 3) 跑
python3 $FW/engine/run.py                    # gated(預設):規劃收斂 → 停下交你 review
python3 $FW/engine/run.py --stage execute    #   review 完,手動接執行迴圈
python3 $FW/engine/run.py --mode auto        # 或全自動:規劃收斂後直接接執行
```
> **`--mode`**(兩種):`gated` / `auto`。
> **`--stage`**(執行哪一段):`all`(預設)/ `plan`(只生成)/ `execute`(只執行,gated review 完用這個)/ `reject`(樹模式局部重拆)。
> **多份需求**:`init-project.py --name featureB` 再開一個,各自 `run.py --workspace featureB`(但別同時跑)。
> 詳細輸出已直接印在終端機;背景執行才需要 `tail -f .loop/<name>/{plan,loop}.log`。

---

## 完整流程圖（從 init-project 到收斂）

> 上面是高層次概念;這張圖把「實際會跑的指令、人類 gate 的位置、執行迴圈裡每輪疊了什麼防護」全部展開,
> 方便第一次上手對齊心智模型。(機制細節在 `rules/`,這裡只給全貌。)

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
│   產出：state.json / phases/ / loop.config.yaml              │
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
        ║  loop.config.yaml /    ║   │
        ║  state.json / phases/  ║   │
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

---

## 其他你可能在意的

- **要參考另一個專案的 code?**(如把舊專案 API refactor 進新專案):loop 只看得到被改的那個 repo。把來源用
  `git worktree add ./.loop/<name>/inputs/old HEAD` 掛成**唯讀輸入**、`.gitignore` 掉、用完 `git worktree remove`。
  (細節讓 agent 讀 `generators/0-requirements-interview.md` 的跨專案段帶你做。)
- **需要同時推進多個並行任務？** 同一個工作目錄限制一次只能跑一個 loop；若想「同時」跑多個 loop，請用 `git worktree`。詳細流程見 [並行多工指引](docs/parallel-multitasking.md)。
- **東西放哪**:規劃書 / 狀態 / log 都在 code repo 的 `.loop/<name>/`;產出落 code repo。框架本身唯讀、絕不被寫入。
- **跨專案總覽**:每次跑完自動更新 `~/.loop/index.md`(專案 / phase / 狀態 / 時間),一人多專案好追蹤。

---

## 想深入（多半是讓 agent 去讀）

- **為什麼這樣設計**(九大原則、反模式):[`rules/BLUEPRINT.md`](rules/BLUEPRINT.md)
- **運作細節 / 每輪防護 / 收斂與防漏協定**:[`rules/`](rules/)(boot-sequence、convergence、completeness、oscillation-escalation、git-safety、git-review-gate、context-budget…)
- **agent 入口 / 前期準備一條龍**:[`generators/bootstrap.md`](generators/bootstrap.md)
