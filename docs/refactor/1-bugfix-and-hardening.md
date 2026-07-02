# 🔧 計畫書 1 — Bugfix 與夜間跑安全網（Hardening）

> **狀態**：待執行
> **依賴**：無（本系列第一份）
> **產出 branch**：`refactor/1-bugfix-and-hardening`
> **對應 review**：`docs/review/2026-07-02-framework-review.md` §3（B1–B10）、§4.2（快速失敗/牆鐘/通知）、§4.3（RUN_REPORT）

## 0. 目標

1. 修復 10 個已確認缺陷，其中 **B1 是啟動 blocker**（新專案 preflight 必然失敗），最優先。
2. 補齊「無人值守整晚跑」缺的安全機制：**快速失敗偵測**、**牆鐘上限**、**終止通知**、**外部心跳（dead man's switch）**、**磁碟守衛**、**殘留鎖秒級接手**、**CLI 版本遙測**。
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

**現況（收官重審後校正）**：`engine/utils.py` :358-362 `fail_fingerprint()` 用 `changed_files()`——實際是 `git diff --name-only HEAD~1 HEAD`（**最後一個 commit** 的檔案清單，git_utils.py:21-30），不是 working tree dirty 檔案。真正的缺陷有二：(a) 只涵蓋最新**一個** commit——本輪若有多個 commit（agent commit + git_guard autocommit）只算到最後一個；(b) 本輪 agent **沒有** commit 時，拿到的是**上一輪**commit 的檔案清單——指紋張冠李戴，震盪偵測被污染。

**變更規格**：
- `fail_fingerprint(control, changed: list[str])` 增加參數：改動檔案清單由呼叫端提供。
- `engine/loop.py` 兩個呼叫點（`update_stuck_state` 內 append、round record 的 `fail_fp`）改傳 `changed_files_between(git_head_before, current_head)` 的結果（**本輪起訖 HEAD 的實際 diff**，涵蓋本輪全部 commits；本輪無 commit 時為空清單，不再沿用上一輪；此值本輪已算過，重用變數、不要重跑 git）。
- `reconstruct_history_and_progress` 不受影響（讀的是已存的 fingerprint 字串）。

**驗收**：新測試 `test_fail_fingerprint_uses_round_range_diff`（兩輪 fail_tasks 相同、本輪 diff 檔案不同 → 指紋不同）、`test_fail_fingerprint_empty_when_no_commit_this_round`（本輪無 commit → 檔案成分為空，不得等於上一輪指紋）、`test_fail_fingerprint_covers_multi_commit_round`（agent commit + autocommit 兩個 commit 的檔案都入指紋）。

## T6｜修 B7：sync_framework_docs 移出每輪迴圈

**現況**：`loop.py` :458、`plan_loop.py` :191 每輪呼叫 `sync_framework_docs`，同步 + 自動 commit 發生在 Review Gate 取 diff 之前，導致框架文件 commit 混進「上一輪未審 diff」，且污染一輪一 commit 的還原點語意。

**變更規格**：兩個迴圈都改為**只在進迴圈前呼叫一次**（`_run_execute_locked` / `_run_plan_locked` 的 for 迴圈之前、首次 review gate 之前）。
🚨 **last_safe_sha 的前移必須是條件式的**：只有當「同步前的 HEAD == 既有 `last_safe_sha`」（= 上個 run 沒有留下未審 commit）時，才把 `last_safe_sha` 前移到同步 commit 的 HEAD。若兩者不等——上個 run 以 max_rounds / human_required / crash 結束時，最後一輪的 agent commit 尚未被審查，**現況正是靠新 run 的首次 gate 補審**——`last_safe_sha` 一律不動，讓首次 gate 審「未審 commits + 同步 commit」的合併 diff（框架文件噪音可接受；計畫書 3 T7 落地後同步 commit 會被規約豁免、噪音消失）。❌ 無條件前移＝把未審 commit 洗白，破壞 B7 要保護的審查語意。

**驗收**：新測試 `test_sync_framework_docs_called_once_per_run`（mock 計數）、`test_sync_advances_last_safe_only_on_clean_base`（上個 run 留下未審 commit 的 fixture：last_safe 不前移、首次 gate 的 diff 含該 commit）；手動驗證：跑 3 輪的整合測試中 sync commit ≤ 1 個。

## T7｜修 B8/B9：死碼清理與防禦性 return

