# 🛡️ 規劃書 — state.py / state.json 防呆強化（限縮 agent 出錯）

> **交付對象**：執行 agent。
> **目標**：把目前「寫了但沒生效」的守衛救活，並補上一批機械化硬約束，讓 agent 在操作狀態時**無法**做出非法/造假/越級的變更。
> **總原則**：硬邊界由程式擋死，不靠 prompt 自律；任何拒絕都回 exit code 1 + 可教學的明確訊息；價值判斷一律交人類。
> **唯一事實來源**：方法論在 `rules/`，本規劃書只描述工程改動，不重述方法論軟版。

---

## 0. 現況基線（改動前必讀）

目前 `state.py` 已具備的防護：
- **白名單 + 型別**：`_is_valid_key`（[state.py:62](../engine/state.py)）、`set/incr` 的數值校驗（[state.py:961](../engine/state.py)）。
- **守衛轉換**：`_validate_guarded_transition`（[state.py:276](../engine/state.py)）擋「`human_required` 不可被改回 false」「`current_phase` 不可逆向」。
- **樂觀鎖 + 寫者蓋章**：`guarded_state_write`（[state.py:298](../engine/state.py)）用 `expected_revision` 偵測衝突、`_stamp_last_writer` 蓋 `last_writer` 並 bump `state_revision`。
- **任務單步轉移 + 收斂門檻**：`task-status` CLI（[state.py:1040](../engine/state.py)）。
- **唯一性**：`task-add` / `issue-add`。
- **原子寫入**：`save_state_json` 用 tmp + `os.replace`（[state.py:29](../engine/state.py)）。

### 🔴 核心問題（本規劃書要解決的根因）
`_validate_guarded_transition` / `guarded_state_write` / `_stamp_last_writer` **目前只被引擎內部的 `set_human_required` / `set_plan_human_required` 呼叫**。
agent 實際操作走的是 `__main__` 裡的 CLI 子命令（`set` / `incr` / `task-status` / `task-conv` / `issue-*`），這些路徑直接 `set_val_in_json_data` + `save_state_json`，**完全繞過守衛、不 bump revision、不蓋 writer**（見 [state.py:951](../engine/state.py)、[state.py:961](../engine/state.py)、[state.py:1040](../engine/state.py)、[state.py:1077](../engine/state.py)、[state.py:1092](../engine/state.py)）。

➡️ 後果：規則文件 `state-model.md` §5.2 寫的保護對 agent 全部失效——agent 可 `set human_required false`、`set current_phase 1`（倒退）而不被擋。**TASK-01 是所有其他守衛能否生效的前提，必須先做。**

---

## 1. 任務清單（依依賴順序執行）

> 每個任務含：問題 / 改動位置 / 做法 / 驗收標準。請逐一完成，每完成一個就補一支單元測試到 `engine/test_engine_features.py`。

---

### TASK-01｜CLI 寫入路徑全面改走 `guarded_state_write`（最高優先）

- **問題**：CLI 寫入繞過守衛（見 §0 核心問題）。
- **改動位置**：
  - `state.py` `__main__`：`set` / `incr` / `task-status` / `task-conv` / `issue-add` / `issue-set-status` 各分支（[state.py:935](../engine/state.py)–[state.py:1128](../engine/state.py)）。
  - argparse：頂層新增 `--run-id`（[state.py:842](../engine/state.py) 附近）。
  - `state_cli` 注入：把 run_id 帶進指令（[config.py:157](../engine/config.py)）。
- **做法**：
  1. argparse 頂層加 `parser.add_argument("--run-id", default=os.environ.get("LOOP_RUN_ID", ""))`。
  2. 把每個寫入子命令的「`set_val_in_json_data(...)` + `save_state_json` + `render_all`」三件套，改為包成 `mutate(data)` 閉包，丟給 `guarded_state_write(state_path, mutate, source="agent_cli", run_id=args.run_id)`。
  3. `guarded_state_write` 回傳 `{"ok": False, "conflict": True/...}` 或拋 `ValueError` 時，CLI 印出原因到 stderr 並 `sys.exit(1)`；`ok=True` 才印 `OK ...` 並 `exit(0)`。
  4. `config.py` 的 `state_cli` 注入改為 `python {state_py} --state {state_json} --run-id {run_id}`（run_id 取自 cfg；若無則留空，由 env 補）。
