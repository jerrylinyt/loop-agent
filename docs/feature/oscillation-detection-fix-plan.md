# 🛟 規劃書 — 震盪偵測範圍修正（rule↔engine 對齊）+ 升級/停手門檻調整

> **交付對象**：執行 agent。
> **目標**：修正「震盪 A↔B / 不收斂」偵測目前結構性抓不到主要情境的 rule↔engine 落差，並把三個升級/停手門檻統一調升到 10。
> **總原則**：硬邊界由程式擋死，不靠 prompt 自律；程式行為必須與 `rules/` 承諾的一致，不可自行窄化保護範圍。
> **唯一事實來源**：方法論在 `rules/`，本規劃書只描述工程改動，不重述方法論本體。

---

## 0. 現況基線（改動前必讀）

### 🔴 核心問題：`is_fail_verify` 判定範圍比規則承諾的窄，且窄到跟主要情境互斥

震盪偵測目前的判定邏輯在 [loop.py:279](../../engine/loop.py:279)（`update_stuck_state` 內）與 [loop.py:539](../../engine/loop.py:539)（`_run_execute_locked` 內重複計算一次）：

```python
is_fail_verify = (not killed) and ("驗證" in mode) and (result == "FAIL")
```

`mode` / `result` 是 [loop.py:523-524](../../engine/loop.py:523) 讀 agent 自己回填的 `last_round_mode` / `last_round_result`（見 [boot-sequence.md:106-107](../../rules/boot-sequence.md:106)）。這個布林值同時餵給：
- **不收斂偵測**：`rounds_since_progress`（[loop.py:293-295](../../engine/loop.py:293)）只在 `is_fail_verify` 為真時才 +1。
- **震盪 A↔B 偵測**：`fail_fingerprints` 指紋歷史（[loop.py:295](../../engine/loop.py:295)、[loop.py:540-541](../../engine/loop.py:540)）只在 `is_fail_verify` 為真時才 append。

問題在於 `"驗證" in mode` 這個條件：依 [boot-sequence.md:67](../../rules/boot-sequence.md:67)，`mode=驗證` **只在該 phase 剩下任務全部已 CONVERGED 時才會進入**（跑 phase 級全量驗證）。而 oscillation-escalation.md 本身要解決的「改 A 壞 B、改 B 壞 A」死循環（[oscillation-escalation.md:3](../../rules/oscillation-escalation.md:3)），實際發生在**單一任務卡在 DRAFTED/NEEDS_REVISION、反覆 RE-VERIFY 抓到實質差異**的階段（[convergence.md:31-48](../../rules/convergence.md:31)）——這種輪次依 STEP 4 分類邏輯應回填 `mode=推進`，不是 `驗證`。

這造成結構性矛盾：**只要有任務還在震盪、沒有全部 CONVERGED，該 phase 就永遠進不了「驗證模式」**（進驗證模式的前提正是「全部已 CONVERGED」）。也就是說，`is_fail_verify` 在「任務真的在震盪」的當下幾乎不可能為真——不是機率低，是條件互斥。

而規則文字自己在 [oscillation-escalation.md:15](../../rules/oscillation-escalation.md:15) 明確要求「不論 `last_round_mode` 是「推進」或「驗證」」都要推進指紋歷史，跟引擎的 `"驗證" in mode` 判斷直接矛盾——規則承諾的保護，引擎沒有做到。規則文件內部也有自相矛盾：§A 表格（[oscillation-escalation.md:10](../../rules/oscillation-escalation.md:10)）寫「連續失敗**驗證**輪沒進展」，暗示窄讀成只算驗證模式，跟下面第 15 行的明確說明衝突。

### 次要問題：`idle_stalled` 這條路徑也抓不到「有在動但沒收斂」

`idle_stalled`（[loop.py:302](../../engine/loop.py:302)）靠 `progress_signature`（phase + 總 pass 數 + git HEAD）連續不變偵測。一個持續震盪的任務每輪幾乎都會有新 commit（RE-VERIFY 失敗要 conv 歸零 + 寫修正記錄），HEAD 每輪都變，這條路徑同樣抓不到「每輪都有動作、但沒有真的收斂」的情況。

