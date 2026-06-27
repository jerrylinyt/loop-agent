# Dashboard 完善需求規格

> 給實作 agent 的工作說明書。目標：把 `dashboard/` 這個 FastAPI + 單頁 HTML 控制台從「半成品」補成可日常使用的工具。
>
> **語言**：UI 文案沿用現有風格（中英混用皆可，與既有按鈕一致即可）；程式碼識別字一律英文。
> **不要破壞**：現有 API 路徑與 `index.md` / `CONTROL.md` / `TREE.md` 的檔案格式都是引擎共用契約，除非本規格明說，否則不可更改既有欄位語意。

---

## 0. 背景與現有架構

- **後端**：[`dashboard/app.py`](../dashboard/app.py) — FastAPI，無資料庫，所有狀態都來自檔案系統。
- **啟動器**：[`dashboard/main.py`](../dashboard/main.py) — 用 `subprocess` 起 `uvicorn` 並開瀏覽器。
- **前端**：[`dashboard/templates/index.html`](../dashboard/templates/index.html) — 單一檔案，Tailwind via CDN，原生 JS，無建置步驟。**保持無建置**（不要引入 npm/bundler）。
- **資料來源**：
  - 專案總覽：`~/.loop/index.md`（Markdown 表格，欄位：`專案 | repo | workspace | phase | stuck | 狀態 | 更新`）。
  - 每個 workspace 即時狀態：`<repo>/.loop/<ws>/CONTROL.md`（YAML-in-Markdown，用 `key: value` 行）。
  - 規劃樹：`<repo>/.loop/<ws>/TREE.md`。
  - Log：`<repo>/.loop/<ws>/loop.log`、`plan.log`。
  - 執行鎖：`<repo>/.loop/<ws>/.loop_state/run.lock`，內容固定為 `pid=<pid> started=<YYYY-MM-DD HH:MM:SS>`（見 [`engine/utils.py:42`](../engine/utils.py)）。
  - 設定：`<repo>/.loop/<ws>/loop.config.yaml`。
- **引擎進入點**：`engine/run.py`，重要參數：
  - `--workspace <name>`
  - `--mode {auto, gated}`
  - `--stage {all, plan, execute, reject}`（`reject` 需搭配 `--subtree <node_id>`）

### CONTROL.md 可讀欄位（單一事實來源）
實作時用既有的 [`get_control_val()`](../dashboard/app.py:53) 逐行解析即可。可用欄位（見 `.loop/generators/templates/CONTROL.template.md`）：

```
current_phase, stuck_level, human_required, stop_condition_met,
last_round_mode, last_round_result, last_round_fail_tasks,
rounds_since_progress, current_model_tier, enhanced_rounds_used,
blocking_issues, plan_version,
# 每個 phase 一組（id 對應 config.phases）：
p{id}_consecutive_pass, p{id}_total_validations, p{id}_last_result
```

---

## 1. 範圍與優先級

分三批，**A 必做、B 必做、C 視時間**。每項都有「驗收標準」，請逐項對照。

| 批次 | 項目 |
|------|------|
| **A. 修 bug** | A1 log 補歷史、A2 殭屍 lock 可清、A3 用 `sys.executable` 並保留錯誤輸出 |
| **B. 補工作流** | B1 human_required 原因 + Resume、B2 啟動模式選擇、B3 CONTROL 狀態總覽、B4 untrack 專案 |
| **C. 體驗** | C1 增量更新不閃爍、C2 log 搜尋/下載/上限、C3 全域總覽列 |
| **D. 新功能（追蹤體驗）** | D1 瀏覽器通知、D2 活動時間軸、D3 進度趨勢、D4 心跳/執行時長、D5 Diff 檢視、D6 多專案即時總覽、D7 規格檢視、D8 卡住預警、D9 Phase 進度條 |

---

## A. 修 bug（最高優先）

### A1. 打開 log 要先顯示歷史，再接續即時串流
**現況**：[`log_generator()`](../dashboard/app.py:433) 直接 `f.seek(0, os.SEEK_END)`，只 tail 之後的新行。結果：專案沒在跑時打開 log 一片空白；剛打開也看不到先前內容。