- **相容性**：`set_val_in_json_data` 仍保留供 `guarded_state_write` 內的 mutate 使用；不要刪。
- **驗收標準**：
  - `set human_required true` 後，再 `set human_required false`（source=agent_cli）**被拒、exit 1**。
  - `set current_phase 2` 後 `set current_phase 1` **被拒、exit 1**。
  - 任一成功的 CLI 寫入後，`get state_revision` 數值 +1、`get last_writer_source` == `agent_cli`。
  - 既有 `task-add` / `task-status` 合法操作仍成功。

---

### TASK-02｜機械化 Phase Gate（`current_phase` 推進必須過門檻）

- **問題**：`phase-converged` / `is-done` 只是可查詢的 derive（[state.py:1147](../engine/state.py)），沒有任何東西阻止 agent 直接 `set current_phase 2` 跳級。
- **改動位置**：`_validate_guarded_transition`（[state.py:276](../engine/state.py)）。
- **做法**：在現有「不可逆向」檢查之後，補「前進需達標」檢查：
  - 當 `after_phase == before_phase + 1` 時，要求 `前一階段（before_phase）所有 task 為 CONVERGED` 且 `OPEN+BLOCKING 的 issue 數 == 0`。否則 `raise ValueError("phase N→N+1 blocked: 前一階段未全部 CONVERGED 或仍有 BLOCKING issue")`。
  - 當 `after_phase > before_phase + 1`（跳級）一律拒絕：`raise ValueError("current_phase 不可一次推進多階")`。
  - 例外 source：`reset_plan` / `dashboard_reset_plan` 不受此限（沿用既有逆向例外清單）。
- **注意**：判斷「全 CONVERGED / blocking==0」請複用既有 derive 邏輯（[state.py:1147](../engine/state.py)–[state.py:1163](../engine/state.py) 的 phase-converged、[state.py:112](../engine/state.py) 的 blocking 重算），避免重複實作漂移。
- **驗收標準**：
  - phase 1 尚有 task != CONVERGED 時 `set current_phase 2` → 被拒、exit 1。
  - phase 1 全 CONVERGED 且 blocking==0 時 `set current_phase 2` → 成功。
  - `set current_phase 3`（從 1 跳級）→ 被拒。

---

### TASK-03｜收斂計數防灌水（conv 增量綁 progress signature）

- **問題**：`task-conv --incr`（[state.py:1077](../engine/state.py)）無條件 +1，對應 loophole-audit 的 P3 反模式——agent 不做真實重推也能把 conv 灌到門檻、騙過 `CONVERGED` 收斂門檻。
- **改動位置**：`task-conv` 分支（[state.py:1077](../engine/state.py)）；task 物件結構（新增欄位）。
- **做法**：
  1. 每個 task 物件新增欄位 `last_conv_sig`（預設空字串）。
  2. `--incr` 時計算當前 `progress_signature(cfg, control)`（已存在，[state.py:389](../engine/state.py)，內含 git HEAD + phase + total_pass）。
     - 若 `sig == target_task.last_conv_sig` → **拒絕**：`Error: conv 未變動（同一進展簽章不可重複 +1，需有真實 commit/狀態前進）`，exit 1。
     - 否則 `conv += 1`，寫回 `last_conv_sig = sig`。
  3. `--reset` 時 `conv = 0` 並清空 `last_conv_sig`。
- **取得 cfg 的方式**：CLI 目前無 cfg。最小作法：用 `git_utils.git_head()` + `current_phase` 自行組一個輕量簽章（不需完整 cfg），確保「同一個 git HEAD + 同一 phase 下不可連 +1」。請在 docstring 註明此簡化。
- **驗收標準**：
  - 同一 git HEAD 下對同一 task 連兩次 `task-conv --incr` → 第二次被拒、exit 1、conv 不變。
  - 製造一個新 commit（HEAD 改變）後再 `--incr` → 成功、conv +1。
  - `--reset` 後 `last_conv_sig` 清空、下一次 `--incr` 可成功。

---

### TASK-04｜狀態變更審計帳本（append-only）

