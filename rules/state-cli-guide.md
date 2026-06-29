# 📖 RULE — state.json CLI 操作與狀態更新指引

> **本文件為 Agent 專用指引。** 
> 當前專案的所有執行狀態唯一事实來源為 `.loop/state.json`。
> 🚨 **鐵則**：你【嚴禁】直接編輯 `state.json` 檔案。任何對狀態的寫入與變更，必須一律使用系統自動注入的 `{state_cli}` 工具。


---

## 1. 基礎命令語法

`{state_cli}` 指令會自動指向對應的 `state.json`。其基本格式為：
```bash
{state_cli} <subcommand> [arguments...]
```

---

## 2. 通用變數更新 (`set` / `incr`)

當需要更新通用變數（例如每輪結束時的震盪偵測欄位、stuck 狀態等），請使用 `set` 或 `incr`。

### 2.1 填寫本輪震盪偵測欄位（STEP 9 必做）
在每一輪結束前，必須使用以下三個指令更新本輪的執行模式與結果：
- **設定本輪模式** (`推進` 或 `驗證`)：
  ```bash
  {state_cli} set last_round_mode 推進
  ```
- **設定本輪結果** (`PASS`、`FAIL` 或 `NA`)：
  ```bash
  {state_cli} set last_round_result PASS
  ```
- **設定失敗任務**（如果有任務失敗被退回，填入任務 ID，多個以逗號分隔；若 PASS 則填空字串 `""`）：
  ```bash
  {state_cli} set last_round_fail_tasks "TASK-02"
  ```

### 2.2 設定其他控制變數
- **變更當前階段 ID**：
  ```bash
  {state_cli} set current_phase 2
  ```
- **變更連續通過驗證次數** (例如設定為 0)：
  ```bash
  {state_cli} set p1_consecutive_pass 0
  ```
- **增加連續通過次數** (+1)：
  ```bash
  {state_cli} incr p1_consecutive_pass
  ```
- **遭遇卡死需升級交給人類**：
  ```bash
  {state_cli} set human_required true
  ```

---

## 3. 任務狀態與收斂管理 (`task-status` / `task-conv`)

### 3.1 變更任務狀態
任務狀態包括：`TODO`、`DRAFTED`、`IN_PROGRESS`、`CONVERGED`、`NEEDS_REVISION`、`FROZEN`。
- **開始實作某一任務** (改為 `IN_PROGRESS`)：
  ```bash
  {state_cli} task-status --phase <phase_id> --task <task_id> --to IN_PROGRESS
  # 範例
  {state_cli} task-status --phase 1 --task TASK-01 --to IN_PROGRESS
  ```
- **任務收斂完成** (改為 `CONVERGED`，前提是 conv 連續達標)：
  ```bash
  {state_cli} task-status --phase 1 --task TASK-01 --to CONVERGED
  ```
- **驗證失敗被打回** (改為 `NEEDS_REVISION`)：
  ```bash
  {state_cli} task-status --phase 1 --task TASK-01 --to NEEDS_REVISION
  ```

### 3.2 調整任務收斂計數器 (Conv)
- **增加任務收斂次數** (+1)：
  ```bash
  {state_cli} task-conv --phase 1 --task TASK-01 --incr
  ```
- **重設任務收斂次數** (歸零)：
  ```bash
  {state_cli} task-conv --phase 1 --task TASK-01 --reset
  ```

### 3.3 新增任務 (用於規劃期)
- **在某個 Phase 中新增任務**：
  ```bash
  {state_cli} task-add --phase 1 --task TASK-03 --output "outputs/new_doc.md"
  ```

---

## 4. Issue 與 Bug 索引管理 (`issue-add` / `issue-set-status`)

### 4.1 新增 Issue
當遭遇卡死、規格衝突或需要人類決策時，需建立一個 Issue：
- **新增一個阻礙性 (BLOCKING) Issue**：
  ```bash
  {state_cli} issue-add --id ISSUE-01 --title "某個 API 規格衝突導致測試無法通過" --level blocking --phase 1 --task TASK-02
  ```
- **新增一個資訊性 (INFO) Issue**：
  ```bash
  {state_cli} issue-add --id ISSUE-02 --title "效能優化建議" --level info
  ```

### 4.2 更新 Issue 狀態
Issue 的狀態包括 `OPEN`、`RESOLVED`、`WONTFIX`：
- **解決 Issue**：
  ```bash
  {state_cli} issue-set-status --id ISSUE-01 --status RESOLVED
  ```

---

## 5. 樹狀模式節點操作 (`node-*`)

> *注意：此命令僅在專案啟用樹狀模式 (`mode: "tree"`) 時使用。*

- **設定節點狀態**：
  ```bash
  {state_cli} node-set-state --node <node_id> --state <state>
  # 範例
  {state_cli} node-set-state --node leaf_task_a --state IN_PROGRESS
  ```
- **為中間節點提議子節點集合**（逗號分隔）：
  ```bash
  {state_cli} node-children --node root --children "leaf_a,leaf_b,leaf_c"
  ```
- **觸發節點依賴重構與深度重算**：
  ```bash
  {state_cli} node-reflow --node root
  ```

---

## 🚨 執行後驗證與注意事項
每次你呼叫 `{state_cli}` 更新狀態後：
1. 狀態會被原子寫入 `state.json` 檔案。
2. 你可以藉由 `git diff` 查看 `state.json` 的變更，確認狀態已經成功寫入。
3. ❌ **不要**使用編輯器手動修改 `state.json`。
