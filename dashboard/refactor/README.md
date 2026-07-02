# 📺 Dashboard Refactor 計畫書系列 — 總綱

> **目標**：讓團隊成員**自己追蹤自己專案的完整狀態**——plan 長什麼樣、任務跑到哪、失敗率為什麼升高、下一步該我做什麼——第一時間看得到、點得進去、分析得出來。
> **撰寫前提**：本規劃**不基於現有 dashboard 程式碼**，只基於資料檔的既有/規劃中格式（state.json、rounds.jsonl、phases/*.md、registry.json、RUN_REPORT…）。執行時 agent 可自行比對現有 `dashboard/` 程式碼決定沿用或重寫——**以本規劃的行為規格為準**。
> **依賴**：`docs/refactor/` 計畫書 1–5（各階段的具體依賴見各檔開頭）。

## 三條鐵則（所有階段共同遵守）

1. **檔案是唯一真相**：dashboard 是 `.loop/` 檔案的**讀取投影 + 指令觸發器**，自己不持有任何真相（不建自己的 DB 存狀態；快取可以有，但重啟即拋棄、隨時可從檔案重建）。這是「文件即狀態、可冷接手」原則在 UI 層的延伸。
2. **單一寫入路徑 = CLI**：dashboard 的所有寫入動作（resume、approve、config 變更…）一律透過 `loop` CLI / `state.py`（source=`dashboard_*`）執行，**嚴禁直接改 state.json**——引擎的守衛與稽核（state_events）因此天然覆蓋 UI 操作。
3. **讀取遵守增長紀律**：rounds.jsonl 尾讀/分頁（沿用 `engine/analytics.py` 的 loader，不自己重寫解析）、log 用串流不整檔載入、任何聚合結果照 workspace+檔案 mtime 快取。

## 關鍵設計裁決（回答規劃時的核心疑問）

### Q：plan 內容是 markdown，程式化處理很難，要改格式嗎？
**裁決：不改格式，改「契約」——結構歸 state.json，散文歸 markdown，兩者用錨點縫合。**

- **結構化資料本來就不在 markdown 裡**：phases/tasks 的 id、status、conv、depends_on、verify、order 全部活在 `state.json`（v3 schema 後更完整）。dashboard 的表格、進度、圖全部讀 state.json，**一行 markdown 都不用 parse**。
- markdown（`phases/*.md`）只承載**每個任務的規格散文**，且 docs/refactor 計畫書 4 M2.2 已把它標準化成錨點格式（每任務一個 `## TASK-xx` 小節、`spec_ref: 檔案#錨點`）——擷取一個任務的說明 = 「找標題、切到下一個標題」，機械且已有引擎 API（任務卡就是這樣組的，dashboard 直接複用同一個擷取函式）。
- **為什麼不把規格散文也搬進 JSON/YAML**：規格是給人 review（gate#2）與給 agent 讀的長文，markdown 的可讀性、git diff 可審性、agent 產出品質都優於塞進 JSON 字串；plan review 的人類體驗會嚴重倒退。
- dashboard 需要的「plan 全貌」= `state.json`（結構）+ `PLAN_SUMMARY.md`（人話摘要，計畫書 2 T6）+ 錨點擷取（單任務散文）。三者都已存在或已規劃，**零新格式**。

### Q：畫面上改 config 安全嗎？
可以，但有三道欄：表單只開放**已知旋鈕**（schema 驅動）+ 存檔前跑 `preflight --dry` 驗證 + 寫入走 git commit（可稽核可還原）。run 進行中的變更明確標示「下個 run 生效」（引擎每次啟動才讀 config）。詳見計畫書 2。

### Q：失敗率升高怎麼「第一時間看到原因」？
三層鑽取：**趨勢圖（帶事件標記）→ 失敗原因聚類 Top-N（錯誤簽名/任務/指紋三個維度）→ 單輪詳情（prompt/diff/驗證輸出/state 變化 + 同任務前後輪對比）**。詳見計畫書 3。

## 階段索引

| 階段 | 檔案 | 一句話 | 主要依賴 |
|------|------|--------|----------|
| 1 | `1-data-api-and-readonly-views.md` | 資料層 + 唯讀視圖：總覽、plan 瀏覽、任務、輪次時間軸、單輪詳情、即時 log | docs/refactor 1、2（PLAN_SUMMARY）、5 T1/T2（registry、analytics loader、task 歸因） |
| 2 | `2-operations-and-config.md` | 操作層：生命週期按鈕、人類 gate、config 編輯、issue 操作 | docs/refactor 2（loop CLI 全套） |
| 3 | `3-insights-and-failure-analysis.md` | 洞察層：失敗率監控、原因聚類、前後輪對比、成本/ETA 面板 | docs/refactor 3 T6（遙測）、5（analytics） |
| 4 | `4-team-mode-and-outlook.md` | 團隊化（owner/分享/權限）+ 展望清單 | 前三階段 |

> 階段 1 完成即可日常使用（看得到一切）；2 補齊「不用開終端機」；3 是分析力；4 是規模化。各階段獨立驗收。

## 路由總表（跨 engine/dashboard 的資料流稽核點）

`docs/refactor/ROUTING.md` 集中定義「每種 agent 拿到什麼、每個產出物誰生產誰消費、進不進 context」，並含跨計畫增補帳（本系列對 docs/refactor 的增補——任務卡落檔、registry owner 欄位——都記在該帳上）。**執行本系列任一計畫書前先讀它；收 PR 前過它的 §D 自查。**
（該檔是 refactor 執行期工作版；全系列完工後其 §A/§B 會依實作狀態畢業為常駐的 `docs/architecture/routing.md`，屆時以新位置為準——見 docs/refactor 計畫書 4 收尾。）
