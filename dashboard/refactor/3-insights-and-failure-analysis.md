# 🔬 Dashboard 計畫書 3 — 洞察層：失敗率監控、原因聚類、前後輪對比

> **狀態**：待執行
> **依賴**：dashboard 計畫書 1（rounds API、單輪詳情）；docs/refactor 計畫書 3 T6（context 遙測）、5 T1/T2（task 歸因、analytics loader）
> **產出 branch**：`dashboard/3-insights`
> **核心使用情境**：「round 失敗率升高了——**大部分在失敗什麼？從哪一輪開始的？是同一個原因嗎？**」人要在一分鐘內從趨勢圖走到根因假設。

## T1｜失敗率監控與趨勢圖

**規格**：
1. workspace 詳情頁頂部新增**健康條**：最近 `window`（預設 30，可調）輪的滾動失敗率（FAIL+killed / 總輪），配色綠(<20%)/琥珀(<50%)/紅(≥50%)。紅時全站總覽卡片同步標紅（fleet 層看得到誰在惡化）。
2. **趨勢圖**（Rounds 籤頂部，取代/強化計畫書 1 的迷你圖）：X=輪次、Y=滾動失敗率折線 + 每輪 result 色點；**事件標記層**：⬆ 模型升級（stuck_level 變化）、↩ REVERT、🧊 任務 FROZEN、🔁 phase 前進、📌 human note 注入——失敗率轉折點旁邊通常就站著一個事件，並排是最快的歸因線索。
3. 圖上框選區間 → 下方 rounds 表過濾到該區間（brush-to-filter）。
4. 資料端點：`GET /api/ws/{id}/health?window=`，回滾動序列 + 事件列表（一次算好，前端不重算）。

**驗收**：fixture（前 20 輪綠、後 15 輪紅、中間一次升級）：健康條轉紅、趨勢圖轉折點與升級標記對位、框選過濾正確。

## T2｜失敗原因聚類（Top-N 面板）★ 本計畫書的主菜

**規格**：
1. **三個聚類維度**（同一份失敗輪資料、三種分組，UI 用籤切換）：
   - **按錯誤簽名**（最有用）：對每個 FAIL 輪取「驗證輸出尾段」（RUN_CHECK 的 check log 尾 / evidence 檔的 build/test 輸出段 / review REVERT reason），做**確定性正規化**後取簽名。
   - **按任務**：哪個任務貢獻最多失敗輪。
   - **按失敗指紋**：既有 fail_fingerprint 分組（「同一組任務+同一批檔案」的反覆失敗 = 震盪嫌疑）。
2. **錯誤簽名正規化演算法**（確定性、可測，實作於 `engine/analytics.py` 供 CLI 與 dashboard 共用）：
   ```
   a. 取輸出尾 30 行 → 過濾出「錯誤行」：match 常見 pattern（Error|Exception|FAILED|AssertionError|
      error TS\d+|✕|✗ …，pattern 表可設定）取第一條；沒有 match 就取最後一個非空行。
   b. 正規化：去除時間戳/絕對路徑前綴/十六進位位址/行號數字（`:123` → `:N`）/UUID。
   c. 簽名 = 正規化字串（截 160 字元）；顯示名 = 原始字串。
   ```
3. **面板呈現**：`失敗分析` 區（健康條轉琥珀/紅時自動展開）：Top-5 清單，每項——正規化錯誤行、次數與占比、首次/最近出現輪次、涉及任務 chips、迷你 trend（該簽名在時間軸上的分布點）、`查看代表輪` 按鈕（跳該簽名最近一輪的詳情）。
4. **一鍵歸因輔助**：每個聚類項附機械判定 hint：同簽名 + 同任務 + 連續 ≥3 輪 → 顯示「疑似卡死（引擎將於 stall_threshold 升級）」；同指紋交替出現 → 「疑似 A↔B 震盪」；簽名含 `timeout` → 「檢查 check_timeout / 環境」。hint 是規則表（可擴充），不是 LLM。
5. 端點：`GET /api/ws/{id}/failures?window=&group_by=signature|task|fingerprint`。

