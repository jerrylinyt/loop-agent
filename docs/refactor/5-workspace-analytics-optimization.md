# 📊 計畫書 5 — 執行歷史分析與校準優化（Workspace Analytics & Optimization）

> **狀態**：待執行
> **依賴**：計畫書 1（duration 欄位）、2（`loop` CLI、PLAN_SUMMARY）、3（context 遙測、jsonl 輪替）、4（任務級編排、verify 契約）——**本系列最後一份**
> **產出 branch**：`refactor/5-workspace-analytics`
> **對應 review**：§5.5（成本記帳）、§8（衡量指標）；並回應使用者需求：「分析執行過的 workspace 並產出優化」

## 0. 目標與定位

跑過的每個 workspace 都是一份「這套門檻/模型/切法在真實任務上表現如何」的實驗數據。本計畫把這些數據變成三種產出：

1. **單 workspace 分析報告**（`loop analyze`）：這個專案跑得貴不貴、卡在哪、哪些防護真的攔到東西。
2. **校準建議**（`loop analyze --suggest`）：基於數據的 config 調整建議（收斂門檻、升級門檻、模型指派）——**只建議、不自動改**。
3. **跨 workspace 聚合**：餵給既有 maintenance 爬坡迴圈更豐富的訊號，並校準框架預設值。

**與既有 maintenance 迴圈的分工**（不重疊、共用地基）：

| | `collect_traces.py`（既有） | 本計畫（新增） |
|---|---|---|
| 問的問題 | 「框架哪裡有缺陷？」（痛點獵捕） | 「這個專案/這組門檻表現如何？」（成本與校準） |
| 粒度 | 跨專案、缺陷指紋 | 任務級、run 級、workspace 級 |
| 產出 | summary.json → 硬化提案 | ANALYSIS.md / CONFIG_SUGGESTIONS.md / 校準係數 |

**授權紅線（沿用框架原則 9）**：本計畫所有「優化」產出一律是**建議文件**，由人套用。程式不得自行修改任何 `loop.config.yaml` 門檻或框架預設——一個能自己調鬆門檻的分析器，等於繞過了 BREAKER 不可自我放寬的紅線。

---

## T1｜資料補強：任務級歸因與機器可讀 registry

**現況缺口**：
- `round_finished` record 沒有 `task` / `action` 欄位——**無法做任務級分析**（哪個任務燒最多輪、收斂成本多少），只能到 phase 級。
- workspace 發現靠 parse `~/.loop/index.md` 的 markdown 表格（`collect_traces.py:22-53`），脆弱且欄位有限。

**變更規格**：
1. **round record 欄位（規格主體在計畫書 4 M2.3 第 4 點，本任務為消費/驗證方）**：
   - `round_finished` 的 `task`/`action`/`verify_kind`/`model`、`review_revert` 的 `round`/`task`、`task_frozen`/`phase_advanced`/`note_injected` 事件 record——皆由計畫書 4（與計畫書 2 T7）實作；本任務驗證欄位齊全性（analytics loader 對缺欄位 record 的容錯 + 統計時標記資料版本），並確保欄位名與 M2.3 完全一致（欄位名以 M2.3 為準）。
2. **機器可讀 registry**：`~/.loop/registry.json`（`config.index` 同目錄）：
   ```jsonc
   { "version": 1, "workspaces": [{
       "repo_path": "...", "workspace": "featureA",
       "first_seen": "...", "last_run_at": "...", "last_status": "complete",
       "last_run_id": "...", "framework_ref": "abc123" }] }
   ```
   - `utils.update_index()` 改為**同時**維護 registry.json（真相）與 index.md（人看的投影，由 registry 渲染）。upsert key 同現況（repo_path + workspace）。
   - 原子寫入（temp + replace），損毀時從 index.md 降級重建。
3. `collect_traces.py` 的 workspace 發現改用 registry.json（找不到才 fallback parse index.md）。

**驗收**：`test_round_record_has_task_attribution`、`test_registry_upsert_and_render_index`、`test_collect_traces_uses_registry`。

## T2｜共用讀取層 `engine/analytics.py`

**動機**：analyze / collect_traces / report（計畫書 1 T12）各自讀 rounds.jsonl 會養出三套解析邏輯。

**變更規格**：
1. 新模組 `engine/analytics.py`，提供：
   - `iter_rounds(state_dir, since=None) -> Iterator[dict]`：讀 `rounds.jsonl*`（含輪替檔，依序）、逐行容錯 parse（沿用 collect_traces 的容錯行為）。
   - `load_runs(state_dir) -> dict[run_id, RunData]`：按 run 分組，附起訖時間、final_status（來自 `run_finished`）、rounds 列表。
   - `discover_workspaces(registry_path) -> list[WorkspaceRef]`。
2. `collect_traces.py` 與 `report.py` 改為呼叫本模組（行為不變，重構有測試保護）。

**驗收**：`test_iter_rounds_reads_rotated_files`、`test_load_runs_groups_and_status`；collect_traces 對同一 fixture 重構前後 summary.json 完全一致（golden test）。

