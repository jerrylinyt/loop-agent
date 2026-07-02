# 📊 Dashboard 計畫書 1 — 資料層 + 唯讀視圖

> **狀態**：待執行
> **依賴**：docs/refactor 計畫書 1（rounds 欄位）、2 T6（PLAN_SUMMARY）、5 T1/T2（registry.json、`engine/analytics.py`、round record 的 task/action 歸因）。缺 5 時可先落地、對應欄位顯示「—」，5 落地後自動變豐富。
> **產出 branch**：`dashboard/1-readonly`

## 0. 目標與技術基調

看得到一切、動不了任何東西（操作在計畫書 2）。技術建議（非硬性，執行 agent 可依現況調整，但行為規格不變）：

- **後端**：Python（FastAPI 或等效）——關鍵理由是**直接 import 引擎模組**（`analytics.py` 的 loader、`config.py` 的 load_config、任務卡的錨點擷取函式），零重複解析邏輯。
- **前端**：SPA（React + Vite + TS 或等效），SSE 做即時串流（不用 websocket，單向足矣）。
- **零資料庫**：所有 GET 現算 + per-(workspace, 檔案 mtime) 記憶體快取；服務重啟無任何損失。
- 綁定 `127.0.0.1` 預設（權限模型在計畫書 4 前 = 本機使用者）。

## T1｜後端骨架與資料存取層

**規格**：
1. 啟動：`loop dashboard`（掛進 docs/refactor 計畫書 2 的 CLI；等效 `python dashboard/main.py`）。參數：`--port`（預設 8000）、`--registry`（預設 `~/.loop/registry.json`）。
2. 資料存取一律經 `dashboard/datasource.py` 單一模組，內部呼叫 `engine/analytics.py`（iter_rounds/load_runs/discover_workspaces）與 `engine/state.py` 讀取函式；**本模組是 dashboard 唯一碰檔案的地方**（利於測試與快取）。
3. 快取：key = (workspace, 檔案路徑, mtime)；任何檔 mtime 變了就重讀。rounds.jsonl 讀取沿用尾讀/分頁，聚合類請求限定最近 N 輪（參數化，預設 500）。
4. workspace 定位：registry.json 為主；`+ Track` 手動登錄路徑的功能保留（寫回 registry，走 CLI）。

**驗收**：`test_datasource_cache_invalidates_on_mtime`、`test_datasource_never_writes`（跑完整測試套件後所有 `.loop/` fixture byte-level 不變）。

## T2｜REST 讀取 API

**規格**（回應皆 JSON；錯誤統一 `{error, detail}`；workspace id = `repo_path::ws_name` urlsafe 編碼）：

| Endpoint | 內容 |
|----------|------|
| `GET /api/workspaces` | registry 全列表，每項附摘要：status（running/complete/awaiting_acceptance/human_required(code)/plan_*/idle，判定順序：run.lock 活性 → state 旗標）、current_phase、任務計數（CONVERGED/總數）、blocking_issues、last_run_at、owner（計畫書 4 前可空） |
| `GET /api/ws/{id}/state` | state.json 全文（原樣） + 衍生欄位（blocking 計數、is_done 判定、ETA 粗估——公式同 `loop status`，共用函式） |
| `GET /api/ws/{id}/plan` | phases[]（id/name/threshold/gate 計數）+ tasks[]（id/title/status/conv/threshold/depends_on/verify.kind/order/tier_hint）+ requirements_map + plan 物件（status/approved/version）+ `PLAN_SUMMARY.md` 原文 |
| `GET /api/ws/{id}/task/{task_id}` | 單任務全景：state 欄位 + **spec 散文**（錨點擷取，同任務卡函式）+ reads/output + evidence 檔案清單（路徑+mtime）+ revert_history + 關聯 issues + 該任務的 rounds 摘要列表 |
| `GET /api/ws/{id}/rounds?limit&offset&task&result&loop_type` | round_finished 分頁列表（新到舊），欄位齊全（round/task/action/result/tier/duration/killed/stuck_level/progressed/fail_fingerprint） |
| `GET /api/ws/{id}/rounds/{n}` | 單輪詳情（見 T5 資料組裝規格） |
| `GET /api/ws/{id}/file?path=` | 白名單檔案原文：允許 `.loop/<ws>/` 底下的 .md/.yaml/.json 與 evidence 檔，**加上 repo 級 `.loop/` 直下的 .md**（REPO_MAP.md、未來 lessons.md——不含 rules/generators 同步副本以外的任意路徑）；**拒絕任何 `..` 與白名單外路徑**（路徑正規化後前綴檢查） |
| `GET /api/ws/{id}/reports` | RUN_REPORT.md / PLAN_SUMMARY.md / ANALYSIS.md 的存在性與內容 |
| `GET /api/ws/{id}/log/stream?file=loop|plan` | SSE：先推最後 200 行，之後 tail -f 式增量 |

