# 🔧 計畫書 1 — Bugfix 與夜間跑安全網（Hardening）

> **狀態**：待執行
> **依賴**：無（本系列第一份）
> **產出 branch**：`refactor/1-bugfix-and-hardening`
> **對應 review**：`docs/review/2026-07-02-framework-review.md` §3（B1–B10）、§4.2（快速失敗/牆鐘/通知）、§4.3（RUN_REPORT）

## 0. 目標

1. 修復 10 個已確認缺陷，其中 **B1 是啟動 blocker**（新專案 preflight 必然失敗），最優先。
2. 補齊「無人值守整晚跑」缺的三個安全機制：**快速失敗偵測**、**牆鐘上限**、**終止通知**。
3. 終止時自動產出人類可讀的 **RUN_REPORT.md**。
4. 建立 CI 煙霧測試，保證「B1 這種等級的 regression 不會再靜默存活」。

**不在本計畫範圍**：branch 模式、`loop` CLI、schema 翻新（見計畫書 2/4）。

---

## T1｜修 B1：preflight 移除 tree prompts 殘留檢查（P0 blocker）

**現況**：`engine/utils.py` 中 `structured_preflight()`（約 :264-268）與死碼版 `preflight()`（約 :159-164）都要求 prompts 必須包含 `tree_decompose`、`tree_decompose_gate`。tree 功能已移除、`engine/prompts.yaml` 沒有這兩鍵 → `agent_prompts` 檢查恆為 error → **plan/execute 兩個 stage 的 preflight 必然失敗，引擎啟動不了**。

**變更規格**：
- 必要 prompt 鍵集合定為常數 `REQUIRED_PROMPT_KEYS = ("base", "escalation", "git_review", "plan", "plan_gate")`，定義在 `engine/config.py`，`utils.py` 引用它（單一事實來源）。
- 移除所有 `tree_decompose` / `tree_decompose_gate` 字樣（`grep -rn "tree_decompose" engine/` 應為 0 筆）。

**驗收**：
- 新測試 `test_preflight_default_prompts_ok`：以框架預設 prompts（load_config 不帶專案 config）呼叫 `structured_preflight(cfg, "plan")`，斷言 `agent_prompts` 該項 `ok == True`。
- 新測試 `test_preflight_missing_prompt_fails`：刪掉 `base` 後斷言該項 `ok == False` 且 severity 為 error。

## T2｜修 B2：刪除 utils.py 重複定義的死碼

**現況**：`engine/utils.py` 定義了兩次 `preflight()` 與兩次 `report_preflight()`（:143-201、:204-212 為舊 tuple 版；:321-330 覆蓋之）。舊版是死碼，且兩版訊息不一致。

**變更規格**：
- 刪除舊 tuple 版 `preflight` / `report_preflight`，只留 structured 版。
- 舊版中「`REQUIREMENTS CONFIRMED` 未標記」的**警告文案**比新版清楚（含指引到 bootstrap STEP 4），把該文案合併進 structured 版的 `requirements_confirmed` 檢查 detail。

**驗收**：`grep -c "def preflight" engine/utils.py` == 1；`grep -c "def report_preflight" engine/utils.py` == 1；既有測試全綠。

## T3｜修 B3：plan_loop 卡住升級的角色標籤錯誤

**現況**：`engine/plan_loop.py` :261-264、:275 用 `model_tier_label(cfg, "decompose", …)`——`roles` 無 `decompose` 鍵（tree 殘留），fallback 成 `normal`；實際選模型用的是 `plan` 角色（預設 thinking）。log 顯示與實際不符，且 plan 已在最高層時「升級」是 no-op 卻宣稱升級。

**變更規格**：
1. 三處 `"decompose"` 全改為 `"plan"`。
2. `model_tier_label()` 已有「已在最高層 → 回傳 base_key」邏輯；plan_loop 升級分支要利用它：若 `model_tier_label(cfg, "plan", 1) == model_tier_label(cfg, "plan", 0)`（無處可升），log 改輸出「plan 角色已是最高層模型，無法再升級；再無進展將交人類」，不輸出「升級模型」。

