# 🚀 GENERATOR — Bootstrap（前期準備總入口：開 workspace → 訪談需求 → 停在你跑 python 之前）

> **怎麼用**:這是整個 Loop Engineering 流程的**唯一進入點**。把這份檔案交給任何一個 agent
> (Claude Code、codex、opencode……皆可,本檔不假設特定 CLI),它會依序帶你完成「前期準備」——
> **開 workspace + 需求訪談 + 人類確認**——做完就**停下來**,把下一步的 python 指令交給你自己執行。
>
> ❗**本檔管轄的工作邊界**:agent 在這個流程裡**只允許執行一次性、快速的專案初始化指令**
> (`init-project.py` 或 `parallel.py add`,秒級完成);**絕對不允許**自己呼叫 `plan_loop.py` / `run.py` / `loop.py`
> ——那些是**長時間跑、會消耗大量模型用量的收斂迴圈**,必須由人類自己決定何時啟動。
> agent 做完前期準備後,任務就是把「你要自己貼上去跑的那一行指令」清楚印出來,然後結束。

---

## STEP 0｜確認框架與目標

問清楚(不確定就問,不要腦補):
1. **框架在哪**:`framework_path`(這份 bootstrap.md 所在的 `loop-engineering/` 目錄,或使用者指定的共享 clone 路徑,如 `~/.loop/framework`)。
2. **目標 code repo 在哪**:要被 agent 操作、產出落地的那個既有專案路徑。
3. **是否需要並行多工 (Parallel Multitasking)**:
   - 若使用者希望對同一個 repo **同時推進多個獨立任務**，必須採用 `git worktree`。請參閱 [並行多工指引](docs/parallel-multitasking.md)。
   - 確認要建立的分支名稱 (如 `loop/feat-x`)。
4. **這份需求的 workspace 名稱**:同一個 repo 可以開多份需求(`.loop/<name>/`),預設用 `default`;
   若是並行多工，預設取與分支名稱相同的名字 (如 `loop-feat-x`)。

## STEP 1｜執行專案初始化（唯一允許的 python，一次性、秒級）

根據 STEP 0 的並行需求，用你的 shell 工具執行(把 `<framework_path>` / `<repo>` / `<name>` / `<branch>` 換成確認的值):

- **一般單一任務初始化**：
  ```bash
  pip install -r <framework_path>/requirements.txt
  python3 <framework_path>/init-project.py <repo> --name <name>
  ```
  這只會安裝框架所需的依賴（如 PyYAML）並建立 `.loop/<name>/`(REQUIREMENTS/config 樣板 + `.gitignore`)。

- **並行多工初始化** (在主 repo 根目錄執行，會自動建立 worktree、切換分支並建立 workspace)：
  ```bash
  pip install -r <framework_path>/requirements.txt
  python3 <framework_path>/parallel.py add <branch> --name <name>
  ```
  ⚠️ **注意**：使用並行多工初始化成功後，請將接下來的指令執行目錄切換至新產生的 worktree 目錄下（例如：`cd ../<repo>-<sanitized-branch>`），再繼續下述步驟。

跑完專案初始化後馬上結束，安全。若單一任務初始化印出「= 已存在,略過」,代表這個 workspace 已經初始化過,跳過此步驟即可。

## STEP 2｜填寫 Agent 執行設定（人類決策點：CLI / 模型）

問清楚(不確定就問,不要腦補):
1. **使用哪個 CLI** 來跑 agent(Claude Code / opencode / gemini-cli / codex…),對應到
   `agent.build_cmd`(模板預設 `opencode run -m {model} {prompt}`;`{model}`/`{prompt}` 佔位依所選 CLI 的實際語法調整位置)。
2. **三個模型層**(`agent.models.fast / normal / thinking`)——分別用在「葉子執行 / Git Review Gate」
   「主要 Execute / Plan」「卡關升級的高階模型」,照所選 CLI 支援的模型名稱填上實際值。

把這兩項直接寫進 STEP 1 剛建好的 `<repo>/.loop/<name>/loop.config.yaml` 的 `agent:` 區塊,
覆蓋 `build_cmd` 與 `models.fast/normal/thinking` 的佔位值。

⚠️ **這一步必須在這裡(由人類)完成,不能留給階段②生成規劃書的 agent 事後填**——
`engine/plan_loop.py` 啟動時的 preflight 健檢會檢查 `agent.models.*` 是否仍是佔位值,
若是會直接擋下(回傳錯誤、不進入規劃迴圈),所以規劃 agent 根本沒有機會先跑起來再補填。

## STEP 3｜需求訪談

依 `0-requirements-interview.md` 的問題清單,**一組一組問清楚**(不要一次轟炸),把答案寫進
`.loop/<name>/REQUIREMENTS.md`(STEP 1 已建好樣板,照填即可;`templates/REQUIREMENTS.template.md` 是其來源)。
過程中注意:
- 若輸入資料很大(大檔/大量項目)→ 標記「需要大範圍防漏協定」,留給階段②的生成器處理。
- 提醒使用者:之後的執行階段**不會把資料整批讀進 context**;完整性靠列舉清單 + 行覆蓋。

## STEP 4｜人類確認需求（停止點之一）

把寫好的 `REQUIREMENTS.md` 完整內容(或摘要)念給使用者確認**逐條需求**是否正確、有無遺漏。
使用者確認後,在檔案標記 **REQUIREMENTS CONFIRMED(日期/確認人)**。
**未確認前不要往下走**——尤其不要自己接著去跑生成規劃書。

## STEP 5｜停下來，把下一步指令交給人類

需求確認後,**到此為止**。輸出大致像這樣的收尾訊息(依實際路徑/workspace 名稱替換):

```
✅ 前期準備完成：.loop/<name>/REQUIREMENTS.md 已確認。

接下來是「生成規劃書」與「執行」——這兩段都是會持續跑到收斂為止的 python 迴圈，
請你自己決定何時啟動：

  cd <repo>
  python3 <framework_path>/engine/run.py --workspace <name>

  · 預設 gated 模式：規劃書生成收斂後會停下來等你 review，你 review 完再跑：
      python3 <framework_path>/engine/run.py --workspace <name> --stage execute
  · 想全自動可加 --mode auto。

我不會自己執行這個指令。
```

❌ **不要**自己呼叫 `plan_loop.py`、`run.py`、`loop.py`，也不要建議用背景/nohup 方式偷跑——
這是刻意的人類決策點,不是技術限制。

---

## 給「人」的使用說明（非 agent 指令，供你自己參考）
1. 開一個全新 agent session(任何 CLI 都行),貼上這份 `bootstrap.md` 全文 + 你的初步想法(一兩句話也行)。
2. agent 會問你問題、帶你把 STEP 0~4 走完,最後印出指令給你。
3. 你看過指令、確認沒問題後,**自己貼上去跑**——之後就是 `run.py` 接手反覆觸發、直到收斂或交人類裁決。