**變更規格**：
1. `plan_loop.py` :132-133 重複的 `cfg["run_id"] = run_id`、:206-207 重複的 `git_head_before = git_head()` 各刪一行。
2. `loop.py` `run_git_review_gate()` 函式末尾（PASS 分支之後）加 `return True, "", ""`（理論上不可達，防 decision 枚舉未來擴充時回傳 None 造成 TypeError）。
3. 加入 `ruff` 設定檔（`pyproject.toml`，只開 `F`（pyflakes）規則），修完既有告警。**授權新增 dev 依賴 ruff（僅 CI 用，不進 runtime requirements.txt）**。

**驗收**：`ruff check engine/ *.py` 零錯誤；CI 步驟包含 ruff。

## T8｜修 B10 + 文件門檻數字漂移（B6）

**變更規格**：
1. `generators/2-plan-review-gate.md` :20-26 移除 `config.min_unit.*` 引用（該 config 已刪）：煙霧圍欄描述改為定性表述「單一任務改動範圍明顯過大（跨多檔多關注點）→ 回頭確認是否包了多個自然單位」。
2. 門檻的單一事實來源裁決（收官重審後校正——原版指示「改讀 config」是錯的，會覆蓋合法的異質門檻）：
   - **實況**：CONVERGED 守衛讀的是**每個任務自己的 `threshold` 欄位**（state.py:1397/1406，`task-add --threshold` 設定、預設 5）——既不是寫死 5、也不該改讀 config。這個 per-task 設計是對的：plan 可以給不同風險的任務不同門檻。
   - **裁決（寫進文件，三處統一）**：門檻的單一事實來源 = **任務自身的 `threshold` 欄位**；config 的 `phases[].converge_threshold` 是 **plan 期的預設值輸入**（generator 建任務時據此填 per-task threshold，可依任務風險逐一調高）；執行期引擎/CLI 只讀 per-task 值。
   - `rules/state-model.md` :76 與 `rules/state-cli-guide.md` :155 的「threshold 預設為 5」改為上述裁決的表述；`1-plan-generator.md` 補一句「task-add 時 threshold 依 phase converge_threshold 填入、高風險任務可調高」。
3. `rules/convergence.md` 門檻表述保持「典型 2~3、由 plan 逐階段自訂」不變（它是對的）。

**驗收**：`grep -rn "min_unit" generators/ rules/ engine/` 為 0 筆；`grep -rn "預設為 5\|預設 5" rules/` 為 0 筆；新測試 `test_converged_guard_uses_per_task_threshold`（同 phase 兩任務不同 threshold，各自按自己的值把關）。

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

## T13b｜修 B11：stop_requested 被誤標為 broken_control_file（收官重審時發現）

**現況**：`engine/loop.py` :449-450，`check_stop_requested` 成立（人主動要求停止，如 dashboard 的 stop）時，走 `finish("broken_control_file", 1, "broken_control_file")`——**主動優雅停止被記成「狀態檔毀損」**：rounds.jsonl 的 final_status 錯、之後的 RUN_REPORT/通知/errors.md 連結全部跟著錯。`plan_loop.py` 的同路徑是正確的（`finish("stopped", 1)`）。

**變更規格**：loop.py 該分支改為 `finish("stopped", 1)`（無 human_required_code——主動停止不是交人事件，不設 human_required 旗標）；log 訊息改「⏹ 收到停止請求，本輪前優雅停止」。

**驗收**：`test_stop_requested_finishes_as_stopped`（觸發 stop 檔，斷言 run_finished 的 final_status=="stopped" 且 human_required 未被設）。

## T14｜Dead man's switch：外部心跳

**動機**：`notify_cmd`（T11）只在引擎**正常走到終止流程**時發通知；OOM、斷電、`kill -9`、SSH session 帶走 process 這類**靜默死亡**不會發任何東西——早上看到「沒有壞消息」是假象。監控活著的東西，不能靠它自己報死訊，要靠外部服務偵測「心跳停了」。

**變更規格**：
1. config 新增 `runtime.heartbeat_url: ""`（空 = 關閉）。
2. 引擎每輪頂端（與 `touch_run_lock` 同位置）對該 URL 發一次 HTTP GET（標準庫 `urllib.request`，timeout 10s）；`plan_loop` 同樣支援。
3. 失敗（網路錯/非 2xx）只 log warning、**絕不影響迴圈**；連續失敗不累計任何停機邏輯（心跳的可靠性歸外部服務管）。
4. `finish()` 時對 `{heartbeat_url}/fail` 或 `?status=<status>` 發最後一擊（healthchecks.io 慣例：正常完成 ping 本體、失敗 ping `/fail`；URL 樣板容許 `{status}` 佔位）。
5. 文件：README 與「下班前 checklist」補 healthchecks.io / 自架 uptime-kuma 的設定範例——**建議的告警門檻 = 2 × (round_timeout + interval)**。