**驗收**：新測試 `test_plan_stuck_label_uses_plan_role`：roles 用預設值時，斷言 plan_loop 升級路徑取得的 tier label 基於 `plan` 角色；`grep -rn '"decompose"' engine/` 為 0 筆。

## T4｜修 B4：Review Gate revert 失敗的災難性 fallback

**現況**：`engine/loop.py` :216-220，`git revert` 失敗時 fallback 執行 `git reset --hard last_safe_sha` + `git clean -fd`。這違反 `rules/git-safety.md` §2 紅線；`clean -fd` 會刪掉使用者所有未追蹤檔案（其他 workspace 產物、個人筆記）。

**變更規格**：revert 失敗時**不做任何自動還原**，改為停機交人：
```
revert_res.returncode != 0:
  1. subprocess.run(["git", "revert", "--abort"])   # 清掉半套 revert 狀態（失敗可忽略）
  2. set_human_required(control, True, "review_revert_failed",
       f"Git Review Gate 判定 REVERT 但自動 revert 失敗（可能有衝突）。原因：{reason}",
       run_id=..., source="execute_loop",
       suggested_action="人工檢查 git status / 衝突，手動 revert 或修復後 resume。")
  3. append_round_record type="human_required"
  4. run_git_review_gate 回傳 (False, "review_revert_failed", <訊息>) → 外層走既有 human_required 停機路徑（exit 2）
```

**驗收**：
- `grep -n "reset --hard\|clean -fd" engine/` 為 0 筆。
- 新測試 `test_review_revert_failure_halts_instead_of_hard_reset`：mock `subprocess.run` 使 revert 失敗，斷言回傳 halt_reason == `review_revert_failed` 且未呼叫 reset/clean。

## T5｜修 B5：失敗指紋改用「本輪 commit 的實際 diff」

**現況**：`engine/utils.py` :358-362 `fail_fingerprint()` 用 `changed_files()`（working tree dirty 檔案）。agent 正常於 STEP C commit 後 working tree 乾淨 → 指紋退化成只剩 fail_tasks，震盪偵測解析度下降。

**變更規格**：
- `fail_fingerprint(control, changed: list[str])` 增加參數：改動檔案清單由呼叫端提供。
- `engine/loop.py` 兩個呼叫點（`update_stuck_state` 內 append、round record 的 `fail_fp`）改傳 `changed_files_between(git_head_before, current_head)` 的結果（該輪實際 commit diff；此值本輪已算過，重用變數、不要重跑 git）。
- `reconstruct_history_and_progress` 不受影響（讀的是已存的 fingerprint 字串）。

**驗收**：新測試 `test_fail_fingerprint_uses_commit_diff`：兩輪 fail_tasks 相同、commit diff 檔案不同時，指紋不同；working tree 乾淨時指紋仍含檔案成分。

## T6｜修 B7：sync_framework_docs 移出每輪迴圈

**現況**：`loop.py` :458、`plan_loop.py` :191 每輪呼叫 `sync_framework_docs`，同步 + 自動 commit 發生在 Review Gate 取 diff 之前，導致框架文件 commit 混進「上一輪未審 diff」，且污染一輪一 commit 的還原點語意。

**變更規格**：兩個迴圈都改為**只在進迴圈前呼叫一次**（`_run_execute_locked` / `_run_plan_locked` 的 for 迴圈之前、首次 review gate 之前）。同步造成的 commit 之後，若 `last_safe_sha` 已存在，**把 `last_safe_sha` 前移到同步 commit 的 HEAD**（避免第一次 review gate 審到框架文件同步 diff）。

**驗收**：新測試 `test_sync_framework_docs_called_once_per_run`（mock 計數）；手動驗證：跑 3 輪的整合測試中 `chore: sync updated loop framework docs` commit ≤ 1 個。

