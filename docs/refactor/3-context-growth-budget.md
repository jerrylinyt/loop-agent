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
| G2 | Review Gate 審查輪的 context | prompt 本身很小（`git_review` 樣板無 `{diff_content}`/`{state_json_content}` 佔位符——loop.py:132-140 傳入的這兩個 kwargs 是**死參數**，fmt_prompt 只替換樣板中存在的佔位符）；但樣板指示審查 agent **自行整檔讀 state.json 並自跑完整 diff**——增長發生在 agent 側讀取，不在 prompt | 無上限：state 越大、diff 越大，審查 agent 自己讀進 context 的量越肥；另有死 kwargs＋誤導註解（loop.py:133「實質提供完整 diff」、rules/git-review-gate.md:18「你會看到 state.json 完整內容」——都與實況不符） | ❌ 未執法（agent 側） |
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
3. 壓實屬引擎寫入，走 `guarded_state_write` 的引擎 source，事後 git commit——**commit 訊息與豁免依 T7 引擎自產 commit 規約**（否則壓實刪欄位的 diff 正中 review 紅線 2/4 的 REVERT 靶心，會形成 compact→revert→state_too_large 死循環）。
4. `run.py` 的 `reset_execute_state_data` 中 `reset_history` append 處同步加「留 5 筆」上限（源頭節流）。

**驗收**：新測試 `test_compact_moves_resolved_issues_and_reset_history`、`test_compact_preserves_decision_fields`（壓實前後 `is_done` / task 狀態判定完全一致）。

## T3｜Review Gate 審查輪的 context 治理（G2）

**現況（收官重審後校正——原版本的前提是錯的）**：
- prompt 本身**沒有**內嵌完整 diff / state.json：`engine/prompts.yaml` 的 `git_review` 樣板只有 `{diff_range}`/`{control}`/`{result_file}` 佔位符；`loop.py:132-140` 傳入的 `diff_content` / `state_json_content` 兩個 kwargs 因樣板無對應佔位符而是**死參數**（`fmt_prompt` 只替換存在的佔位符）。
- 真正的增長在 **agent 側**：樣板指示審查 agent「自行執行 `{diff_range}`」「讀取 `{control}`（整檔 state.json）」——state 與 diff 越大，審查 agent 自己讀進 context 的量越肥，且完全沒有預算指引。
- 附帶兩處**誤導性殘留**會坑到未來維護者：`loop.py:133` 註解「實質提供完整 diff 供獨立審查」、`rules/git-review-gate.md:18`「你現在不只會看到 Diff，還會看到最新的 state.json 狀態檔完整內容」——皆與實況不符。

**變更規格**：
1. **清死碼**：移除 `run_git_review_gate` 中傳入 `fmt_prompt` 的 `diff_content` / `state_json_content` 死 kwargs 與 loop.py:133 誤導註解；`rules/git-review-gate.md:18` 措辭改為與實況一致。
2. **給審查 agent 有預算的輸入（正向改善，取代放任自讀）**：
   - config 新增 `runtime.review_embed_max_bytes: 30000`。
   - prompt **實際內嵌**（樣板新增佔位符）：(a) `git diff --stat last_safe..HEAD` 全文（很小）；(b) `state.py` 新函式 `summarize_for_review(state) -> str`（≤2KB：current_phase、各 phase 任務狀態計數、計數器、OPEN issues 索引行）；(c) `git diff last_safe..HEAD -- <state.json>` 輸出（**本輪狀態變更才是審查對象**，通常很小）。三者合計受 `review_embed_max_bytes` 截斷保護（截斷處插入明確標記與自查指令）。
   - 樣板指引改為：「diff 逐項審查以你自行執行 `{diff_range}` 的輸出為準、**分段檢視、單檔過大先看 stat 挑重點**；state 審查以上方內嵌的摘要與狀態 diff 為準，僅在懷疑結構毀損時才整檔讀 state.json」——把「怎麼有預算地讀」寫成明確指令，而不是放任整檔吞。
3. `rules/git-review-gate.md` 同步更新措辭（含第 2 節「你會看到」段）。

**驗收**：
- 新測試 `test_review_prompt_no_dead_kwargs`（樣板佔位符集合與 fmt_prompt 傳入 kwargs 集合一致——防死參數重生，兼防「佔位符加了 kwargs 忘傳」的反向錯）。
- 新測試 `test_review_prompt_embeds_stat_summary_and_state_diff`（斷言三樣內嵌存在、200KB diff fixture 下 prompt 總長受 max_bytes 截斷且含標記）。
- 手動：跑一輪真實 review，確認審查 agent 依指引取 diff/state（log 可見其指令），未整檔讀 state.json（非毀損情境）。

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
3. Review Gate 對「修剪 commit」的相容：**依 T7 引擎自產 commit 規約**（prune 類）豁免，不再於規則檔寫個案豁免句。