**結論**：目前唯一真的會把 `stuck_level` 推上去的情境，是 agent 連續 `stall_threshold` 輪**完全沒有任何 commit**（純空轉）；規則真正要防的任務級震盪，結構上幾乎無法觸發。此區塊完全沒有單元測試覆蓋（`test_engine_features.py` 搜不到 `is_fail_verify` / `detect_oscillation`）。

---

## 1. 任務清單（依依賴順序執行）

---

### TASK-01｜修正 `is_fail_verify` 判定範圍，對齊規則承諾（最高優先）

- **問題**：見 §0 核心問題。
- **改動位置**：[loop.py:279](../../engine/loop.py:279)（`update_stuck_state` 內）、[loop.py:539](../../engine/loop.py:539)（`_run_execute_locked` 內）。
- **做法**：
  1. 拿掉 `"驗證" in mode` 這個限制條件，改成任何 mode 下、只要 `result == "FAIL"` 且非被 watchdog 中斷（`not killed`），就視為一次客觀驗收失敗：
     ```python
     is_fail_verify = (not killed) and (result == "FAIL")
     ```
  2. 變數名稱 `is_fail_verify` 已不準確（現在推進/驗證兩種 mode 都算），建議重新命名為 `is_objective_fail`（兩處呼叫點同步改名），避免未來讀者誤解成「僅限驗證模式」。
  3. `NA` 的既有語意不變（[oscillation-escalation.md:16](../../rules/oscillation-escalation.md:16)：`NA` 僅限「本輪沒有執行任何客觀驗收」的純推進輪），這次修正不影響 `NA` 判斷路徑，只補回 `推進` 模式下 `FAIL` 應該被計入的部分。
- **驗收標準**：
  - 建構一輪 `mode=推進`、`result=FAIL` 的紀錄 → `rounds_since_progress` 應 +1、`fail_fingerprints` 應新增一筆。
  - 既有 `mode=驗證`、`result=FAIL` 的行為維持不變（不能因改名/改條件而回歸失敗）。
  - `killed=True` 的輪次不論 mode/result 為何，一律不計入（維持原本 `not killed` 前提）。

---

### TASK-02｜修正規則文件自相矛盾措辭

- **問題**：[oscillation-escalation.md:10](../../rules/oscillation-escalation.md:10) 表格寫「連續失敗**驗證**輪沒進展」，與同文件第 15 行「不論 `last_round_mode` 是「推進」或「驗證」」矛盾，容易被窄讀。
- **改動位置**：`rules/oscillation-escalation.md` §A 表格。
- **做法**：把表格內「連續失敗驗證輪沒進展」改為「連續客觀驗收失敗輪沒進展（不論推進/驗證模式）」，與第 15 行說明保持一致。
- **驗收標準**：文件內部不再有「驗證輪」與「不論推進或驗證」兩種矛盾措辭並存。

---

### TASK-03｜調升三個升級/停手門檻至 10

- **問題**：目前 `stall_threshold=6`、`enhanced_max_rounds=8`、`human_stop_after=4`（[config.py:49-53](../../engine/config.py:49)），使用者要求統一調高到各 10 次，讓升級/停手更保守（減少誤判、給更多輪次真正嘗試收斂）。
- **改動位置**：`engine/config.py` `DEFAULTS["oscillation"]`（[config.py:48-54](../../engine/config.py:48)）。
- **做法**：
  ```python
  "oscillation": {
      "stall_threshold": 10,      # 原 6：tier0→1 升級門檻（不收斂 / 無活動 共用）
      "osc_window": 8,            # 維持不變，見下方說明
      "osc_distinct_max": 3,      # 維持不變，見下方說明
      "enhanced_max_rounds": 10,  # 原 8：tier1→2 升級門檻
      "human_stop_after": 10,     # 原 4：tier2 之後的停手緩衝
  },
  ```
  - **`osc_window` / `osc_distinct_max` 刻意不動**：這兩個是「震盪 A↔B 指紋窗口」的形狀參數（窗口大小 / 窗口內允許的最多相異指紋數），不是「升級門檻」或「停手限制」，語意上跟本次要求的兩類門檻不同軸；若要一併放寬需要使用者額外確認，本規劃書先維持原值，只調整明確對應「升級」與「停手」的三個欄位。
  - **連動影響（務必檢查）**：`engine/plan_loop.py` 的規劃收斂震盪偵測（[plan_loop.py:272](../../engine/plan_loop.py:272)、[plan_loop.py:278](../../engine/plan_loop.py:278)）共用同一份 `oscillation` config，且是**自己的兩層梯度**（`stall_threshold` 升級增強模型 → `stall_threshold + enhanced_max_rounds` 才交人類），沒有用到 `human_stop_after`。調整後 plan_loop 的人類交接輪數會從 `6+8=14` 變成 `10+10=20`，屬於本次調整的預期副作用，需在驗收時一併確認、不是遺漏。
  - 執行迴圈（`loop.py`）的最終硬停止門檻是 `stall_threshold + human_stop_after`（[loop.py:320](../../engine/loop.py:320)），會從 `6+4=10` 變成 `10+10=20`。