**驗收**：fixture（三種簽名的 check log：pytest 斷言錯、TS 編譯錯、timeout）：聚類數=3、占比正確、正規化把不同行號/路徑的同型錯誤合併為一組（`test_signature_normalization_merges_variants`）；代表輪跳轉正確；卡死 hint 在連續同簽名 fixture 上出現。

## T3｜前後輪對比視圖（Round Compare）

**規格**：
1. 入口：單輪詳情的「同任務上一輪」升級為**並排對比模式**（`/compare?left=R83&right=R87`，預設同任務相鄰兩輪，可手選任意兩輪）。
2. 並排欄位（左右各一欄 + 中間差異高亮）：
   - result / tier / duration / stuck_level（數值變化上色）
   - **commit diff 的 diff**：兩輪 changed_files 集合的交集/差集（「這輪多動了哪些檔、少動了哪些」）；同檔皆有改動時提供該檔兩輪 diff 的並排（後端 `git show` 兩次）
   - 驗證輸出尾段並排（錯誤簽名相同 → 頂部標「同一個錯」；不同 → 標「錯誤已變化：A → B」——**這行字就是「變化原因」的第一線索**：同錯=沒修到，換錯=修掉一個撞出下一個）
   - agent 報告摘要並排、state 變化列表並排
3. 對比頁頂部一句機械結論（規則生成）：`「相同任務連續失敗，錯誤簽名相同（沒修到點上）」`／`「錯誤已從 X 變為 Y（有進展或引入新問題）」`／`「本輪通過——與上輪差異見左列」`。
4. REVERT 輪的對比自動把 review verdict 的 FLAG evidence 置頂（「為什麼被退」永遠第一眼）。

**驗收**：fixture 三情境（同錯連敗/換錯/修復通過）機械結論正確；REVERT 輪 evidence 置頂；任意兩輪手選對比可用。

## T4｜成本與 ETA 面板

**規格**：
1. workspace 詳情新增 `Insights` 籤：
   - **成本分解**：本 run 各 tier 輪數×時長堆疊圖；任務成本 Top-10 橫條（該任務累計輪數，色分 action 類型）——「錢燒在哪」一眼可見。
   - **收斂效益**：各 phase 的重驗實質差異率（來自 analytics，樣本不足標註）——人肉版的「門檻值不值」判讀，配一行說明連到 `loop analyze --suggest`。
   - **context 遙測**：prompt_bytes / state_bytes 走勢（docs/refactor 3 T6 的數據）——增長異常提早看到。
   - **ETA 卡**：同 `loop status` 公式 + 已耗牆鐘，並顯示「照目前均速，預計 HH:MM 完成」。
2. 全部數據來自 `engine/analytics.py` 聚合（dashboard 不自算），端點 `GET /api/ws/{id}/insights`。

**驗收**：fixture 下四個區塊數字與 `loop analyze` 輸出一致（golden 對照）。

## T5｜異常主動浮出（不用人來翻）

**規格**：
1. 總覽卡片新增**異常徽章**（依 T1/T2 的機械 hint）：`失敗率↑`、`疑似震盪`、`疑似卡死`、`context 增長異常`——徽章點擊直達對應分析面板。
2. 瀏覽器通知（可選開關）：頁面開著時，任一 workspace 進入紅色健康態或 human_required → Web Notification 一次。
3. 與引擎通知的分工註記：引擎 notify_cmd 管「停機了」；dashboard 徽章管「還在跑但不對勁」——後者是引擎（授權紅線內）不會替人判斷的灰色地帶，**只提示、不動作**。

**驗收**：E2E：fixture 惡化 workspace 在總覽出現徽章且直達面板；通知在健康態轉紅時觸發一次（mock Notification API）。

---

## 最終驗收清單

- [ ] 「一分鐘根因路徑」端到端演練：fixture 失敗率升高 → 總覽徽章 → 健康條 → Top-N 聚類（正確合併同型錯誤）→ 代表輪 → 前後對比出現「同錯連敗」結論——全程 ≤ 6 次點擊
- [ ] 錯誤簽名正規化單元測試（行號/路徑/時間戳變體合併；不同錯不誤併）
- [ ] 三種機械 hint（卡死/震盪/timeout）與三種對比結論的規則測試全綠
- [ ] Insights 數據與 `loop analyze` golden 一致；聚合皆走 `engine/analytics.py`（dashboard 無自製解析）
