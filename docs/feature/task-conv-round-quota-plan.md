# 🛡️ 規劃書 — `task-conv --incr` 一輪一次配額（收斂計數防灌水強化）

> **交付對象**：執行 agent。
> **目標**：在既有「Phase + Git HEAD 簽章」防重複自增的基礎上，疊加「同一 `run_id#round` 只允許一次 `conv +1`」的配額鎖，比照 `task-status` 已有的一輪一任務配額，堵住「同一輪內多個瑣碎 commit 各自灌一次 conv」的繞法。
> **總原則**：硬邊界由程式擋死，不靠 prompt 自律；任何拒絕都回 exit code 1 + 可教學的明確訊息；兩道檢查（簽章 / 配額）是「且」的關係，任一擋下即拒絕。
> **唯一事實來源**：方法論在 `rules/`，本規劃書只描述工程改動，不重述方法論本體。

---

## 0. 現況基線（改動前必讀）

目前 `task-conv --incr` 已具備的防護：**Phase + Git HEAD 簽章**（[`_cli_progress_signature`](../../engine/state.py:506)），邏輯在 [state.py:1399-1414](../../engine/state.py:1399)：

```python
sig = _cli_progress_signature(data)   # f"{current_phase}|{git_head()}"
if sig == (live_task.get("last_conv_sig") or ""):
    raise ValueError("conv unchanged: the same progress signature cannot increment twice without real progress")
live_task["conv"] += 1
live_task["last_conv_sig"] = sig
```

### 🔴 核心缺口（本規劃書要解決的根因）

簽章只綁「Phase + HEAD」，**沒有綁 round**。這代表：

- 若同一輪內 agent 刻意（或因 [`git_guard`](../../engine/git_utils.py:113) 中斷後自動補 commit）產生**多個 commit**，每次 HEAD 改變都會讓簽章不同，`--incr` 就會被允許重複執行 → 一輪內可以灌超過 1 次 conv，違反 `rules/state-model.md` 「每輪只做一次驗證」的方法論規則。
- 對照組：`task-status` 的 `TODO→DRAFTED` / `DRAFTED→CONVERGED` 已經由 [`_record_task_progress_quota`](../../engine/state.py:512) 用 `run_id#round` 鎖住「一輪只能推進一個任務」，但這把鎖**只覆蓋狀態晉級，沒有覆蓋 conv 計數本身**。

➡️ 後果：agent 可以在合法的狀態機轉移節奏下（不違反 `task-status` 配額），單純靠多 commit 把 `conv` 提早灌到 `threshold`，繞過「多輪獨立驗證」這個收斂門檻原本要保證的東西。

---

## 1. 任務清單（依依賴順序執行）

> 每個任務含：問題 / 改動位置 / 做法 / 驗收標準。完成後補單元測試到 `engine/test_engine_features.py`。

---

### TASK-01｜為 `task-conv --incr` 疊加 round 配額鎖（最高優先）

- **問題**：見 §0 核心缺口。
- **改動位置**：
  - `state.py` 新增控制欄位 `last_conv_progress_run_id`（獨立於 `task-status` 用的 `last_task_progress_run_id`，因為兩者語意不同：一個是「狀態晉級」，一個是「收斂計數」，不應共用同一把鎖，否則兩種操作會互相卡到對方的配額）。
  - `STATIC_KEYS` 白名單加入新欄位（[state.py:52](../../engine/state.py:52)）。
  - `control_keys` 集合（get/set 路徑，[state.py:124](../../engine/state.py:124)、[state.py:204](../../engine/state.py:204)）加入新欄位。
  - `task-conv` 分支的 `mutate()`（[state.py:1399-1414](../../engine/state.py:1399)）。
- **做法**：
  1. 新增輔助函式 `_record_conv_progress_quota(data, run_id, round_no)`，邏輯比照 `_record_task_progress_quota`（[state.py:512](../../engine/state.py:512)）：
     ```python
     def _record_conv_progress_quota(data: dict, run_id: str | None, round_no: str | None) -> None:
         if run_id and round_no:
             quota_key = f"{run_id}#{round_no}"
         elif run_id:
             quota_key = run_id
         else:
             logger.warning("conv progress quota skipped because run_id is empty")
             return
         control = data.setdefault("control", {})
         last_quota_key = str(control.get("last_conv_progress_run_id") or "")
         if last_quota_key == quota_key:
             raise ValueError("this run has already incremented conv once; finish the round before incrementing again")
         control["last_conv_progress_run_id"] = quota_key
     ```
  2. 在 `task-conv --incr` 的 `mutate()` 內，**簽章檢查通過之後、寫入 `conv`/`last_conv_sig` 之前**呼叫 `_record_conv_progress_quota(data, args.run_id, args.round)`。兩個檢查皆為硬性關卡，任一失敗就 `raise ValueError`、不寫入。
  3. `--reset` 不受此配額影響（`--reset` 是清空重來，不算「實質前進」），維持現況直接 `conv = 0; last_conv_sig = ""`。
  4. `run_id` 為空（未注入，例如本地手動操作）時退化為不限制，僅記 warning log，比照 TASK-06（`task-status` 配額）的既有慣例，避免非 agent 的手動操作被卡死。