- **問題**：個別 `set/incr/task-status` 不留痕，無法事後稽核 agent 是否偷改、無法重建。
- **改動位置**：`guarded_state_write`（[state.py:298](../engine/state.py)）成功寫入後追加；新增 `append_state_event`。
- **做法**：
  1. 新增 `append_state_event(state_json_path, record)`，寫到與 state.json 同目錄的 `state_events.jsonl`（append-only，沿用 `append_round_record` 的 try/except 風格，[state.py:402](../engine/state.py)）。
  2. 在 `guarded_state_write` 成功路徑（`save_state_json` 之後）寫一筆：`{ts, run_id, source, revision, changed_keys, before_summary, after_summary}`。
     - `changed_keys`：比對 before/after 的 `control` / `plan` / `phases`(task status&conv) / `current_phase` 差異，列出變動的 key。
     - 不要記整份狀態（context/磁碟成本），只記摘要。
  3. （可選）dashboard 後端加一個讀 `state_events.jsonl` 的端點供 UI 顯示。本規劃書只要求產出檔案，端點列為後續。
- **驗收標準**：
  - 任一成功寫入後，`state_events.jsonl` 多一行合法 JSON，含正確 `revision` 與 `changed_keys`。
  - 被守衛拒絕的寫入**不**產生事件行（拒絕發生在 save 之前）。

---

### TASK-05｜載入/寫入不變量校驗（fail-closed）

- **問題**：`load_state_json` 出錯時回 `{}`（[state.py:24](../engine/state.py)），壞檔靜默變空狀態，後續流程可能用空狀態誤判。寫入也沒有結構不變量檢查。
- **改動位置**：新增 `_check_invariants(data) -> list[str]`；在 `guarded_state_write` 的 `_validate_guarded_transition` 之後呼叫。
- **做法**：
  1. 寫一個 `_check_invariants(data)`，回傳違規訊息清單，至少涵蓋：
     - `current_phase` 必須對應到 `phases` 中存在的 id。
     - 同一 phase 內 task id 不重複；全域 issue id 不重複。
     - 每個 task 的 `conv` 不可 > `threshold` 後仍非 CONVERGED 之外的非法組合（至少 `conv >= 0`、`threshold >= 1`）。
     - issue `level` ∈ {BLOCKING, NON_BLOCKING}、`status` ∈ {OPEN, RESOLVED}。
  2. `guarded_state_write` 中若 `_check_invariants(after)` 非空 → `raise ValueError("invariant violated: " + "; ".join(...))`，不寫入。
  3. **載入端**：`load_state_json` 在 `json.load` 失敗時，除了 log，改為**拋出**自訂例外（或回一個帶 `__corrupt__: True` 標記的 dict），讓上層能 fail-closed 而非把空狀態當正常。請評估呼叫端衝擊；若風險高，至少在 CLI `get/set` 入口偵測到空/壞檔時報錯退出（已有部分：[state.py:936](../engine/state.py)）。
- **驗收標準**：
  - 構造 `current_phase=9` 但 phases 無 id=9 → 寫入被拒。
  - 構造重複 task id 的 mutate → 被拒。
  - 壞 JSON 檔不再被當成空狀態靜默通過（至少 CLI 報錯 exit 1）。

---

### TASK-06｜一輪一任務配額（物理化「一輪一任務」）

- **問題**：規則要求「每輪只做一個任務/一次驗證」，但 state.py 沒擋，對應 loophole-audit 的 P1 多工幻覺。
- **改動位置**：`guarded_state_write` 或 task-status 分支；需要 run_id（由 TASK-01 提供）。
- **做法**：
  1. 在 state.json 的 `control` 記 `last_task_progress_run_id`（上次發生「實質任務前進」的 run_id）。
  2. 定義「實質任務前進」= `TODO→DRAFTED` 或 `DRAFTED→CONVERGED`。
  3. 當本次寫入屬於上述轉移，且 `args.run_id == control.last_task_progress_run_id`（同一輪已經前進過一次）→ **拒絕**：`Error: 本輪已推進一個任務，請結束本輪（一輪一任務）`，exit 1。否則更新 `last_task_progress_run_id = run_id`。
- **注意**：run_id 為空（未注入）時退化為不限制，並 log 警告，避免本地手動操作被卡死。
- **驗收標準**：
  - 同一 `--run-id` 下對兩個不同 task 各做一次 `TODO→DRAFTED` → 第二次被拒。
  - 不同 `--run-id` → 各自可前進一次。

---

### TASK-07｜拒絕訊息可教學 + `--dry-run`