**需求**：
- 連線後先送出檔案「最後 N 行」（預設 `N=500`，可由 query string `?tail=N` 覆寫），再進入即時 follow。
- 大檔不要整檔讀進記憶體；用「從檔尾往回讀 block」或 `collections.deque(f, maxlen=N)` 等有界做法。
- 維持現有 SSE 格式：每行 `data: <line>\n\n`。歷史與即時之間送一行分隔，例如 `data: --- end of history (live) ---\n\n`。
- 檔案不存在時：送一行提示而非直接斷線（沿用現有行為）。

**驗收**：對一個有歷史 log、未在執行的專案打開 Live Logs，立即看到最後數百行；之後若有新行會即時追加。

### A2. 殭屍 / 殘留 lock 要能清除，且 Start 不再靜默失敗
**現況**：
- [`parse_index()`](../dashboard/app.py:106) 只要 `run.lock` 存在就視為 `is_running=True`；pid 已死才改回 `False`，但 **lock 檔仍留著**。
- 引擎 `acquire_run_lock()`（[`engine/utils.py:27`](../engine/utils.py)）對「存在且 age < stale_seconds」的 lock 會丟 `WorkspaceBusy` 並結束。
- 因此：pid 已死但 lock 還在 stale 視窗內 → 使用者按 Start，引擎開起來立刻因 lock 衝突退出，而 stdout 被導到 DEVNULL（見 A3）→ **完全沒有回饋、也起不來**。

**需求**：
1. `parse_index()` 對每個 lock 計算 `stale`：pid 不存在 / 非執行中 / zombie → `is_running=False` 且標記 `stale_lock=True`。在回傳的 `ProjectStatus` 增欄位 `stale_lock: bool`。
2. 新增端點 **`POST /api/projects/{proj_id}/clear-lock`**：刪除該 workspace 的 `run.lock`（若存在），回 `{"status": "cleared"}`；找不到專案 404。
3. 前端：當 `stale_lock` 為真且未在執行，在該專案卡片 / 詳情頁顯示「⚠️ Stale lock」提示與一顆「Clear Lock」按鈕，呼叫上述端點後刷新。
4. （建議）`start_project()` 啟動前，若偵測到 `stale_lock`，可先自動清除再啟動，避免使用者要點兩次；但仍保留手動 Clear Lock 入口。

**驗收**：手動建立一個指向死 pid 的 `run.lock`，dashboard 顯示 stale 並提供 Clear Lock；清除後可正常 Start。

### A3. 用 `sys.executable`，並保留子程序的錯誤輸出
**現況**：[`start`](../dashboard/app.py:172)、[`init`](../dashboard/app.py:192)、[`reject`](../dashboard/app.py:423) 都用 `["python", ...]`，會跳出目前 venv 抓到系統 Python；且 `start`/`reject` 把 `stdout`/`stderr` 導到 `DEVNULL`，啟動失敗時毫無痕跡。

**需求**：
1. 三處 `subprocess` 的執行檔一律改成 `sys.executable`（`import sys`）。
2. **背景型**（`start`、`reject`，用 `Popen`）：把 `stdout`/`stderr` 導向檔案而非 DEVNULL，建議寫到 `<repo>/.loop/<ws>/.loop_state/spawn.log`（append 模式）。這樣引擎若在進入主迴圈前就崩潰（例如 lock 衝突、import 失敗），仍有蹤跡可查。
3. **同步型**（`init`，用 `run(capture_output=True)`）：維持把 stderr/stdout 回傳給前端的行為即可。

**驗收**：在缺套件或 lock 衝突情境下按 Start，`spawn.log` 內能看到對應錯誤訊息。

---

## B. 補關鍵工作流（高優先）

### B1. human_required：顯示原因並提供 Resume
**現況**：引擎會在「核心狀態檔毀損且無法自動修復」「人機衝突」「互卡需裁決」「Git Review Gate 判定需人介入」等情況把 `human_required` 設為 `true` 並停機（見 [`engine/loop.py`](../engine/loop.py) 多處）。原因只寫進 `loop.log`，dashboard 只亮一個黃 badge，使用者不知道發生什麼、也沒有「處理完，繼續」的入口。