**驗收**：新測試 `test_prune_keeps_threshold_latest`、`test_prune_skips_open_issue_evidence`；手動：fixture repo 累積 10 輪證據後過 gate，舊證據被移除且 commit 訊息正確。

## T6｜context 用量遙測（讓預算漂移可觀測）

**動機**：治理要能持續，必須量得到。給 maintenance/trace 迴圈提供數據。

**變更規格**：
1. `round_finished` record 新增欄位：`prompt_bytes`（本輪組出的完整 prompt 長度）、`state_bytes`（本輪開始時 state.json 尺寸）。review gate 輪另記 `review_prompt_bytes`（掛在該輪 record 或獨立 `type: review_finished` record，實作者擇一並文件化）。
2. `collect_traces.py` 的 summary 聚合新增：各 workspace 的 `prompt_bytes` P50/P95 走勢、`state_bytes` 成長率——`maintenance/trace-driven-analysis.md` 的輸入自動變豐富，無需改該文件。
3. RUN_REPORT（計畫書 1）「時間與輪數」節補一行：平均 prompt 尺寸與 state.json 終值。

**驗收**：新測試 `test_round_record_has_context_telemetry`；collect_traces 對 fixture 輸出含新聚合欄位。

## T7｜引擎自產 commit 規約（與 Review Gate 的互認，收官重審新增）

**動機**：本系列讓引擎自己會產 commit（T2 壓實、T5 修剪、計畫書 1 T6 的框架同步、reset 類），這些 commit 會落在下一輪 review 的 `last_safe..HEAD` diff 範圍——壓實刪 state 欄位、修剪刪證據檔，**正中現行紅線 2/4/8 的 REVERT 靶心**。散在各任務寫個案豁免會漏（計畫書 4 M4 改寫規則檔時就會遺失），需要一條統一規約。

**變更規格**：
1. **訊息前綴**：所有引擎自產 commit 訊息一律 `loop-engine(<類別>): <摘要>`，類別枚舉：`compact` / `prune` / `sync` / `reset`。
2. **路徑白名單**（每類允許觸碰的範圍）：`compact` → 僅 state.json；`prune` → 僅 `.reverify/.enum/.validate/` 刪檔；`sync` → 僅 `.loop/rules|generators/`；`reset` → state.json + phases/。
3. **Review Gate 端的互認（引擎層實作，非 LLM 判斷）**：gate 取 diff 前先列出 range 內 commits，凡「訊息帶規約前綴 **且** 該 commit 的 diff 完全落在對應路徑白名單內」者從審查範圍排除（逐 commit 驗路徑，**前綴對但路徑越界 → 不豁免、照審**——防 agent 偽造前綴夾帶）；排除後若剩餘 diff 為空 → 直接 PASS 並前移 last_safe_sha。
4. 計畫書 4 M4 落地時，此規約併入 L0 實作（見該書 M4 的引擎 commit 豁免列）；13 項版規則檔過渡期由本任務在引擎層實作同邏輯（不改規則檔文字，機制在 gate 取 diff 前）。
5. 明確排除：agent 的 commit（`R### | phase…` 格式）永不適用豁免，即使觸碰相同路徑。

**驗收**：新測試 `test_engine_commit_exempted_from_review`（compact commit 在 range 內 → 不觸發 LLM review 且 last_safe 前移）、`test_forged_prefix_with_out_of_scope_paths_not_exempted`、`test_agent_commit_never_exempted`。

---

## 最終驗收清單

- [ ] `grep -n "journal_in_control_keep" engine/ generators/` 零筆（死設定已移除）
- [ ] `control_max_bytes` 有真實執法路徑（測試證明 80% warning、100% 壓實→停機）
- [ ] Review prompt 死 kwargs 清除（佔位符/kwargs 一致性測試綠）；stat+摘要+state diff 三樣內嵌存在且受 max_bytes 截斷（200KB diff fixture）
- [ ] 引擎自產 commit（compact/prune/sync）經 T7 規約被 gate 正確豁免；偽造前綴夾帶越界路徑不豁免（測試綠）
- [ ] 10k 行 rounds.jsonl 下引擎啟動的重建耗時 < 0.1s（尾讀生效；加簡單計時斷言或手動驗證）
- [ ] 證據檔修剪在 phase gate / complete 觸發，保留數符合門檻，OPEN issue 證據不動
- [ ] `pytest engine/` 全綠，本計畫新增測試 ≥ 12 個
- [ ] `rules/context-budget.md` 更新：把本計畫的機制逐條對應寫進「對策」欄（從「紀律」升級為「機制」），並標注哪些仍屬 prompt 自律（目前僅剩：agent 不讀 log——物理上無法禁止，維持規則層）
