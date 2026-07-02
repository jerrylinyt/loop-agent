# 🧨 計畫書 3 — 產出檔增長治理（Context / Growth Budget 執法）

> **狀態**：待執行
> **依賴**：計畫書 1（rounds.jsonl 的 duration 欄位、finish 流程）；與計畫書 2 可並行
> **產出 branch**：`refactor/3-context-growth-budget`
> **對應 review**：§2 診斷 A 的 context 面向；本計畫同時回答使用者追問：「log / state / event json 太長被 agent 讀到，需要處理嗎？」——**需要，且現況有五個未執法的增長源**。

## 0. 問題定義：增長源盤點（現況實測）

`rules/context-budget.md` 的紀律寫得很對，但**大半沒有機制執法**。逐一盤點：

| # | 增長源 | 誰會讀到 | 現況防護 | 判定 |
|---|--------|----------|----------|------|
| G1 | `state.json` | **agent 每輪 STEP 0 全讀**；引擎每輪多次 parse | `control_max_bytes: 60000` 與 `journal_in_control_keep` **定義了但引擎全程沒用（死設定）**；`reset_history` 無上限 append（run.py:168）；resolved issues 留在索引 | ❌ 未執法 |
| G2 | Review Gate prompt | **每輪把「完整 state.json 內容 + 完整 diff」內嵌進 prompt**（loop.py:123-140） | 無任何上限——state 越大、diff 越大，審查輪 context 越肥，弱模型審查品質越差 | ❌ 未執法，**最大的單點** |
| G3 | `rounds.jsonl` / `state_events.jsonl` | 引擎啟動整檔逐行 parse（state.py:627）；dashboard/collect_traces 讀 | append-only、**無輪替**；長專案數萬行後啟動變慢；不進 agent context（在 .loop_state，gitignore） | ⚠️ 引擎效能問題，非 context 問題 |
| G4 | 證據檔 `.reverify/ .enum/ .validate/` | 進版控、進 Review Gate 的 diff；正常不被執行 agent 回讀 | 每輪新增、永不清理；單檔長度無上限（agent 可能貼整包 build log） | ❌ 未執法 |
| G5 | `loop.log` / `plan.log` | 規則禁止 agent 讀；人用 | rotation 已有（50MB×5）✅ | ✅ 已治理 |
| G6 | `phases/*.md` / issues 檔 | agent 按需讀單節/單檔 | plan 期定型、一 Issue 一檔 ✅；但 issues **索引**在 state.json 內只增不減 | ⚠️ 併入 G1 |
| G7 | `HUMAN_NOTES.md`（計畫書 2 新增） | 注入 prompt | 計畫書 2 已規定單則 4,000 字上限 ✅ | ✅ 設計時已治理 |

**治理原則**（本計畫的驗收基準）：
- **會進 agent context 的檔案**：必須有硬上限 + 超限的明確行為（擋下或壓縮），不能只靠規則散文。
- **只有引擎讀的檔案**：必須有輪替 + 尾讀，成本 O(1) 不隨歷史增長。
- **進版控但不進 context 的檔案**：必須有修剪政策，防 repo 膨脹與 diff 噪音。

> 註：計畫書 4（v3）會把「agent 每輪全讀 state.json」整個拿掉（引擎發任務卡），屆時 G1 對 agent 的影響歸零、只剩引擎效能面。**本計畫的執法機制在 v3 仍全部有效**（state 預算改保護引擎與 review gate，jsonl 尾讀不變），不是丟棄式工程。

---

## T1｜state.json 尺寸預算執法（G1）

**變更規格**：
1. 啟用死設定：`runtime.control_max_bytes`（預設維持 60000）。刪除從未使用的 `journal_in_control_keep` 鍵（config + template 註解）。
2. 引擎每輪頂端（`inspect_and_fix_blank` 附近）檢查 `os.path.getsize(state.json)`：
   - `> 80%` 上限：log warning 一次/每 run（含目前尺寸與最大增長區塊名）。
   - `> 100%`：先嘗試 **T2 自動壓實**；壓實後仍超限 → `set_human_required(code="state_too_large", suggested_action="state.json 超出 context 預算，檢查 plan 是否把明細塞進 state（應放 phases/issues 檔）。")` 停機。**超限不擋寫入、只擋下一輪**（避免把 agent 卡在寫不進狀態的死路）。
3. `state.py` 的 `save_state_json` 在寫入後回報尺寸（log debug），供 trace。

**驗收**：新測試 `test_state_size_warning_at_80`、`test_state_size_halts_at_100_after_compaction`。

## T2｜state.json 自動壓實（compaction）