## T3｜`loop analyze`：單 workspace 分析報告

**變更規格**：
1. CLI：`loop analyze [--workspace ws] [--since YYYY-MM-DD] [--json]`，產出 `.loop/<ws>/ANALYSIS.md`（+ `--json` 時同名 .json）。
2. **指標定義**（每項附計算來源，實作照表）：

   | 節 | 指標 | 計算 |
   |----|------|------|
   | 總覽 | runs 數 / 總輪數 / 總牆鐘時 / 完成率 | run_finished 聚合 |
   | 成本 | 各 model tier 的輪數與時長占比；每 CONVERGED 任務平均輪數 | round_finished 的 tier/duration/task |
   | 任務排行 | 最貴任務 Top10（該 task 的輪數、REVERT 次數、升級次數、最終狀態） | task 歸因（T1） |
   | 收斂效益 | 各任務 REVERIFY 輪中「發現實質差異」比率（= conv 歸零次數 / 重驗輪數） | action=REVERIFY + conv 變化（state_events 或 round 序列推導） |
   | 驗證效益 | verify.kind=command 任務的一次過率；phase 全量驗證的 FAIL 分布（第幾次 pass 後才 FAIL） | RUN_CHECK / PHASE_VALIDATE 輪 |
   | 防護效益 | Review Gate：L0 攔截數（分項）、L1 呼叫數與 REVERT 率；震盪升級事件數與「升級後 N 輪內恢復進展」比率 | review 記錄 + stuck_level 轉變序列 |
   | Context | prompt_bytes P50/P95 走勢、state_bytes 終值走勢 | 計畫書 3 T6 遙測 |
   | 估算準度 | PLAN_SUMMARY 估算輪數 vs 實際輪數（比值） | PLAN_SUMMARY 存檔值（見 T6）+ 實際 |
3. 「升級後恢復進展」定義：stuck_level 由 0→1（或 1→2）的輪之後 `osc.enhanced_max_rounds` 輪內出現 `progressed=true`。
4. 資料不足的節輸出「（樣本不足：N 輪）」，不拋錯、不給誤導性百分比（分母 < 5 一律標註）。

**驗收**：以手工構造的 fixture（一個 20 輪的假 workspace，含升級、REVERT、reverify 歸零、check 失敗各若干）跑 analyze，逐節斷言數字正確（`test_analyze_metrics_golden`）；空 workspace 不拋錯。

## T4｜跨 workspace 聚合

**變更規格**：
1. `loop analyze --all`：遍歷 registry 全部 workspace，輸出 `~/.loop/analytics/<date>/cross-summary.md` + `.json`：
   - 各 workspace 一行總覽（輪數/時長/完成率/平均任務成本/估算準度比值）。
   - **框架預設值體檢**：把 T5 的校準規則跑在「全體資料」上，產出對 `engine/config.py DEFAULTS` 的建議（例：全體 reverify 實質差異率 2% → 建議預設 converge_threshold 由 2 降 1 並說明風險）。
   - 任務型聚類（依 verify_kind × phase 名稱關鍵字粗分類），供任務型 preset（**計畫書 2 T16 第 1-b 點的 `presets/` 目錄**）校準——校準建議寫給各 preset 的建議門檻註解段，❌ 不碰 CLI profile（profiles/ 是 CLI/模型設定，與任務型無關）。
2. 與 collect_traces 的關係：`loop analyze --all --collect` 順手呼叫 collect_traces 產 snapshot/summary（同一日期目錄旁），一次指令餵飽 maintenance 迴圈。

**驗收**：兩個 fixture workspace 下 `--all` 產出 cross-summary 且逐 workspace 數字與單獨 analyze 一致；`--collect` 產生 trace-snapshots。

## T5｜校準建議引擎（`--suggest`）

**變更規格**：
1. `loop analyze --suggest`：在 ANALYSIS.md 之外產出 `.loop/<ws>/CONFIG_SUGGESTIONS.md`——**建議 = 規則表驅動的確定性輸出**（不叫 LLM），每則建議必含：訊號數據、建議的 config diff、風險說明、樣本數。
2. **校準規則表 v1**（實作為 `engine/calibration_rules.py` 的資料驅動規則清單，之後可擴充）：

   | 規則 | 觸發訊號 | 建議 | 風險註記 |
   |------|----------|------|----------|
   | R1 收斂門檻過高 | 某 phase 的 REVERIFY 實質差異率 < 5% 且重驗輪數 ≥ 20 | `converge_threshold` −1（下限 1） | 「差異率低也可能代表重驗品質差，套用前抽查 2 份證據檔」 |
   | R2 收斂門檻過低 | phase 全量驗證的 FAIL 有 ≥ 30% 歸因於已 CONVERGED 任務被打回（NEEDS_REVISION 事件） | `converge_threshold` +1 | — |
   | R3 全量驗證過長 | 最終 phase `consecutive_pass` 在達標前**最後 K 次從未 FAIL**（K = required 的後半段） | `final_phase_pass_gte` 降至（最後一次 FAIL 位置 + 3） | 「僅在有 phase 級 check（客觀驗證）時建議」 |
   | R4 升級太慢 | 升級事件中「升級前空燒輪數」P50 ≥ 8 且升級後恢復率 ≥ 60% | `stall_threshold` −2（下限 4） | — |
   | R5 升級無效 | 升級後恢復率 < 30%（樣本 ≥ 5） | 不動門檻；提示「多為規格矛盾，檢視對應 FROZEN/Issue」 | 對齊授權紅線：這不是門檻問題 |
   | R6 tier_hint 建議 | 某任務（或同型任務）曾升級到 normal 且升級後一輪內過 | 對該型任務建議 plan 期標 `tier_hint: normal` | 寫給「下次 plan」的建議，不改既有 state |
   | R7 watchdog 過鬆/過緊 | killed=timeout 率 > 10% 且 killed 輪 duration 集中於上限值 | `round_timeout_seconds` 調整方向與數值（P95×1.5） | — |
   | R8 check 逾時 | RUN_CHECK 逾時率 > 20% | `check_timeout_seconds` 上調（P95×2） | — |