## T7｜修 B8/B9：死碼清理與防禦性 return

**變更規格**：
1. `plan_loop.py` :132-133 重複的 `cfg["run_id"] = run_id`、:206-207 重複的 `git_head_before = git_head()` 各刪一行。
2. `loop.py` `run_git_review_gate()` 函式末尾（PASS 分支之後）加 `return True, "", ""`（理論上不可達，防 decision 枚舉未來擴充時回傳 None 造成 TypeError）。
3. 加入 `ruff` 設定檔（`pyproject.toml`，只開 `F`（pyflakes）規則），修完既有告警。**授權新增 dev 依賴 ruff（僅 CI 用，不進 runtime requirements.txt）**。

**驗收**：`ruff check engine/ *.py` 零錯誤；CI 步驟包含 ruff。

## T8｜修 B10 + 文件門檻數字漂移（B6）

**變更規格**：
1. `generators/2-plan-review-gate.md` :20-26 移除 `config.min_unit.*` 引用（該 config 已刪）：煙霧圍欄描述改為定性表述「單一任務改動範圍明顯過大（跨多檔多關注點）→ 回頭確認是否包了多個自然單位」。
2. 門檻數字單一事實來源化：
   - `rules/state-model.md` :76 與 `rules/state-cli-guide.md` :155 的「threshold 預設為 5」改為「門檻 = 該任務所屬 phase 的 `converge_threshold`（見 loop.config.yaml），CLI 會讀取設定驗證」。
   - **同時檢查 `engine/state.py` 的 CONVERGED 門檻守衛實際讀哪裡**：若目前寫死 5，改為讀取 config `phases[i].converge_threshold`（找不到 config 時 fallback 5 並輸出 warning）。state.py CLI 需要能定位 config：以 `--state` 路徑同目錄的 `loop.config.yaml` 為準。
3. `rules/convergence.md` 門檻表述保持「典型 2~3、由 plan 逐階段自訂」不變（它是對的）。

**驗收**：`grep -rn "min_unit" generators/ rules/ engine/` 為 0 筆；`grep -rn "預設為 5\|預設 5" rules/` 為 0 筆；新測試 `test_converged_threshold_reads_config`。

## T9｜快速失敗偵測（cli_failing breaker）★ 夜間跑關鍵

**動機**：CLI 未登入 / token 半夜過期 / 模型名錯 → agent process 幾秒內 rc≠0 秒退。現行機制要靠 idle 簽章累積 `stall_threshold=10` 輪才升級模型（對 auth 錯誤無效），會空燒到 max_rounds。

**變更規格**：
1. `run_agent()` 回傳值擴充為 `(rc, killed, duration_seconds: float)`（兩個實作 `_run_agent_pty` / `_run_agent_pipe` 都量測）。所有呼叫端同步更新。
2. config 新增（`DEFAULTS["oscillation"]`）：`fast_fail_seconds: 30`、`fast_fail_limit: 3`。
3. `loop.py` 與 `plan_loop.py` 主迴圈：每輪 agent 結束後判定 `is_fast_fail = (not killed) and rc != 0 and duration < fast_fail_seconds`；連續計數（存記憶體即可，跨 run 不需持久化）。達 `fast_fail_limit` →
   - execute：`set_human_required(code="cli_failing", reason=f"agent process 連續 {n} 次於 {duration:.0f}s 內以 rc={rc} 退出，疑似 CLI 未登入/額度/模型名問題", suggested_action="檢查 agent CLI 登入狀態與模型名稱後 resume。")` → `finish("human_required", 2, "cli_failing")`。
   - plan：對稱使用 `set_plan_human_required(code="cli_failing", …)`。
4. 任一輪 `rc == 0` 或 `duration >= fast_fail_seconds` 或 killed → 計數歸零（killed 已有 watchdog 路徑，不算 fast fail）。
5. `round_finished` record 新增欄位：`duration_seconds`（所有輪都記，供報告與 trace 分析）。