- **注意（訊息可教學）**：兩種拒絕原因要在錯誤訊息上明確區分，讓 agent 知道自己是撞到哪一道牆：
  - 簽章未變 → `"conv unchanged: the same progress signature cannot increment twice without real progress"`（維持原文案）。
  - round 配額已用 → `"this run has already incremented conv once; finish the round before incrementing again"`（新文案）。
- **驗收標準**：
  - 同一 `run_id#round` 內，即使中途製造了新的 git commit（HEAD 改變、能通過簽章檢查），第二次 `--incr` 仍要被拒、exit 1、`conv` 不變。
  - 不同 `round`（`run_id` 相同、`round` 不同）、且 HEAD 也已改變 → 兩次 `--incr` 皆應成功。
  - `run_id` / `round` 為空（本地手動）→ 不受配額限制，僅受原簽章機制限制。
  - `--reset` 不消耗、也不受此配額影響；`--reset` 後同一輪內再 `--incr` 一次應仍受配額限制（不能靠 reset 繞過同輪配額）。
  - 既有的「同一 HEAD 連兩次 `--incr` 第二次被拒」測試（[test_engine_features.py:134-137](../../engine/test_engine_features.py:134)）不受影響、維持通過。

---

### TASK-02｜CLI 注入確認：`--round` 要能傳到 `task-conv`

- **問題**：頂層 argparse 已有 `--round`（沿用 TASK-01/task-status 既有機制，`default=os.environ.get("LOOP_ROUND_NO", "")`），但 `task-conv` 分支目前完全沒讀取 `args.round`（只用在 `task-status` 分支）。需確認 `loop.py` 產生的 `state_cli` 呼叫指令，在跑 `task-conv` 時環境變數 `LOOP_ROUND_NO` 確實有被注入（沿用跟 `task-status` 相同的注入路徑，[loop.py:495-498](../../engine/loop.py:495) 附近的 comment 已說明 round 為何要逐輪 render，此處無需改動注入邏輯，只需確認共用）。
- **驗收標準**：
  - 用同一個 `config.py` 產生的 `state_cli` 前綴，分別呼叫 `task-status` 與 `task-conv`，兩者拿到的 `--round` 值一致（同一輪內相同）。

---

### TASK-03｜文件同步

- **改動位置**：
  - `rules/state-model.md`（[rules/state-model.md:86](../../rules/state-model.md:86) 「重複簽章防堵」段落）：補充「除了 Phase+HEAD 簽章，同一輪（`run_id#round`）也只允許一次 `conv +1`」。
  - `rules/state-cli-guide.md`（[rules/state-cli-guide.md:162](../../rules/state-cli-guide.md:162)）：同步補上一輪一次的說明，並列出新的拒絕錯誤訊息文案，方便 agent 讀文件就知道兩種拒絕原因分別對應什麼情況。
- **驗收標準**：文件描述與程式行為一致，不再只提簽章、漏提 round 配額。

---

## 2. 全域驗收（全部任務完成後）

- `python -m pytest engine/` 全綠，新增測試涵蓋 TASK-01 所有驗收案例。
- 端到端：跑一個既有 `.loop/<name>/` 工作區，確認正常「一輪一次驗證」的合法流程不被新配額誤擋。
- 回歸檢查：`task-status` 既有的 `run_id#round` 配額（`last_task_progress_run_id`）與本次新增的 `last_conv_progress_run_id` 互不干擾——同一輪內合法地推進一次任務狀態 **且** 合法地 `conv +1` 一次，兩者應同時成功（不應共用同一把鎖而互相誤鎖對方）。

## 3. 風險與相容性

- 新欄位 `last_conv_progress_run_id` 需要在既有 state.json 檔案缺欄位時安全地當作空字串處理（`control.get(..., "")`），不影響尚未升級過的舊工作區。
- `run_id` / `round` 三者的來源優先序（env `LOOP_ROUND_NO` vs `--round` vs cfg）應與 `task-status` 既有的解析方式保持一致，避免同一套 CLI 對兩個子命令的 round 判斷產生落差（沿用 `docs/state-hardening-plan.md` §3 已提過的風險，此處不重複造輪）。
- 本規劃書**不**處理 Git Review Gate 的 revert 粒度問題（同一輪內多個 commit 被整段 revert、可能連坐 revert 掉合法的第一個 commit）。該議題已討論過，結論是**暫緩**：先觀察「同輪雙 commit」（agent 本身 commit + `git_guard` 中斷後自動補 commit）在實際運行中的發生頻率，若確認是常態且造成明顯浪費，再另開規劃書處理「精確 revert 邊界」（需要 review 判決 schema 額外標出從哪個 SHA 開始有問題，並處理部分 revert 失敗時的 fallback 邏輯）。

## 4. 建議實作順序

`TASK-01`（配額鎖本體）→ `TASK-02`（確認注入一致）→ `TASK-03`（文件同步）→ 全域驗收。