**變更規格**：
1. 新函式 `state.compact_state(state_json_path) -> dict`（回傳統計），規則——把「歷史性、非決策必需」的內容搬到**引擎專用 archive**：
   - `reset_history`：只留最近 5 筆，其餘 append 到 `.loop_state/state_archive.jsonl`（一行一筆，`{"type":"reset_history", ...}`）。
   - `issues` 中 `status == RESOLVED` 的項目：整筆搬到 archive（`{"type":"issue_resolved", ...}`），state 索引只留 OPEN。`blocking_issues` 計數邏輯不受影響（本來就只數 OPEN+BLOCKING）。
   - 任務物件裡若存在歷史性陣列欄位（如未來的 `revert_history` / `evidence` 清單）：保留最近 `converge_threshold` 筆，其餘搬 archive。
   - **絕不動**：phases 結構、任務 status/conv、control 運行欄位、requirements_map（都是決策必需）。
2. 呼叫點：T1 的超限路徑 + `finish()` 收工時例行執行一次（run 結束順手瘦身）。
3. 壓實屬引擎寫入，走 `guarded_state_write` 的引擎 source，事後 git commit（`chore: compact state.json`）——在 run_branch 上，無污染顧慮。
4. `run.py` 的 `reset_execute_state_data` 中 `reset_history` append 處同步加「留 5 筆」上限（源頭節流）。

**驗收**：新測試 `test_compact_moves_resolved_issues_and_reset_history`、`test_compact_preserves_decision_fields`（壓實前後 `is_done` / task 狀態判定完全一致）。

## T3｜Review Gate prompt 內嵌上限（G2，最高優先）

**現況**：`loop.py run_git_review_gate` 把 `diff`（完整 `git diff last_safe..HEAD` 輸出）與 `state_json_content`（完整 state.json）字串直接代入 prompt。大 diff 輪（如 autocommit 補了一堆檔）prompt 可達數百 KB——弱模型直接被淹死，審查品質崩潰還照樣收錢。

**變更規格**：
1. config 新增 `runtime.review_embed_max_bytes: 30000`。
2. **diff 內嵌改為「導覽 + 截斷」**：
   - prompt 內嵌 `git diff --stat last_safe..HEAD` 全文（stat 很小）+ diff 本文**前 `review_embed_max_bytes` bytes**，截斷處插入明確標記：`…（diff 已截斷，完整內容請自行執行：{diff_range}）`。
   - `git-review-gate.md` 已指示審查 agent「使用工具獲取 diff」（rule :36-38），prompt 樣板同步強化：「內嵌內容僅供導覽，**逐項審查必須以你自己執行 `{diff_range}` 的輸出為準**」。
3. **state.json 內嵌改為「引擎生成的摘要 + 狀態 diff」**：
   - 移除 `state_json_content` 整檔內嵌。
   - 改嵌兩樣：(a) `state.py` 新函式 `summarize_for_review(state) -> str`（≤ 2KB：current_phase、各 phase 任務狀態計數、各計數器值、OPEN issues 索引行）；(b) `git diff last_safe..HEAD -- <state.json路徑>` 的輸出（**本輪狀態變更才是審查對象**，全文通常很小；同樣受 max_bytes 截斷保護）。
   - 審查紅線需要完整 state 時（如結構毀損判定），agent 自行讀檔——rule 補一句指引。
4. `prompts.yaml` 的 `git_review` 樣板與 `rules/git-review-gate.md` 同步更新措辭。

**驗收**：
- 新測試 `test_review_prompt_capped`（構造 200KB diff，斷言組出的 prompt 長度 < 60KB 且含截斷標記與 stat）。
- 新測試 `test_review_prompt_embeds_state_diff_not_full_state`。
- 手動：跑一輪真實 review，log 中 `[Git Review Prompt]` 長度肉眼確認在預算內。

## T4｜rounds.jsonl / state_events.jsonl 輪替與尾讀（G3）

**變更規格**：
1. **輪替**：run 啟動時（`run_started` 寫入前）檢查兩檔尺寸，任一 > `runtime.jsonl_rotate_max_mb`（新鍵，預設 20）→ `os.replace` 成 `.1`（保留 `jsonl_rotate_keep`（新鍵，預設 3）代，與 log rotation 同款輪替邏輯，抽共用函式 `utils.rotate_file_if_needed(path, max_mb, keep)`，`rotate_log_if_needed` 改為呼叫它）。
   - **輪替只發生在 run 邊界**：保證單一 run 的 records 不會被切在兩檔（報告與震盪重建都以 run 為單位）。