**需求**：
1. **抓原因**：新增端點 **`GET /api/projects/{proj_id}/human-context`**，回傳 `human_required` 是否為真，以及「最近一段相關原因」。原因來源：掃 `loop.log` 反向找最後一個含 `human_required` 或 `🧑‍⚖️` 的區段（抓該行與其後幾行），回 `{"human_required": bool, "reason": "<文字>", "log_excerpt": "<多行>"}`。找不到原因時 `reason` 給空字串。
2. **前端**：當狀態為 `human_required`，在詳情頁頂部顯示一個醒目的橫幅（黃底），內含 reason / log_excerpt，並提供兩顆按鈕：
   - **「I've handled it — Resume」**：呼叫下方 Resume 端點。
   - **「Open loop.log」**：切到 Live Logs tab。
3. **Resume 端點** **`POST /api/projects/{proj_id}/resume`**：
   - 前置：專案必須未在執行（有 lock 就擋，回 400）。
   - 動作：把 CONTROL.md 的 `human_required` 設回 `false`（用既有寫檔工具；可參考 `engine/state.py` 的 set_val 模式，或直接做一個只改這一個 key 的安全寫入），然後以該專案上次的 mode（讀 `last_round_mode`，預設 `auto`）重新 `start`（等同呼叫 start_project 的 spawn 流程）。
   - 回 `{"status": "resumed"}`。
   - **注意**：只負責把旗標放下並重啟迴圈；實際狀態檔的修復是使用者線下做的，dashboard 不嘗試自動修。

**驗收**：手動把某 workspace 的 `human_required` 設為 `true`，dashboard 顯示橫幅與 log 摘要；按 Resume 後旗標歸 false 且引擎重新啟動。

### B2. 啟動模式選擇（auto / gated / 各 stage）
**現況**：UI 只有「Start (Auto)」，但引擎支援 `--mode {auto,gated}` 與 `--stage {all,plan,execute,reject}`。

**需求**：
1. 擴充 [`StartRequest`](../dashboard/app.py:33)：`mode: str = "auto"` 已有，新增 `stage: str = "all"`。`start_project()` 把 `--stage` 一併傳入（`reject` 不在此端點處理，維持走既有 `/reject`）。
2. 後端對 `mode`/`stage` 做白名單驗證（`mode ∈ {auto,gated}`、`stage ∈ {all,plan,execute}`），非法回 400。
3. 前端把單一 Start 按鈕改成「主按鈕 + 下拉」或一排小按鈕，至少提供：
   - **Start (Auto)** → mode=auto, stage=all
   - **Start (Gated)** → mode=gated, stage=all
   - **Plan only** → stage=plan
   - **Execute only** → stage=execute
4. 文案旁可加一行極簡說明（gated = 每階段人工把關）。

**驗收**：可從 UI 觸發 gated 模式與 plan-only，`spawn.log` / 行為符合對應參數。

### B3. CONTROL 狀態總覽 tab（把 CONTROL.md 的豐富狀態露出）
**現況**：詳情頁只有 phase / stuck / status 三格，CONTROL.md 裡的 per-phase 進度、blocking_issues、model tier、收斂計數全藏著。

**需求**：
1. 新增端點 **`GET /api/projects/{proj_id}/control`**，解析 CONTROL.md 回結構化 JSON：
   ```json
   {
     "current_phase": "1",
     "stuck_level": "0",
     "current_model_tier": "default",
     "enhanced_rounds_used": "0",
     "rounds_since_progress": "0",
     "blocking_issues": "0",
     "stop_condition_met": false,
     "human_required": false,
     "last_round_mode": "auto",
     "last_round_result": "...",
     "last_round_fail_tasks": "...",
     "plan_version": "1",
     "phases": [
       {"id": "1", "consecutive_pass": "3", "total_validations": "5", "last_result": "PASS"}
     ]
   }
   ```
   - `phases` 的偵測方式：掃 CONTROL.md 找所有 `p{id}_consecutive_pass` 形式的 key，蒐集出現過的 `{id}`，再各自讀三個欄位。
   - CONTROL.md 不存在時回 `{}` 或合理空結構（前端要能容錯）。
2. 前端新增一個 **「Overview / 狀態」tab**（放在 Live Logs 之前或之後皆可），用卡片 + 小表格呈現上述資訊。per-phase 用一張表：Phase / Consecutive Pass / Total Validations / Last Result，pass 數可配門檻（門檻可暫時不顯示，或之後從 config 讀）。
3. 此 tab 跟著既有 5 秒輪詢更新（或 B/C 後改增量更新）。

**驗收**：打開 Overview tab 能看到目前 phase、各 phase 收斂計數、stuck level、model tier、blocking issues。

