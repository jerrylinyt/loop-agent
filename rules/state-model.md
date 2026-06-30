# 🎚️ RULE — 狀態模型與流程控制（通用、N 階段、config 驅動）

> **唯讀框架規則**。引擎與 agent **共同遵循這份定義**。
> 不出現 any 字面階段數；一切以 `loop.config.yaml.phases`(N 筆，最後一筆=最終階段)表達。

## 1. 狀態控制（state — 活在 state.json，單一事實來源）

> 原則 2:文件即狀態。所有的執行狀態（變數、計數器、任務狀態表、Issue 索引、樹節點拓撲）全數存儲於 `.loop/state.json`。
> 任何 Agent 均**嚴禁手動編輯**狀態檔案本體（`state.json`），必須一律使用系統提供的 `state.py` CLI 寫入。
> 人類要查看狀態，請直接打開專案附帶的 Web Dashboard 網頁。


通用狀態欄位（存在於 `state.json` 中）：
- `current_phase`：指向當前階段 ID。
- `p{id}_consecutive_pass`：連續通過全量驗證次數。
- `p{id}_total_validations`：總驗證次數。
- `p{id}_last_result`：PASS / FAIL。
- `blocking_issues`：由引擎重算（`OPEN` 且 `BLOCKING` 的 Issue 數量）。
- `plan_version`：規劃書版本。
- `framework_ref`：當前框架快照。
- `control` 物件：包含 `last_round_mode`、`last_round_result`、`last_round_fail_tasks`、`rounds_since_progress`、`stuck_level`、`current_model_tier`、`enhanced_rounds_used`、`human_required` 等運行狀態。

### 設定 vs 狀態
- **門檻 / 階段定義 / 停止條件** = **設定** → `loop.config.yaml`，不放 `state.json`。
- **活計數器** = **狀態** → `state.json`。


---


---

## 3. 流程控制（flow — 引擎 + boot 共同驅動，全 config化）

| 機制 | 通用判準（config 驅動） | 由誰執行 |
|------|------------------------|---------|
| **BOOT SEQUENCE** | STEP G→10：一輪【只做一個任務/一次驗證】，STEP 10 後 agent 結束並交回控制權；更新狀態使用 CLI 寫入 | agent |
| **Phase Gate (平模式)** | 相鄰階段 i→i+1：`phase i 全 CONVERGED 且 p{i}_pass>=門檻 且 blocking==0` | 引擎 + agent |
| **停止(正常)** | `current_phase==最後階段 且 最後階段全任務 CONVERGED 且 p{last}_pass>=final_phase_pass_gte 且 blocking==0` | 引擎 |
| **停止(交人類)** | `human_required==true` | 引擎 |

---

## 4. 引擎讀寫狀態的方式

- 引擎透過呼叫 `state.py` 讀寫 `state.json`。

---

## 5. 狀態變更剛性約束與防護（非法操作防護）

為確保狀態變更安全無虞，`state.py` 內建了多重的剛性校驗。任何違反以下規則的 CLI 操作均會被拒絕並報錯（回傳 exit code 1）：

### 5.1 鍵值白名單與類型約束 (Key & Type Whitelist)
- **寫入白名單限制**：使用 `set` 或 `incr` 更新欄位時，鍵值 (Key) 必須位於預設的白名單中（包含 `current_phase`、`last_round_mode`、計數器欄位如 `p{id}_consecutive_pass` 等）。未在白名單內之鍵值將被拒絕變更。
- **數值遞增限制**：`incr` 指令僅適用於數值型鍵值（如 `consecutive_pass`、`total_validations`、`rounds_since_progress`、`stuck_level` 等）。非數值型欄位執行 `incr` 將報錯。

### 5.2 狀態轉換守衛 (Guarded Transition)
每次寫入時，系統會對寫入前後的變更進行「守衛驗證」：
- **交接人類旗標保護**：`human_required` 與 `plan_human_required` 一旦被設定為 `true`，**嚴禁**直接透過 `set` 修改回 `false`。必須一律透過明確的 resume 管道（如 `resume`、`dashboard_resume` 等 source）方能清除。
- **階段不可逆向與推進限制**：
  - 當前階段 `current_phase` 只能往前进（遞增），**嚴禁**逆向變更為較小的數值。若需要倒回，必須經由專屬的 `reset_plan` / `dashboard_reset_plan` 途徑。
  - **禁止跨多階跳躍**：`current_phase` 每次推進最多只能前進 1 階（如 1 ➔ 2 階為合法；但 1 ➔ 3 階為非法）。
  - **前進門檻檢查**：當前進到相鄰下一階段（`before_phase + 1`）時，前一階段的所有任務必須皆已處於 `CONVERGED` 狀態，且全域 `BLOCKING` 類型之 Issue 數量必須為 0，否則寫入會被拒絕。

### 5.3 任務狀態單步轉移限制 (Task Status Transitions)
變更任務狀態時（`task-status`），必須遵循嚴格的單步狀態轉移路徑：
- **合法狀態轉移路徑**：
  - `TODO` ➔ `DRAFTED` 或 `FROZEN`
  - `DRAFTED` ➔ `CONVERGED`、`NEEDS_REVISION` 或 `FROZEN`
  - `NEEDS_REVISION` ➔ `DRAFTED` 或 `FROZEN`
  - `FROZEN` ➔ `TODO`、`DRAFTED` 或 `NEEDS_REVISION`
  - `CONVERGED` ➔ `NEEDS_REVISION` 或 `FROZEN`
  - *註：狀態與其自身（例如 `TODO` ➔ `TODO`）始終為合法轉移。*
- **非法狀態轉移**：任何未列在上述合法路徑中的轉換皆為**非法**（例如：嚴禁從 `TODO` 直接改為 `CONVERGED`；嚴禁從 `NEEDS_REVISION` 直接改為 `CONVERGED` 等）。
- **收斂門檻限制 (Convergence Gate)**：將任務改為 `CONVERGED` 之前，該任務的收斂計數 `conv` **必須**大於或等於設定的門檻（`threshold`，預設為 5）。否則寫入將直接報錯。

### 5.4 實體唯一性約束 (Entity Uniqueness)
- **任務唯一性**：使用 `task-add` 新增任務時，若該任務 ID 已存在於當前 Phase，將直接報錯。
- **Issue 唯一性**：使用 `issue-add` 新增問題時，若該 Issue ID 已存在於狀態中，將直接報錯。

### 5.5 任務推進配額限制 (One-Task Progress Quota)
- **實質任務前進限額**：當 CLI 帶有非空的 `run_id` 與 `round` 時，系統會在 `control` 中記錄 `last_task_progress_run_id`。在同一個 round 內只允許進行**最多一次**實質任務推進（定義為任務狀態從 `TODO` ➔ `DRAFTED`，或從 `DRAFTED` ➔ `CONVERGED`）。重複推進將被拒絕。

### 5.6 收斂自增防灌水限制 (Conv Increment Restrictions)
- **重複簽章防堵**：變更任務收斂計數器（`task-conv --incr`）時，會綁定當前「Phase + Git Commit」組成的進展簽章。在簽章未改變的情況下，禁止對同一任務連續執行兩次自增，以防收斂計數灌水。
