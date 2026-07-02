# 👥 Dashboard 計畫書 4 — 團隊模式 + 展望

> **狀態**：待執行（前半）；後半為展望盤點，動工前需先展開成正式計畫書
> **依賴**：dashboard 計畫書 1–3
> **產出 branch**：`dashboard/4-team`

## A 部：團隊模式（本階段實作）

### T1｜Owner 與「我的專案」

**規格**：
1. registry.json 的 workspace 項新增 `owner`（`loop init` 時取 `git config user.email` 寫入；`loop track` 可 `--owner` 覆寫）——此為 docs/refactor 計畫書 5 T1 registry schema 的增補欄位（同 PR 提出）。
2. 總覽預設籤 `我的`（owner == 目前使用者，來源：dashboard 啟動者的 git user.email，token 模式下取 token 綁定身分）＋ `全部` 籤。
3. 卡片顯示 owner 頭像字母 chip；篩選器支援 owner。

**驗收**：兩 owner fixture 下「我的/全部」切換正確；init 後 registry 含 owner。

### T2｜唯讀分享模式

**動機**：讓主管/隔壁團隊看進度，不給操作權。

**規格**：
1. 啟動旗標 `loop dashboard --read-only`：整站隱藏所有動作按鈕、POST 端點全部 403；
2. `loop dashboard export --ws <id>`：產出**靜態快照**（單一 self-contained HTML：總覽 + plan + rounds 摘要 + insights 圖表內嵌資料）——貼進週報/寄給任何人，零部署。
3. token 模式（計畫書 2 T6）+ read-only 可組合：一個寫 token、一個唯讀 token。

**驗收**：read-only 模式 POST 全 403 且 UI 無動作按鈕；export 的 HTML 離線開啟可互動（fixture 驗證）。

### T3｜多人操作防護

**規格**：
1. 動作執行器（計畫書 2 T1）的 audit 記錄補 `actor`（token 身分或 local user）。
2. 「別人正在操作」可見性：workspace 有進行中 action 時，其他 client 的動作按鈕轉為 disabled + 顯示「<actor> 正在 <action>」（輪詢 job 狀態即可，不需 websocket 級即時）。
3. 人類 gate 的蓋章記錄（approve/accept）顯示 actor——誰核可的，永遠可查。

**驗收**：雙 client E2E：A 啟動 execute 期間 B 的按鈕 disabled 且顯示占用者。

---

## B 部：展望（Outlook——按價值排序的下一步候選，動工前各自展開計畫書）

| # | 方向 | 概念與價值 | 前置 |
|---|------|-----------|------|
| O1 | **LLM 單輪解讀員** | 單輪詳情/對比頁加「解讀本輪」按鈕：把該輪的組裝資料（diff stat、驗證輸出尾、state 變化、前輪對比）餵給 fast 模型，產出三句人話歸因。**按需觸發、絕不自動跑**（成本紅線），結果快取進 `.loop_state/`。機械 hint（計畫書 3）先擋 80% 場景，這是剩下 20% 的補槍 | dashboard 3 |
| O2 | **問題收件匣（QUESTION queue UI）** | roadmap H1.2 落地後：總覽新增「待回答」計數，收件匣視圖批次作答（選項按鈕 + 附註）→ 解凍任務。早上的裁決儀式從「翻 report」變「清 inbox」 | roadmap H1.2 |
| O3 | **佇列與排程視圖** | roadmap H2.1 落地後：queue 看板（待跑/進行/完成泳道、拖拉調優先序）、時窗甘特（今晚 22:00–07:00 誰跑哪台） | roadmap H2.1 |
| O4 | **團隊成本儀表** | roadmap H2.4 落地後：跨 workspace 成本聚合、月報、配額水位條、per-任務成本排行的團隊版 | roadmap H2.4 |
| O5 | **Plan 視覺化編輯** | 依賴圖從唯讀升級為可編輯（拖拉 depends_on、改 threshold）→ 產出 **plan diff 提案**走 reset-plan/replan 核可管道——**不直接改 state**（結構變動的授權紅線不因為是 GUI 就鬆） | dashboard 1、roadmap H1.5 |
| O6 | **基準測試看板** | roadmap H3.4 落地後：框架版本 × benchmark 指標矩陣、PR 對比視圖——「這次框架改動讓方法論變好了嗎」的可視化 | roadmap H3.4 |
| O7 | **時間軸重播（replay）** | 用 rounds + state_events 重建任意時點的 state 快照，拖拉時間軸看 phase/任務狀態演變動畫——事後覆盤與新人教學利器；資料都在，純前端工程 | dashboard 1 |
| O8 | **行動端裁決** | roadmap H2.3 的 IM bot 與 dashboard 共用動作執行器與 audit——同一套白名單、兩個入口 | dashboard 2、roadmap H2.3 |
| O9 | **多機 fleet** | 跨機器聚合（每台跑 agent 上報或共享檔案系統）：中央 registry 服務、機器健康（心跳/磁碟/負載）。屬 roadmap H2.1 的 UI 面 | roadmap H2.1 |
| O10 | **嵌入式教學** | 首次開啟引導 tour（空狀態頁直接引導跑 examples/mini-migration）；每個面板的 `?` 連到對應 rules/docs 錨點——把文件塞進使用情境裡 | dashboard 1、docs/refactor 2 T16 |
| O11 | **內嵌需求訪談** | New Workspace 精靈的 (b) 路徑升級：dashboard 以 pty 驅動一個 agent CLI 子行程跑 `0-requirements-interview.md`，聊天式面板互動、產出直接落 REQUIREMENTS.md——「從零到確認需求」完全不離開瀏覽器。複雜度高（互動式子行程管理、逐 CLI 相容），先用複製指引頂著，等精靈 (a)/(b) 的使用比例數據說話 | dashboard 2 T6-b |

**展望的取捨原則**：O1/O7/O10 純 dashboard 內即可動工（無引擎依賴，隨時可做）；O2–O4、O6、O8、O9 跟著 roadmap 對應項走（引擎先行、UI 跟上）；O5 動到結構變更授權，最後做。

---

## 最終驗收清單（A 部）

- [ ] owner 欄位進 registry（與 docs/refactor 5 T1 同步提案）；「我的/全部」切換 E2E 綠
- [ ] read-only 模式與靜態 export 可用；export HTML 離線開啟正常
- [ ] 雙 client 占用可見性 E2E 綠；audit 含 actor；gate 蓋章顯示操作者
