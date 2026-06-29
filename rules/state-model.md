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

## 2. 樹狀模式狀態模型（state.json 中的 tree 欄位）

在樹形漸進拆解模式下，整棵樹的拓撲結構與狀態均活在 `state.json` 的 `tree` 物件下。

- `tree.root`：樹的根節點 ID。
- `tree.nodes.{node_id}`：包含該節點的屬性：
  - `state`：節點生命週期狀態（`PENDING`、`DECOMPOSED`、`LEAF`、`IN_PROGRESS`、`CONVERGED`、`NEEDS_REVISION`、`FROZEN`）。
  - `children`：子節點 ID 陣列。
  - `parent`：父節點 ID。
  - `depth`：節點在樹中的深度。
  - `depends_on`：兄弟節點的依賴陣列。
  - `stable_rounds`：規劃期子節點集合連續穩定的輪數。
  - `reflow_count`：執行期該葉子被退回修復的次數。

---

## 3. 流程控制（flow — 引擎 + boot 共同驅動，全 config化）

| 機制 | 通用判準（config 驅動） | 由誰執行 |
|------|------------------------|---------|
| **BOOT SEQUENCE** | STEP G→10：一輪【只做一個任務/一次驗證】，STEP 10 後 agent 結束並交回控制權；更新狀態使用 CLI 寫入 | agent |
| **Phase Gate (平模式)** | 相鄰階段 i→i+1：`phase i 全 CONVERGED 且 p{i}_pass>=門檻 且 blocking==0` | 引擎 + agent |
| **Phase Gate (樹模式)** | **規劃期 → 執行期**：全樹無 `PENDING` 節點且規劃完成 → 暫停進入 **人類 Gate**。 | 引擎 + 人類 |
| **向上解鎖 (樹模式)** | **自底向上解鎖**：中間/父節點在所有子節點皆為 `CONVERGED` 後，由引擎解鎖為 `CONVERGED`。 | 引擎 |
| **停止(正常)** | `current_phase==最後階段 且 最後階段全任務 CONVERGED 且 p{last}_pass>=final_phase_pass_gte 且 blocking==0` | 引擎 |
| **停止(交人類)** | `human_required==true` | 引擎 |

---

## 4. 引擎讀寫狀態的方式

- 引擎透過呼叫 `state.py` 讀寫 `state.json`。