**驗收**：每個 endpoint 一個 fixture 測試；`test_file_api_rejects_traversal`（`../`、絕對路徑、symlink 逃逸皆 403）；SSE 在 log append 時 2s 內推送增量。

## T3｜總覽頁（Fleet View）

**規格**：
1. 卡片牆（或表格切換），每 workspace 一卡：專案名/ws 名、狀態徽章（色彩語意：綠=running、藍=complete、琥珀=awaiting_acceptance、紅=human_required、灰=idle）、phase 進度、任務進度條（CONVERGED/總數）、最近失敗率 sparkline（最近 50 輪，資料來自 rounds API）、最後更新時間、ETA。
2. **排序 = 需要注意的優先**：human_required > awaiting_acceptance > running(異常訊號) > running > 其他；次序內按最後更新倒序。
3. 篩選：狀態、repo、（計畫書 4 後）owner=me。
4. 輪詢：總覽 10s 一次（輕量 API）；頁面不可見時暫停（`visibilitychange`）。
5. 點卡片 → workspace 詳情頁。

**驗收**：Playwright E2E：fixture 三個 workspace（running/human_required/complete）→ 排序正確、徽章正確、點擊導航正確。

## T4｜Workspace 詳情：Plan 瀏覽與任務鑽取

**規格**：
1. **頁面骨架**：頂部狀態列（狀態徽章、run branch、當前 round/任務、ETA、牆鐘耗時）+ 分頁籤：`Plan｜Rounds｜Issues｜Reports｜Log｜Config(計畫書 2)`。
2. **Plan 籤**：
   - phase 手風琴：每 phase 顯示 gate 進度（`consecutive_pass/required`）與任務表——欄：order、id、title、狀態 chip（TODO/DRAFTED/CONVERGED/NEEDS_REVISION/FROZEN 各有色）、conv（`1/2` 進度點）、verify.kind 圖示（⚙command/🔁reverify/📋enumerate/✋manual）、depends_on（chip，點擊跳轉）。
   - **「還剩多少」一眼可見**：phase 標題右側 `12/41 CONVERGED · 2 FROZEN`；FROZEN>0 時整條 phase 標紅框（它擋著一切）。
   - **依賴圖檢視**（切換按鈕）：tasks 的 DAG 渲染（現成布局庫即可），節點色 = 狀態；點節點開任務抽屜。plan review（gate#2）時人用這張圖看「切得合不合理」。
   - **需求覆蓋矩陣**：R### × 任務的對照表（來自 requirements_map），每條 R 的聚合狀態（全 CONVERGED=✅），沒有 map 時顯示引導文案。
   - PLAN_SUMMARY.md 渲染於 Plan 籤頂部（可折疊）。
3. **任務抽屜**（點任務列/DAG 節點）：spec 散文（md 渲染）、reads/output 清單（點擊經 file API 看內容）、evidence 檔案時間軸（點開看）、revert_history、關聯 issues、該任務歷史輪次迷你列表（點入 T5 詳情）。

**驗收**：E2E：點任務 → 抽屜含 spec 散文（斷言 fixture 內文出現）；FROZEN phase 紅框；依賴圖節點數 = 任務數；需求矩陣聚合正確。