- **問題**：非法轉移只報 `Invalid status transition`（[state.py:1062](../engine/state.py)），agent 不知道合法下一步，浪費輪數試錯。
- **改動位置**：`task-status` 分支（[state.py:1040](../engine/state.py)）；argparse 各寫入子命令。
- **做法**：
  1. 非法轉移時，列出當前狀態的**所有合法目標**：`Error: 非法轉移 {old}→{new}。{old} 的合法下一步為：{...}`。
  2. 各寫入子命令加 `--dry-run`：跑完所有校驗（含 TASK-02/05 守衛）但**不** `save_state_json`，印 `DRY-RUN OK: <會發生的變更>` 或印拒絕原因。實作上可在 `guarded_state_write` 加 `dry_run: bool` 參數，校驗通過後在 save 前 return。
- **驗收標準**：
  - `task-status ... --to CONVERGED`（從 TODO）→ 訊息含「TODO 的合法下一步為：DRAFTED, FROZEN」。
  - `--dry-run` 不改變 `state_revision`，但非法操作仍回 exit 1。

---

### TASK-08｜修 CLI ↔ 文件/設定漂移（消除照抄即報錯）

- **問題**：文件範例與 argparse 對不上，agent 照抄 `state-cli-guide.md` 直接吃 exit 1；另有硬編碼門檻與 config 漂移。
- **逐項**：
  1. `state-cli-guide.md` §4 `issue-add --level blocking`（小寫）/ `--level info` → CLI choices 是大寫 `BLOCKING` / `NON_BLOCKING`（[state.py:888](../engine/state.py)）。**修文件為大寫**，且移除不存在的 `info`/`INFO`。
  2. `state-cli-guide.md` §4.2 `issue-set-status --status RESOLVED` / 提到 `WONTFIX` → CLI 實際是 `--to`，choices 只有 `OPEN`/`RESOLVED`（[state.py:894](../engine/state.py)）。**統一**：要嘛文件改 `--to` 並刪 WONTFIX，要嘛 CLI 加 `--status` alias + `WONTFIX` choice。建議改文件（成本低）。
  3. `state-cli-guide.md` §3.3 `task-add --phase 1 --task TASK-03 --output ...` → CLI 要 `--id` 且 `--order` 必填（[state.py:877](../engine/state.py)）。**修文件**為 `--id ... --order N`。
  4. **`derive is-done` 硬編碼門檻**：[state.py:1176](../engine/state.py) 寫死 `final_phase_pass_gte=10`，與 `config.py` 的 `stop_condition`（[config.py:40](../engine/config.py)）及 `utils.is_done`（[utils.py:381](../engine/utils.py)）重複且會漂移。**作法**：CLI `derive is-done` 不要自己重算；若 CLI 無 cfg，改為在 state.json 內存一份由引擎寫入的 `stop_condition` 快照供 derive 讀，或直接標註 `is-done` 僅供除錯、停止判定一律以 `utils.is_done` 為準。請在程式碼註解寫清楚單一事實來源。
- **驗收標準**：
  - 依 `state-cli-guide.md` 範例逐條複製貼上執行，全部成功（不再因大小寫/參數名 exit 1）。
  - `is-done` 的門檻值來源唯一（不再兩處各寫一個 10）。

---

## 2. 全域驗收（全部任務完成後）

- `engine/test_engine_features.py` 新增/通過對應每個 TASK 的測試；`python -m pytest engine/` 全綠。
- 端到端：跑一個既有 `.loop/<name>/` 工作區，確認正常收斂流程（合法操作）不被新守衛誤擋。
- 回歸檢查：dashboard 既有的 resume / reset_plan 路徑仍能清 `human_required`、仍能 `reset_plan` 倒回 phase（這兩條是守衛的合法例外，務必保留）。

## 3. 風險與相容性

- TASK-01 改變了所有 CLI 寫入的行為（會 bump revision、蓋 writer）。確認 dashboard / loop.py 沒有依賴「CLI 寫入不改 revision」的假設。
- TASK-05 載入端 fail-closed 若改太激進可能讓首次 `migrate` 前的空檔報錯——請保留「檔案不存在 → 空狀態」與「檔案存在但壞 → 報錯」的區分。
- run_id 來源（env `LOOP_RUN_ID` vs `--run-id` vs cfg）三者請定義優先序並在一處集中解析，避免 TASK-01/06 各自為政。

## 4. 建議實作順序

`TASK-01`（前提）→ `TASK-08.4 + is-done 單一來源`（消歧）→ `TASK-02` → `TASK-03` → `TASK-05` → `TASK-06` → `TASK-04` → `TASK-07` → `TASK-08.1~3 文件` → 全域驗收。