### B4. 移除 / untrack 專案
**現況**：能 Init / Track，但無法從 dashboard 移除一筆。

**需求**：
1. 新增端點 **`DELETE /api/projects/{proj_id}`**（或 `POST /api/projects/{proj_id}/untrack`）：
   - 只從 `~/.loop/index.md` 移除對應那一列（用 `repo_path` + `workspace` 比對，與 [`add_project`](../dashboard/app.py:261) 既有比對邏輯一致）。
   - **絕對不要**刪除 repo 內的 `.loop/` 任何檔案——這只是「不再追蹤」，不是「刪除工作區」。UI 文案要講清楚。
   - 若專案正在執行，擋下並回 400（要先 Stop）。
2. 前端：在專案卡片右上提供一個小「✕ / Untrack」入口，需二次確認。

**驗收**：untrack 後該列從 index.md 與列表消失，但 repo 內 `.loop/` 檔案原封不動。

---

## C. 體驗打磨（視時間做）

### C1. 增量更新，不要整列重繪
**現況**：[`fetchProjects()`](../dashboard/templates/index.html:307) 每 5 秒 `innerHTML=''` 重建整個列表，且 `selectProject` 內也呼叫它 → 閃爍、掉 scroll、滑鼠 hover 中斷。

**需求**：改成 diff 更新——只更新有變動的卡片內容（badge / phase / stuck），不重建未變動的 DOM 節點。維持每 5 秒輪詢即可（不需引入 websocket）。

### C2. Live Logs：搜尋 / 下載 / 行數上限
**現況**：log 以 `appendChild` 無上限堆 div，長跑會吃記憶體；不能搜尋、不能下載原始檔。

**需求**：
- 前端保留最多 M 行（預設 2000），超過時砍最舊的 DOM 節點。
- 加一個過濾輸入框：即時隱藏不含關鍵字的行（純前端）。
- 加「Download」：可直接下載 `loop.log` / `plan.log` 原始檔（後端加一個 `GET .../logs/{type}/download` 回 `FileResponse`，或前端組整檔請求）。

### C3. 全域總覽列
**需求**：在頁面頂部加一條彙總：總專案數、執行中數、Action Needed 數、Complete 數。資料用既有 `/api/projects` 算即可，不需新端點。

---

## D. 新功能：讓「追蹤」更省力（建議分批導入）

> 這批是「新增價值」而非「補洞」。每項標注**可行性**：✅ 純 dashboard 就能做；⚠️ 需引擎側配合（會額外標出引擎需求）。
> 優先序建議：**D4 → D1 → D2 → D8** 最快見效（都便宜且直接改善「不用一直盯著看」的體驗），D5 / D9 次之，D3 最後（要引擎配合）。

### D1. 瀏覽器桌面通知（✅ 高價值）
**動機**：這是一個會自己跑很久的 autonomous loop，使用者不該一直盯著畫面。狀態變化應主動推播。
**需求**：
- 前端用 Web Notification API（首次進站要求授權）。輪詢時比對每個專案的前後狀態，於下列「轉換」時推播：
  - `→ human_required`（需介入）— 最重要
  - `→ complete / done`（完成）
  - `→ FAIL` 或 `stuck_level` 升高（卡住）
- 通知文案：`<repo>/<ws>: Action needed`（點擊聚焦該專案）。
- 提供開關（localStorage 記住）讓使用者關掉。
- 不需要新後端；資料用既有 `/api/projects` 輪詢結果即可。

### D2. 活動時間軸（✅ 把 raw log 變成人看得懂的里程碑）
**動機**：loop.log 很吵；使用者要的是「發生了哪些大事」。引擎已用固定 emoji 標記里程碑。
**需求**：
- 新增端點 **`GET /api/projects/{id}/activity?limit=N`**：反向掃 `loop.log`，用標記抽取事件，回結構化清單：
  | 標記（出現在 log） | 事件類型 |
  |---|---|
  | `✅ ... LOOP COMPLETE` / `TREE EXECUTE COMPLETE` | `complete` |
  | `🚨 [Git Review Gate] 發現...改動` | `review_revert` |
  | `⛔ ... 停下交人類` | `human_required` |
  | `⬆ / ⬆⬆ ... 升級模型` | `model_upgrade` |
  | `↩ 有進展` | `progress` |
  | `🍃 葉子 [...] 收斂` | `leaf_converged` |
  - 回傳 `[{ "ts": "...", "type": "review_revert", "text": "<原行>" }]`（ts 若 log 行首有時間戳就帶上，沒有就留空）。