3. 每則建議帶穩定 id（如 `R1@phase2`），已被人駁回的建議記錄在 `CONFIG_SUGGESTIONS.md` 末端「人類裁決」欄（沿用 maintenance/proposals 的格式與防疲勞鐵則：**駁回過且理由仍成立的不重複提**——實作：suggest 產生前 parse 既有檔的裁決欄）。
4. **跨專案版**：`--all --suggest` 對 DEFAULTS 的建議寫成 `maintenance/proposals/<date>-calibration-<rule>.md`（匯入既有人類 PR gate 管道，格式沿用 `trace-driven-analysis.md` §4.2 模板）。

**驗收**：每條規則一個 fixture 測試（觸發 + 不觸發各一）；`test_suggest_respects_rejection`（駁回過的建議不再出現）；`test_suggest_never_writes_config`（斷言執行後 loop.config.yaml 無變更）。

## T6｜輪數估算校準回饋

**變更規格**：
1. PLAN_SUMMARY（計畫書 2 T6）產生時，把估算值持久化到 state `plan.estimated_rounds`（引擎寫）。
2. run 完成時（RUN_REPORT 產生處）計算 `actual/estimated` 比值，append 到 `~/.loop/analytics/estimation-history.jsonl`（repo/ws/任務數/估算/實際/比值）。
3. PLAN_SUMMARY 的估算公式加上校正係數：`估算 × median(全體歷史比值)`（歷史 < 3 筆時係數 = 1 並註明「尚無校準數據」）。報告內同時印原始估算與校正後估算、係數來源樣本數。

**驗收**：`test_estimation_history_appended`、`test_plan_summary_applies_correction`（fixture 歷史比值 2.0 → 估算翻倍且註明）。

## T7｜自動化掛鉤與保存政策

**變更規格**：
1. run 結束（`finish()`）順手做：更新 registry（T1）、append estimation-history（T6）。**不**自動跑全量 analyze（成本考量），但 RUN_REPORT 末尾提示「跨 run 分析：`loop analyze`」。
2. `~/.loop/analytics/` 目錄保留最近 30 個日期目錄（超過刪最舊，engine 端實作於 `--all` 執行時）。
3. cron 範例文件：README 補一段「每週一早自動 `loop analyze --all --collect --suggest` 的 crontab 範例」，讓 maintenance 迴圈的輸入保持新鮮。

**驗收**：`test_finish_updates_registry`、`test_analytics_retention_30`。

## T8｜文件

1. README「其他你可能在意的」加「跑完之後：分析與校準」一節（analyze / suggest / 跨專案 / 授權紅線一句話）。
2. `maintenance/trace-driven-analysis.md` §2 輸入清單補：cross-summary 與 calibration proposals 也是輸入。
3. `docs/checklist-before-leaving.md`（計畫書 2 T9）末尾補一行：「每跑完 2~3 個 run，抽空看一次 `loop analyze --suggest`」。

---

## 最終驗收清單

- [ ] fixture workspace（20 輪、含各事件型）的 `loop analyze` 各節數字經 golden test 驗證
- [ ] `--suggest` 八條規則觸發/不觸發測試全過；執行後任何 config 檔零變更（授權紅線測試）
- [ ] `--all` 跨 workspace 聚合與單獨 analyze 數字一致；`--collect` 與既有 collect_traces 輸出相容（golden 比對）
- [ ] collect_traces / report 重構為共用 `analytics.py` 後，既有輸出 byte-level 一致（或差異僅欄位新增，逐項列明）
- [ ] 估算校正係數在 3 筆歷史後生效並反映在 PLAN_SUMMARY
- [ ] `pytest engine/` 全綠，本計畫新增測試 ≥ 20 個
- [ ] 端到端演練：跑兩個小型真實 run → `loop analyze --all --suggest` → 產出的建議至少一條可人工驗證合理（記入 PR 描述）