2. **尾讀**：`reconstruct_history_and_progress` 改為從檔尾讀：
   - 實作 `utils.tail_lines(path, max_bytes=512*1024) -> list[str]`（seek 到 `max(0, size-max_bytes)`，丟棄第一個不完整行）。
   - 重建邏輯只消費尾部行集。**正確性論證**：該函式只需要 (a) 最後一筆 `round_finished` 的 progress 欄位、(b) 最近 `osc_window`（預設 8）筆 FAIL 指紋、(c) 最後一次 `progressed` 之後的指紋——512KB 尾部遠大於任何合理視窗；萬一視窗不足（極端長行），degrade 成空歷史 = 與現況「新 run 從零開始累積」等價，安全。
   - `collect_traces.py` 讀全檔的行為**不變**（離線分析要完整歷史，含輪替檔：glob `rounds.jsonl*`——本計畫順手補上）。
3. `state_events.jsonl`（state.py 稽核事件）目前無讀取端，只做輪替即可。

**驗收**：新測試 `test_jsonl_rotate_at_run_boundary`、`test_reconstruct_from_tail_equals_full_read`（對 10k 行 fixture，尾讀與全讀重建結果相同）、`test_collect_traces_reads_rotated_files`。

## T5｜證據檔修剪政策（G4）

**變更規格**：
1. **單檔上限（源頭）**：`rules/convergence.md`、`completeness.md`、`boot-sequence.md` 涉及證據檔處補一條硬規：「證據檔單檔 ≤ 300 行；build/test 原始輸出只貼**最後 100 行**（含結果行）+ 完整輸出的執行指令。」——超長證據對稽核沒有增量價值，只肥 diff。
2. **引擎修剪（存量）**：新函式 `utils.prune_evidence_files(cfg, phase_id, log)`：
   - 觸發時機：Phase Gate 通過時（引擎偵測到 `current_phase` 前進後）與 `finish("complete", …)` 時。
   - 規則：對每個任務的 `.reverify/<task>-R###.md` 依 R### 排序，**保留最新 `converge_threshold` 份**，其餘刪除；`.enum/`、`.validate/` 同規則（validate 以 phase 為 key，保留最新 `final_phase_pass_gte` 份）。
   - 刪除以 `git rm` + 單獨 commit `chore: prune stale evidence files (phase N)`。
   - **修剪不可動 OPEN issue 引用的證據**：掃 state issues 索引中 OPEN 項的關聯檔，跳過。
3. Review Gate 對「修剪 commit」的相容：這是引擎產的 commit，會落在下一輪 review 的 diff 範圍。`git-review-gate.md` 紅線 8（無故刪檔）補豁免句：「commit message 為 `chore: prune stale evidence files` 且只刪 `.reverify/.enum/.validate` 底下檔案者，屬引擎例行修剪，不算無故刪檔。」

**驗收**：新測試 `test_prune_keeps_threshold_latest`、`test_prune_skips_open_issue_evidence`；手動：fixture repo 累積 10 輪證據後過 gate，舊證據被移除且 commit 訊息正確。

## T6｜context 用量遙測（讓預算漂移可觀測）

**動機**：治理要能持續，必須量得到。給 maintenance/trace 迴圈提供數據。

**變更規格**：
1. `round_finished` record 新增欄位：`prompt_bytes`（本輪組出的完整 prompt 長度）、`state_bytes`（本輪開始時 state.json 尺寸）。review gate 輪另記 `review_prompt_bytes`（掛在該輪 record 或獨立 `type: review_finished` record，實作者擇一並文件化）。
2. `collect_traces.py` 的 summary 聚合新增：各 workspace 的 `prompt_bytes` P50/P95 走勢、`state_bytes` 成長率——`maintenance/trace-driven-analysis.md` 的輸入自動變豐富，無需改該文件。
3. RUN_REPORT（計畫書 1）「時間與輪數」節補一行：平均 prompt 尺寸與 state.json 終值。

**驗收**：新測試 `test_round_record_has_context_telemetry`；collect_traces 對 fixture 輸出含新聚合欄位。

---

## 最終驗收清單

- [ ] `grep -n "journal_in_control_keep" engine/ generators/` 零筆（死設定已移除）
- [ ] `control_max_bytes` 有真實執法路徑（測試證明 80% warning、100% 壓實→停機）
- [ ] Review Gate prompt 在 200KB diff fixture 下 < 60KB（測試 + 手動 log 確認）
- [ ] 10k 行 rounds.jsonl 下引擎啟動的重建耗時 < 0.1s（尾讀生效；加簡單計時斷言或手動驗證）
- [ ] 證據檔修剪在 phase gate / complete 觸發，保留數符合門檻，OPEN issue 證據不動
- [ ] `pytest engine/` 全綠，本計畫新增測試 ≥ 12 個
- [ ] `rules/context-budget.md` 更新：把本計畫的機制逐條對應寫進「對策」欄（從「紀律」升級為「機制」），並標注哪些仍屬 prompt 自律（目前僅剩：agent 不讀 log——物理上無法禁止，維持規則層）