- 前端在 Overview tab（B3）下方或獨立 tab，用帶顏色圓點的垂直時間軸呈現，最新在上。
- **實作提醒**：把「標記 → 類型」的對應表集中成一個 dict，方便日後引擎新增標記時擴充。

### D3. 進度趨勢圖（⚠️ 需引擎配合，已另有 spec）
**動機**：一眼看出「在進步還是在原地打轉」。
**需求**：
- **引擎側**：每輪 append 一行到 `<repo>/<ws>/.loop_state/rounds.jsonl` —— 完整欄位、寫入點、邊界與驗收見獨立規格 [`engine-rounds-history.md`](engine-rounds-history.md)。
- **dashboard 側**：加 `GET /api/projects/{id}/rounds?limit=N`，讀該檔最後 N 行、逐行 `json.loads`（壞行跳過）回陣列；前端用極簡 inline SVG 畫 sparkline（`stuck_level` 隨序變化、`result`/`progressed` 標點）。欄位名是兩端契約，調整需同步那份 spec。
- 過渡做法（引擎還沒做時）：先從 loop.log 解析輪次與 stuck 變化，精度較差但可先有東西看。

### D4. 心跳與執行時長（✅ 最便宜、最直接）
**動機**：使用者最常問的是「它還活著嗎？跑多久了？」
**需求**：
- `parse_index()`（或新端點）對執行中的專案，從 `run.lock`：
  - mtime → 算 `last_heartbeat_seconds_ago`（引擎長跑會 `touch_run_lock` 更新心跳）。
  - 內容的 `started=` → 算 `running_for`（執行時長）。
- 在 `ProjectStatus` 增 `started_at`、`heartbeat_age`（秒）兩欄。
- 前端：執行中的卡片顯示「⏱ running 12m · ♥ 3s ago」。若 `heartbeat_age` 超過門檻（例如 > round_timeout）轉紅，提示「可能卡死」。

### D5. Diff 檢視（✅ 建立信任）
**動機**：autonomous agent 一直在改檔，使用者想知道「這輪到底改了什麼」。`last_safe_sha` 已存在。
**需求**：
- 新增端點 **`GET /api/projects/{id}/diff`**：在該 repo 跑 `git diff <last_safe_sha> HEAD`（`last_safe_sha` 讀 `<repo>/<ws>/.loop_state/last_safe_sha`；不存在則 `git diff HEAD~1 HEAD` 或回空）。回 `{"base": sha, "head": sha, "diff": "<unified diff 文字>"}`。對超大 diff 設上限（例如截斷到數百 KB 並標示）。
- 前端：新 tab「Changes」，用等寬字體 + 簡單的 +/- 上色呈現（純前端字串上色即可，不必引入 diff 套件）。
- **安全**：只讀，不執行任何寫入或 checkout。

### D6. 多專案即時總覽頁（✅ 規模化時必要）
**動機**：專案一多，逐個點進去看很慢。
**需求**：在現有側欄 / 主畫面之外，提供一個「Overview / Grid」模式：所有專案以小卡格狀排列，每格顯示 repo/ws、狀態 badge、phase、stuck、心跳。執行中的會即時跳動。點任一格進入詳情。資料用既有 `/api/projects`。可與 C3 的彙總列整合。

### D7. 規格與節點內容檢視（✅ 補上 tree 的最後一塊）
**動機**：目前 tree 只看得到 metadata，看不到「這個節點實際要做什麼」。
**需求**：
- 端點 **`GET /api/projects/{id}/doc?path=<相對路徑>`**：白名單只允許讀該 workspace 內的 `REQUIREMENTS.md`、`phases/PHASE*.md`、`tree/*.decomp.md`（**嚴格限制在 `<repo>/.loop/<ws>/` 底下，需 `os.path.realpath` 防穿越**），回 Markdown 原文。
- 前端：tree 節點詳情頁（B 已有的 Node Details）加「View Spec」按鈕，開該節點的 `*.decomp.md`；專案層級加入口看 `REQUIREMENTS.md`。用任意輕量 md 渲染或直接 `<pre>` 顯示皆可。