## T5｜Rounds 時間軸與單輪詳情

**規格**：
1. **Rounds 籤**：反序表格（虛擬滾動）＋頂部迷你圖（每輪一格，色=result：綠 PASS/紅 FAIL/灰 NA/黑 killed；標記：⬆升級、↩REVERT、🚧human_required——資料來自 record type 與 stuck_level 變化）。篩選器同 API。點列 → 單輪詳情頁。
2. **單輪詳情（`/rounds/{n}`）——資料組裝規格**（全部來自既有檔案，逐項標來源）：
   - 基本：round/task/action/result/tier/model/duration/killed（`round_finished`）。
   - **本輪 prompt**（任務卡全文）：來源 = loop.log 中該輪的 `[Execute Prompt]` 區塊（依 round 標頭切分擷取）；v3 後建議引擎把任務卡另存 `.loop_state/cards/R{n}.md`（**向 docs/refactor 計畫書 4 M2.2 增補一行此需求**），存在時優先讀檔。
   - **agent 報告**：state_events 中該輪的 report 事件（v3）；無則顯示 last_round_* 快照。
   - **commit diff**：`round_artifact.git_head_before/after` → 後端跑 `git show --stat` + 逐檔 diff（單檔 >2000 行截斷 + 「在本機看」指令提示）。
   - **驗證輸出**：RUN_CHECK 輪附 check log 尾 100 行（`.loop_state/checks/`）；驗證/重驗輪附 evidence 檔連結。
   - **state 變化**：state_events 該輪範圍的變更事件列表（誰、哪個鍵、舊→新）——「這一輪改了哪些狀態、為什麼合法」一目了然。
   - **審查結果**：該輪相關的 review verdict / REVERT record（含 reason 與 checklist FLAG 項）。
   - **震盪上下文**：本輪 fail_fingerprint 在歷史出現的輪次清單（「這個失敗長什麼樣、之前出現過幾次」）；stuck_level 若在本輪變化，顯示觸發原因字串。
   - **前後導航**：`← 上一輪｜同任務上一輪｜下一輪 →`。「同任務上一輪」是分析利器：兩輪並排（diff stat、result、驗證輸出尾）看「改了什麼、為什麼這次過/還是不過」——**這就是「點開看到前後 round 變化原因」的落地**（完整對比視圖在計畫書 3 T3 強化）。
3. 效能：單輪詳情各區塊獨立 lazy load（diff 大時不擋整頁）。

**驗收**：fixture（含一次 REVERT、一次升級、一次 check FAIL）下：詳情頁八個區塊各自渲染正確；同任務導航正確；2000+ 行 diff 被截斷且有提示；`test_prompt_extraction_from_log`。

## T6｜即時 Log 與運行心跳

**規格**：Log 籤 = SSE tail（T2）+ 自動捲動開關 + 依 round 標頭高亮分段；頂部顯示 run.lock 心跳資訊（pid、最後心跳時間；> 2×interval 未更新顯示「可能已停止」警示——與 dead man's switch 互補的 UI 版）。

**驗收**：E2E：append log 後 2s 內畫面出現新行；心跳過期警示以 mock mtime 驗證。

---

## 最終驗收清單

- [ ] 三 workspace fixture 下：總覽排序/徽章/導航、Plan 瀏覽（含 DAG、需求矩陣、任務抽屜 spec 散文）、Rounds 時間軸與單輪詳情八區塊、SSE log——全部 E2E 綠
- [ ] 全程唯讀證明：跑完整測試後所有 fixture `.loop/` 檔案 byte-level 不變
- [ ] file API 路徑逃逸測試綠
- [ ] 聚合 API 在 10k 輪 fixture 下 < 500ms（尾讀 + 快取生效）
- [ ] 向 docs/refactor 計畫書 4 M2.2 增補「任務卡另存 `.loop_state/cards/R{n}.md`」一行（本計畫的跨檔修改，需同 PR 提出）