- **驗收標準**：
  - `config.py` 三個欄位改為 10，`osc_window`/`osc_distinct_max` 維持 8/3。
  - 執行迴圈：`stuck_level` 0→1 需連續 10 輪才升級（原 6）；1→2 需再撐 10 輪（原 8）；2→硬停止需再 10 輪（原 4，此時總計 `10+10=20` 輪）。
  - 規劃迴圈（plan_loop）：升級增強模型需連續 10 輪無進展（原 6）；交人類需連續 20 輪無進展（原 14）。

---

### TASK-04｜補測試

- **改動位置**：`engine/test_engine_features.py` 新增測試。
- **做法**：
  1. 針對 TASK-01：構造 `mode=推進`、`result=FAIL`、`killed=False` 的呼叫，驗證 `is_objective_fail`（重新命名後）為 `True`，並驗證 `update_stuck_state` 回傳的 `rounds_since` 有 +1。
  2. 針對 TASK-01：構造 `killed=True` 的呼叫，驗證不論 mode/result 為何都不計入。
  3. 針對 TASK-03：讀 `config.py` DEFAULTS，斷言 `stall_threshold == 10`、`enhanced_max_rounds == 10`、`human_stop_after == 10`、`osc_window == 8`、`osc_distinct_max == 3`（鎖住這次刻意不動的兩個值，避免未來被誤改）。
- **驗收標準**：`python -m pytest engine/` 全綠，新增測試涵蓋上述三案例。

---

## 2. 全域驗收（全部任務完成後）

- `python -m pytest engine/` 全綠。
- 端到端：模擬一個任務連續多輪 RE-VERIFY 都抓到實質差異（`mode=推進, result=FAIL`），確認 `rounds_since_progress` 真的會累積、達到新門檻（10）後 `stuck_level` 會被推到 1，符合 oscillation-escalation.md 的原始設計意圖。
- 回歸檢查：既有走 `mode=驗證` 路徑的 phase 級全量驗證失敗案例行為不變。

## 3. 風險與相容性

- 門檻調升代表「卡住 → 升級模型 → 交人」整體會變慢（原本最快 10 輪硬停止，現在最快 20 輪），會拉長真正卡死時燒的輪數/成本；這是使用者明確要的方向（減少誤判優先於快速止血），但建議在改完後觀察幾次實際運行，確認沒有讓卡死狀態拖太久才交人。
- TASK-01 的行為變更（推進模式的 FAIL 現在也會被計入）會讓 `rounds_since_progress` 和 `fail_fingerprints` 在**日常任務執行期**就開始累積，而不是只在少見的 phase 收尾驗證期——這是修正 bug 後的**預期行為變化**，但等於震盪/不收斂偵測第一次在實務上「真的會動」，建議上線後密切觀察是否有誤判（例如任務本來就預期要修個兩三次才過，不該被算作「震盪」）；如有需要，可考慮讓 `stall_threshold`/`osc_distinct_max` 依任務風險分級（非本規劃書範圍，先觀察再說）。
- `plan_loop.py` 與 `loop.py` 共用同一份 `oscillation` config，TASK-03 的調整是全域生效，兩邊的人類交接時機都會變慢，驗收時兩邊都要檢查（見 TASK-03 說明）。

## 4. 建議實作順序

`TASK-01`（偵測範圍修正，最先做，因為這是讓其他改動有意義的前提）→ `TASK-04` 對應測試 → `TASK-02`（文件措辭同步）→ `TASK-03`（門檻調整，獨立於 TASK-01 也可單獨驗證）→ 全域驗收。