**驗收**：新測試 `test_fast_fail_breaker_halts_after_3`（mock run_agent 回 (1, None, 2.0)）、`test_fast_fail_reset_on_success`、`test_round_record_has_duration`。

## T10｜牆鐘上限 max_wall_seconds

**變更規格**：
1. config 新增 `runtime.max_wall_seconds: 0`（0 = 關閉）。
2. `loop.py` 主迴圈每輪頂端（`check_stop_requested` 之後）：`time.time() - start_epoch > max_wall_seconds` →
   - log「⏰ 已達牆鐘上限」、`set_human_required(code="wall_clock_reached", …, suggested_action="檢視 RUN_REPORT 後決定 resume 或驗收。")`、`finish("human_required", 2, "wall_clock_reached")`。
   - 走 human_required 路徑的原因：讓 T12 的報告與 T11 的通知自動觸發，語意是「時間到、待人裁決」而非失敗。
3. `plan_loop.py` 同樣支援（plan 通常短，但 config 同鍵共用）。
4. loop.config.template.yaml 進階旋鈕註解區補上此鍵，註明用法（例：`36000` = 最多跑 10 小時）。

**驗收**：新測試 `test_wall_clock_halts`（max_wall_seconds=1 + mock 時間）。

## T11｜終止通知 notify_cmd

**變更規格**：
1. config 新增 `runtime.notify_cmd: ""`（空 = 關閉）。shell 樣板，佔位符：`{status}`（complete/human_required/…）、`{code}`（human_required_code 或空）、`{workspace}`、`{repo}`（repo 根絕對路徑）、`{report}`（RUN_REPORT.md 絕對路徑或空）、`{run_id}`。
2. 新函式 `utils.notify(cfg, status, code, report_path)`：
   - `fmt_prompt` 同款 replace 代入 → `subprocess.run(shlex.split(...), timeout=30)`；佔位值先經 `shlex.quote` 不可注入。
   - 任何失敗（找不到指令/逾時/非零 rc）只 log warning，**絕不影響引擎退出流程**。
3. 呼叫點：`loop.py` 與 `plan_loop.py` 的 `finish()` 內、`append_run_finished` 之後，對**所有**終止狀態觸發（complete / human_required / preflight_failed 除外——preflight 失敗時人就在終端機前，不通知）。
4. 文件：README「其他你可能在意的」加一段範例（curl Slack webhook）。

**驗收**：新測試 `test_notify_cmd_invoked_with_placeholders`（notify_cmd 指向寫檔的假腳本，斷言收到代入後參數）、`test_notify_failure_does_not_raise`。

## T12｜RUN_REPORT.md 收工報告產生器

**變更規格**：
1. 新檔 `engine/report.py`，核心函式：
   ```python
   def generate_run_report(cfg, *, run_id, final_status, human_code="") -> str:
       """回傳寫出的報告路徑（.loop/<ws>/RUN_REPORT.md，整檔覆寫）。"""
   ```
2. **資料來源與計算邏輯**（全部是既有資料的消費端，不新增寫入路徑）：
   - `rounds.jsonl`：filter `run_id` 相符的 records。
     - 起訖時間：`run_started.ts` → `run_finished.ts`（或最後一筆 ts）；時長 = 差值。
     - 輪數統計：`round_finished` 依 `model_tier` 分組計數；`killed` 計數；`duration_seconds` 總和/平均。
     - 夜間事件：`type in (review_revert, human_required, loop_complete)` 的 records 逐筆列出（ts + message）；`stuck_level` 發生變化的輪列出（升級事件）。
   - `state.json`：
     - 進度：`current_phase` / 各 phase 任務 status 計數（CONVERGED/FROZEN/TODO/DRAFTED/NEEDS_REVISION）/ `p{i}_consecutive_pass`。
     - Issues：OPEN 的逐筆列出（id/level/title），BLOCKING 排前。
     - 需求驗收表：若 state 或 config 有 `requirements_map`（R### → task ids）：全部對應任務 CONVERGED → `✅`；任一 FROZEN 或有關聯 OPEN BLOCKING issue → `❌`；其餘 → `🔶 進行中`。無 map 時本節輸出「（plan 未提供 requirements_map，無法逐條對照）」。
   - git：`git log --oneline <run 期間>` 的 commit 數；`git diff --stat <run 首個 commit 的 parent>..HEAD` 摘要（取不到就略過該節，不可拋錯）。