**驗收**：`test_heartbeat_pinged_each_round`（mock urlopen 計數）、`test_heartbeat_failure_never_raises`、`test_finish_pings_status`。

## T15｜run.lock 加 PID 存活檢查 + 安全接手

**現況**：殘留鎖只靠 mtime 老化判定（`max(3600, 3×round_timeout)`），上次 crash 後要等最多三小時或人工刪鎖檔（README 教使用者裸手 `rm`——危險且不友善）。鎖檔其實已寫入 pid，只差一步驗活。

**變更規格**：
1. 鎖檔內容改為 JSON：`{"pid": …, "hostname": …, "started": …}`。
2. `acquire_run_lock` 判定順序：
   - 鎖存在且 **hostname 相同** → `os.kill(pid, 0)` 驗活：process 已死 → log「接手殘留鎖（pid=N 已不存在）」直接接手；活著 → `WorkspaceBusy`（不看 mtime）。
   - hostname 不同（NFS/容器共享目錄）→ 退回既有 mtime 老化判定（跨機無法驗 pid）。
3. 心跳 `touch_run_lock` 保留（跨機情境的老化判定仍需要）。

**驗收**：`test_lock_takeover_dead_pid`、`test_lock_busy_alive_pid`、`test_lock_foreign_host_falls_back_to_mtime`。

## T16｜每輪磁碟空間守衛

**動機**：doctor 開跑前查一次磁碟，但整晚的 log / npm install / build 產物可能半夜填滿磁碟——**磁碟滿時 git 寫入會產生半套物件，是少數能真正毀掉還原點的故障**。與其寫壞，不如優雅停。

**變更規格**：
1. config 新增 `runtime.min_free_disk_mb: 500`。
2. 引擎每輪頂端 `shutil.disk_usage(repo).free` 低於門檻 → log + `set_human_required(code="disk_low", suggested_action="清理磁碟（log/建置產物/docker）後 resume。")` → `finish("human_required", 2, "disk_low")`（走 T11 通知 + T12 報告路徑）。
3. 低於 2× 門檻時先出一次 warning（給人時間在通知裡看到趨勢）。

**驗收**：`test_disk_guard_halts_below_threshold`、`test_disk_guard_warns_at_2x`（mock disk_usage）。

## T17｜agent CLI 版本遙測

**動機**：agent CLI 半夜自動更新導致行為突變是真實故障模式；沒有版本記錄，「昨晚突然變笨」無法歸因。

**變更規格**：
1. run 啟動時（`run_started` record 前）對 `build_cmd` 的執行檔跑一次 `<exe> --version`（timeout 10s，失敗記 `"unknown"`），寫入 `run_started` record 的 `cli_version` 欄位。
2. 與**上一個 run** 的 `run_started.cli_version` 不同 → log 一行「⚠ agent CLI 版本變更：A → B」，並在 RUN_REPORT（T12）的「時間與輪數」節標示。
3. `loop doctor`（計畫書 2 T4）輸出同一資訊。

**驗收**：`test_run_started_records_cli_version`、`test_report_flags_version_change`。

---

## 最終驗收清單（全部通過才算完成本計畫書）

- [ ] `grep -rn "tree_decompose\|min_unit" engine/ rules/ generators/` 零筆
- [ ] 全新 tmp repo 走 init → `run.py --preflight` 不再出現 prompts error（T13 煙霧測試綠）
- [ ] `grep -rn "reset --hard\|clean -fd" engine/` 零筆
- [ ] `pytest engine/` 全綠，新增測試 ≥ 22 個（T1×2、T3、T4、T5、T6、T8、T9×3、T10、T11×2、T12×3、T14×3、T15×3、T16×2、T17×2）
- [ ] 心跳：設 heartbeat_url 指向本地假 server 跑 3 輪，收到 ≥3 次 ping + finish 一擊；拔掉 server 迴圈照常跑
- [ ] 殘留鎖：kill -9 引擎後立即重啟，秒級接手（不再等 mtime 老化）；引擎運行中重複啟動仍被擋
- [ ] `ruff check` 零錯誤；CI workflow 存在且包含 pytest + ruff + preflight 煙霧
- [ ] 手動整合驗證：用假 agent 指令（`build_cmd: "false"`）跑 `run.py --stage execute`，3 輪內以 `cli_failing` 停機、產出 RUN_REPORT.md、notify_cmd 假腳本被呼叫
- [ ] README 與 engine/README.md 補上：notify_cmd / max_wall_seconds / RUN_REPORT / fast-fail 四項說明
