# 實作計畫 — 收斂硬化（Convergence Hardening）

> **範圍決策（2026-06-28）：知識層全砲，只做收斂硬化。**
> 經評估，Knowledge Layer（index/graph、retrieval、context pack、knowledge update、adapter 正式化）成本高、收益投機、且會引入「過期知識當權威」「檢索餵不足而餓死 context」「graph merge 噪音」等比現況更糟的失效模式——既有 framework 不需它即可完整交付，故**不實作**（相關設計草稿已一併移除）。
> 本計畫只涵蓋「不靠純 LLM 自評」這個**真實**問題的便宜硬化，全部貼著既有 code/rules，不動迴圈結構。

## 0. 為什麼只需要這麼少

既有 framework 已經能完整跑完一個 legacy modernization 案子：每輪喚醒的 OpenCode 自己讀 repo、做單一 task、commit、被延後 Git Review Gate 審、卡住升級、收斂停機。唯一值得補的是**讓「宣稱 PASS」必須留下可抽查的證據**，避免橡皮圖章。

而這件事**大半已經存在**：`rules/boot-sequence.md` STEP 4（驗證模式）早就要求「`p{i}_consecutive_pass +1` 前必須寫驗證證據檔，有 build/test 的要貼實際輸出，禁止只寫『全綠』」。真正的缺口只有兩個小洞 + 一個可選硬閘。

## 1. Work Items

### WI-H1 — Git Review Gate 補「驗收證據」紅線 ✅ 已完成
- **缺口**：`rules/git-review-gate.md` 原 10 條紅線全是結構/毀損類，沒有一條稽核「宣稱 PASS 卻無證據」。boot-sequence 要求了證據，但審查端不檢查，等於沒有牙齒。
- **改動（已落地）**：
  - `rules/git-review-gate.md` §2 新增第 11 條「驗收證據缺失」：本輪若標 `last_round_result: PASS` 或讓 `p{i}_consecutive_pass` +1，且任務可驗證（有 build/test/編譯器），diff/commit/證據檔內找不到實際指令輸出 → REVERT。純分析/文件/未宣稱 PASS 的輪次不適用。
  - §2 標題由「六大審查紅線」改為「審查紅線」（原本就已列 10 條、標題數字過時）。
  - §3 逐條清單列舉加上「驗收證據缺失」。
- **不需改 code**：`prompts.yaml` 的 `git_review` 已指向「§2 的每一條」，自動含新紅線；`loop.py` 的 `_review_has_checklist`（門檻 ≥6 條）在 11 條下仍成立。
- **自驗**：跑一輪讓 agent 標 PASS 但 commit 無驗證輸出 → 審查輪應 FLAG/REVERT；標 PASS 且附實際 build/test 輸出 → PASS。

### WI-H2 — boot-sequence 把「留證」擴到 per-task 執行輪 ✅ 已完成
- **缺口**：STEP 4 的證據要求只綁「驗證模式 + 計數器 +1」；一般執行輪（STEP 7 做單一 task）標 `last_round_result: PASS` 時沒有同等留證要求。
- **改動（已落地）**：`rules/boot-sequence.md` STEP 9 新增「留證鐵則」：本輪若把 `last_round_result` 標 PASS 且任務可驗證，commit 內必須含實際驗收指令與原始輸出，禁止只寫「全綠」，與 git-review-gate §2-11 對齊。
- **自驗**：產一輪可驗證任務的 commit，確認含指令輸出；WI-H1 的審查能據此稽核。

### WI-H3 — 可選 `verify_command` 硬閘 ⬜ 待實作（唯一的程式工作）
- **目的**：給需要機器級確定性的專案一個逃生門——Framework 自己跑一條指令、只看 exit code，不信任 agent 自評。預設關閉，零行為改變。
- **新增**：`engine/verify.py`
  ```python
  def run_verify(cfg: dict, log_both) -> bool | None:
      """讀 cfg['verify']['default_command']；空字串 → 回 None（整步略過）。
      否則在 repo 根 subprocess 跑（timeout = cfg['verify']['timeout_seconds']），
      輸出寫 .loop_state（或 verification/ log）。回 passed: True/False。"""
  ```
- **改 config**：`engine/config.py` `DEFAULTS` 加：
  ```python
  "verify": {"default_command": "", "timeout_seconds": 1800},
  ```
- **接 loop.py**：在 `_run_execute_locked` 與 `_run_tree_execute_locked` 的 `git_guard(cfg, i, log_both)` 之後呼叫：
  ```python
  vr = run_verify(cfg, log_both)
  if vr is False:
      set_val(control, "last_round_result", "FAIL")
      set_val(control, "last_round_mode", "驗證")   # 讓既有 is_fail_verify 邏輯接手
  # vr is None（未設定）或 True → 不動現有流程
  ```
  之後既有的 `update_stuck_state` 會把 FAIL 納入震盪/升級判定，**不需自建修正 task 機制**。
- **鐵則**：
  - `default_command:""` 時 `run_verify` 回 `None`，這步零作用——既有行為（flat / tree / 無 TREE.md）必須逐位元組不變。
  - best-effort 包 try/except：verify 子程序自身爆掉只 log warning，不可中斷主迴圈。
- **自驗**：
  1. default 空 → flat 與 tree 各跑一輪，行為與改動前一致。
  2. `default_command: "exit 1"` → `last_round_result=FAIL`、log 落檔、迴圈續跑、下一輪被既有震盪邏輯接手。
  3. `default_command: "exit 0"` → 不影響收斂。
  4. 指令逾時 → 視為 FAIL，不卡死迴圈。

### WI-H4 — 迴歸測試 ⬜ 待實作
- `engine/tests/test_verify.py`：`run_verify` 對空/0/非0/逾時各情境回值正確。
- 迴歸冒煙：無 `verify` 設定的既有 workspace 跑一輪，輸出與改動前一致（保護 WI-H3 鐵則）。

## 2. 不做什麼（明確邊界）

- **不建知識層**：無 index/graph、retrieval、context pack、knowledge update、task metadata 擴充、adapter 正式化（本期不做）。
- **不建 verification 子系統**：無 scope→command registry、無分級（compile/unit/integration/...）、無結構化 `verification_result` schema。只有單一可選 `verify_command`。
- **不改控制模型**：控制權維持現狀（tree 模式 Framework 選 task、flat 模式 agent 自選）。因為不搬知識編排進 framework，先前「控制模型反轉」的大改不需要，rules 也只動了 acceptance 證據那兩處。
- **不動迴圈結構 / 不改既有 fail-closed 審查放行條件**。

## 3. Definition of Done

- 可驗證任務標 PASS 卻無證據時，獨立審查輪會 REVERT（WI-H1/H2）。
- 設了 `verify_command` 的專案，指令失敗會讓該輪 `last_round_result=FAIL` 並由既有震盪/升級邏輯處理（WI-H3）。
- 未設 `verify_command` 的專案行為與本次改動前完全一致（WI-H3/H4 鐵則）。

## 4. 進度

| WI | 內容 | 狀態 |
|---|---|---|
| H1 | git-review-gate §2-11 驗收證據紅線 | ✅ 已落地（rules） |
| H2 | boot-sequence STEP 9 留證鐵則 | ✅ 已落地（rules） |
| H3 | 可選 verify_command（verify.py + config + loop 接線） | ⬜ 待實作（程式） |
| H4 | verify 測試 + 迴歸冒煙 | ⬜ 待實作 |