3. **報告版型**（節序固定，供人快速掃讀；全 zh-TW）：
   `結果橫幅 → 時間與輪數 → 進度總覽 → 需求驗收表 → 待你裁決（FROZEN + BLOCKING + suggested_action）→ 夜間事件時間軸 → diff 摘要 → 建議下一步`。
   「建議下一步」規則：complete → 「檢視 diff 後驗收」；human_required → 引用 `suggested_human_action`；max_rounds/wall_clock → 「檢視進度後 resume 或調整門檻」。
4. 呼叫點：`loop.py` / `plan_loop.py` 的 `finish()` 內產生（任何 exception 捕捉後 log warning，不影響退出）；產出路徑傳給 T11 的 `notify()`。
5. 獨立 CLI：`python3 engine/report.py --workspace <ws>`（取該 workspace rounds.jsonl 最後一個 run_id 重新產生）。
6. RUN_REPORT.md 加進 init-project.py 寫的 `.gitignore` 樣板？**不加**——報告要進版控（隔天驗收的證據），但每次 run 整檔覆寫不累積。

**驗收**：
- 新測試 `test_generate_run_report_complete` / `test_generate_run_report_human_required`：以 fixture rounds.jsonl + state.json 產報告，斷言含「結果」「需求驗收」「待你裁決」節與正確計數。
- 新測試 `test_report_survives_missing_data`：空 rounds.jsonl / 無 requirements_map 不拋錯。

## T13｜CI 煙霧測試

**變更規格**：
1. 新增 `.github/workflows/ci.yml`：
   - `python3 -m pytest engine/ -x`
   - `ruff check engine/ *.py`
   - **preflight 煙霧**（B1 級 regression 防線）：腳本建 tmp git repo（含 user.email 設定）→ `python3 init-project.py <tmp> --name smoke` → 在 tmp 內把 config 的三個 model 佔位改成假值 `m1/m2/m3` → `python3 engine/run.py --preflight --json --workspace smoke`，斷言 JSON 中 `agent_prompts.ok == true` 且整體無「missing prompt」類 error（整體 `ok` 可為 false——build_cmd 找不到是 warning、其他項不擋）。
2. 煙霧腳本落在 `engine/tests/smoke_preflight.sh`（或 pytest 化，二選一，pytest 化優先）。

**驗收**：CI 在本 branch 全綠；故意把 `base` 從 prompts.yaml 刪掉時 CI 轉紅（驗證防線有效後還原）。

---

## 最終驗收清單（全部通過才算完成本計畫書）

- [ ] `grep -rn "tree_decompose\|min_unit" engine/ rules/ generators/` 零筆
- [ ] 全新 tmp repo 走 init → `run.py --preflight` 不再出現 prompts error（T13 煙霧測試綠）
- [ ] `grep -rn "reset --hard\|clean -fd" engine/` 零筆
- [ ] `pytest engine/` 全綠，新增測試 ≥ 12 個（T1×2、T3、T4、T5、T6、T8、T9×3、T10、T11×2、T12×3）
- [ ] `ruff check` 零錯誤；CI workflow 存在且包含 pytest + ruff + preflight 煙霧
- [ ] 手動整合驗證：用假 agent 指令（`build_cmd: "false"`）跑 `run.py --stage execute`，3 輪內以 `cli_failing` 停機、產出 RUN_REPORT.md、notify_cmd 假腳本被呼叫
- [ ] README 與 engine/README.md 補上：notify_cmd / max_wall_seconds / RUN_REPORT / fast-fail 四項說明