### D8. 卡住 / 震盪預警（✅ 便宜的提早警示）
**動機**：在升級到 `FROZEN` / `human_required` 之前就讓使用者注意到。
**需求**：前端依 `stuck_level`、`rounds_since_progress`、`enhanced_rounds_used`（B3 的 control 端點已提供）做漸進式視覺警示：0 正常、1 黃、≥2 橙、FROZEN 紅 + 圖示。在卡片與詳情頁都呈現。可搭配 D1 在跨越門檻時推播一次。

### D9. Phase 進度條（✅ 把抽象計數變直覺）
**動機**：`p{id}_consecutive_pass: 3` 這種數字對人不直覺。
**需求**：從 `loop.config.yaml` 讀各 phase 的收斂門檻（`config.phases[].threshold` 或對應欄位，實作前先看 config 結構），在 B3 的 per-phase 表把 `consecutive_pass / threshold` 畫成進度條（例如 3/5 = 60%）。門檻讀不到時退回顯示純數字。

---

## 跨項目通用要求（請務必遵守）

1. **無建置前端**：繼續用單一 `index.html` + Tailwind CDN + 原生 JS。不要引入打包工具。
2. **檔案格式契約**：`index.md` / `CONTROL.md` / `TREE.md` / `run.lock` 是與引擎共用的契約。改寫 CONTROL.md（B1 的 Resume）時只能改目標 key，**不可重排 / 破壞其他行**——Git Review Gate 會把破壞狀態檔的改動判 REVERT（見 [`rules/git-review-gate.md`](../rules/git-review-gate.md)）。
3. **錯誤回饋**：所有新端點失敗時回有意義的 `HTTPException(detail=...)`，前端 `alert` 或 inline 顯示，不要靜默吞掉。
4. **路徑安全**：所有 repo / workspace 路徑都來自 index.md（受信任），但新端點仍要對 `proj_id` 找不到時回 404，對非法 `mode/stage/log_type` 回 400。
5. **不阻塞事件迴圈**：SSE / 串流維持 async；同步重 IO 放背景或用既有模式。
6. **Pydantic 模型**：`ProjectStatus` 新增欄位（如 `stale_lock`）記得同步更新 model，否則 `response_model` 會濾掉。

---

## 建議實作順序與驗證

1. 先做 **A1 / A2 / A3**（互相獨立，可平行），各自用上面的「驗收」手動驗。
2. 再做 **B1 → B2 → B3 → B4**。B1 與 B3 都會用到 CONTROL.md 讀取，可共用 helper。
3. **C** 最後做，純前端為主。

每完成一批，啟動 dashboard（`python -m dashboard.main` 或 `python dashboard/main.py`）以本 repo（已在 index.md）為對象手動點過一遍。能補 pytest 更好（後端解析函式如 CONTROL 解析、stale lock 判定都好測），但非硬性要求。

---

## 附錄：現有 API 一覽（實作前先讀懂）

| Method | Path | 用途 |
|--------|------|------|
| GET | `/api/projects` | 列出所有專案（來自 index.md + CONTROL.md 即時覆寫） |
| POST | `/api/projects/{id}/start` | 啟動引擎（目前僅 auto/all） |
| POST | `/api/projects/{id}/stop` | kill pid + 清 lock |
| POST | `/api/projects/init` | 跑 init-project.py 並寫入 index.md |
| POST | `/api/projects/add` | 把既有 workspace 加進 index.md |
| GET/POST | `/api/projects/{id}/config` | 讀 / 存 loop.config.yaml（存檔有 YAML 驗證） |
| GET | `/api/projects/{id}/tree` | 解析 TREE.md 回節點圖 |
| POST | `/api/projects/{id}/reject` | reject 子樹並重新規劃 |
| GET | `/api/projects/{id}/logs/{type}` | SSE 串流 loop/plan log |
| GET | `/` | 回 index.html |

**本規格將新增**：
- B/A 批：`clear-lock`、`human-context`、`resume`、`control`、untrack(`DELETE`)、logs `download`，並擴充 `start`（stage）與 `ProjectStatus`（stale_lock）。
- D 批：`activity`、`rounds`（需引擎吐 rounds.jsonl）、`diff`、`doc`，並擴充 `ProjectStatus`（`started_at`、`heartbeat_age`）。
