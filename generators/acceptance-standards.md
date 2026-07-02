# ✅ STANDARD — 各類任務的驗收標準建議（Acceptance Standards by Task Type）

> **這份文件給誰用**：
> 1. **階段① 需求訪談**（`0-requirements-interview.md`）：幫使用者把 DoD 從「做完就好」寫成**可驗收的形式**——照抄對應任務型的模板句改就行。
> 2. **階段② 規劃**（`1-plan-generator.md` / `2-plan-review-gate.md`）：規劃 agent 給每個任務指定驗證方式時，**不得低於本檔對應任務型的最低標準**；plan gate 據此抽查。
> 3. **人類**：隔天驗收時，知道「怎樣算過」的客觀依據在哪。
>
> **一條金律**：寫不出驗收方法的需求 = 還沒定義完的需求。訪談時卡在「怎麼驗」，就是需求本身要再問。

---

## 0. 通用原則：驗收的三層梯度

任何任務的驗收方式，按可信度排序永遠是：

| 梯度 | 形式 | 特性 | 對應 verify.kind |
|------|------|------|------------------|
| **L1 機械可執行** | 一條指令，exit code 定生死（test / build / lint / diff 腳本） | 不可偽造、免費重跑、引擎可自動執行 | `command` |
| **L2 證據可稽核** | 產出留下可抽查的證據檔（含 檔:行 來源、原始輸出） | 可事後稽核，但產生過程仍靠 LLM 自律 | `reverify` / `enumerate` |
| **L3 人工判定** | 人看過、簽名 | 最貴、不可自動化 | `MANUAL`（明確標記） |

**規劃鐵則**：
- 每個任務**先問能不能上 L1**——寫得出 check 指令的，一律 L1（收斂成本從 N 輪 LLM 重驗降到 1 次免費執行）。
- 上不了 L1 的（主觀分析、文件），走 L2 + 本檔對應章節的證據規格。
- 連 L2 都寫不出的（「介面要好看」「用起來順」），**誠實標 `MANUAL`** 進人審清單——不要假裝自動化，也不要讓它擋停止條件（列 NON_BLOCKING + 人驗收點）。
- **「能編譯/能跑」永遠不等於「對」**——L1 的 check 必須斷言**行為與資料**，不是斷言「沒炸」。

---

## 1. 後端 API（新增 / 修改 / 移植）

**最低標準：每一隻 endpoint 一組 integration test——真實打一個 request，拿回**完整**資料並逐欄斷言。**

### DoD 模板句（訪談時照改）
```
R0xx：<方法> <路徑> 完成後——
  a. Integration test 以真實 HTTP request 打 <路徑>（含必要的認證前置），
     斷言：HTTP status、response schema（逐欄位型別）、關鍵欄位值與種子資料一致。
  b. 錯誤路徑至少涵蓋：未認證(401)、無資源(404)、參數不合法(422/400) 各一條。
  c. 資料完整性：list 類回應斷言筆數與分頁；detail 類斷言關聯資料（join 出來的欄位）非空且正確。
  驗收指令：<例：pytest tests/integration/test_orders.py -q>
```

### 任務切分與驗證對應
| 任務 | verify | check 範例 |
|------|--------|-----------|
| 一隻 API 的實作/移植 | `command` | `pytest tests/integration/test_orders_get.py`、`npm test -- orders.int.spec.ts` |
| 共用契約先行任務（schema/router/auth middleware） | `command` | schema 驗證腳本 + 一條冒煙 request |
| DB migration | `command` | migration up→down→up 腳本 + 種子資料查詢斷言 |
| phase 收尾全量驗證 | phase 級 `gate.check` | 整包 integration suite + `openapi` schema diff（若有 spec） |

### 環境要求（plan 期就要定，不要留到執行期猜）
- Integration test 的資料庫用**可重建的實例**（docker compose / testcontainers / sqlite 替身——訪談時問清楚用哪個），並有**種子資料 fixture**（測試斷言的「正確值」來源）。
- 測試必須**冪等**：重跑不需人工清庫。做不到冪等的 check 會讓收斂計數失真。

### 常見假驗收（plan gate 抽查時打回）
- ❌ 只斷言 `status == 200` 不看 body → 不算「拿到完整的資料」。
- ❌ mock 掉 DB/下游後自己測自己 → 那是 unit test，不滿足本節最低標準（unit test 是加分項，不是替代品）。
- ❌ check 指令跑的是「整包 test」但該 endpoint 根本沒有對應測試檔 → 綠燈是別人的綠燈。

---

## 2. 前端（頁面 / 元件 / 使用者旅程）

**最低標準：每個 user story 一條 Playwright E2E——從開頁到操作到斷言「畫面上看得到正確資料」，全程可跑。**

### DoD 模板句
```
R0xx：<頁面/功能> 完成後——
  a. Playwright E2E：導航至 <路由> → 執行 <關鍵操作序列> → 斷言畫面出現 <具體資料/狀態>
     （斷言用語意 selector（role/text），不用脆弱的 css path）。
  b. 該旅程全程 console 無 error（page.on('console') 收集斷言）。
  c. `npm run build` 通過（型別/lint 含在 build 或另列）。
  驗收指令：npx playwright test e2e/<story>.spec.ts
  後端來源：<真後端（整合環境）| API mock（附 mock 與真實 schema 的對齊方式）>——訪談時二選一定案。
```

### 任務切分與驗證對應
| 任務 | verify | check 範例 |
|------|--------|-----------|
| 一個 component | `command` | component test（vitest/RTL）：render + 互動 + 斷言輸出 |
| 一個頁面/user story | `command` | 該 story 的 Playwright spec |
| 共用 UI 契約（design tokens/共用元件/路由註冊） | `command` | 元件測試 + 一條掛載冒煙 |
| phase 收尾 | phase 級 `gate.check` | 全部 E2E + build；核心旅程（登入→主流程→登出）必在其中 |

### 環境要求
- Playwright 跑 headless、可在無人環境執行（這是 overnight 的硬條件）；依賴的後端在 plan 期定案：docker compose 起真後端（佳）或 route-level mock（可，但 mock 資料要從真實 schema 生成，並列一條「上整合環境重跑」的 NON_BLOCKING 待辦）。
- 斷言**資料正確性**而不只是「元素存在」：列表頁要斷言筆數與關鍵欄位值。

### 常見假驗收
- ❌ 「畫面截圖看起來對」→ 不可重跑、不可稽核。截圖可留作 L3 輔助，不算 L1。
- ❌ E2E 只做「頁面打得開」→ 旅程沒有操作與資料斷言，等於只驗 build。
- ❌ 視覺美感/易用性寫成擋停止的驗收 → 標 `MANUAL`，進人審清單。

---

## 3. 分析任務（逆向舊專案、理解邏輯流程）★ 最容易假收斂的一類

沒有編譯器把關，「我看懂了」不是完成定義。**完成 = 產出文件本身通過四道機械 gate + 收斂協定**（對應 `completeness.md` / `convergence.md`，此處是「怎麼用」的具體化）：

### 完成定義（DoD 模板句）
```
R0xx：完成 <目標範圍> 的邏輯分析，產出文件滿足——
  a. 分母明確：inventory 清單列出全部 <分析單位>（函數/事件/API/狀態轉換/畫面…，依任務定義），
     每項含 檔:行；DEAD 項附機械式零引用證據。
  b. 覆蓋閉合：來源檔行覆蓋 100%（閱讀涵蓋記錄）；每單位逐分支交代（不只 happy path）；
     被呼叫者皆可在 inventory 找到（閉合檢查）。
  c. 可追溯：文件中每個結論附 檔:行 來源。
  d. 收斂：inventory 集合穩定 N 輪（建議 2；核心高風險模組 3）＋各單位分析經獨立重驗。
```

### 「怎樣算收斂完成」的判定順序
1. **機械 gate 先過**（a–c 全是可檢查的形式要件，plan 應把它們寫進任務的驗證標準）；
2. **集合穩定 + 重驗計數達門檻**（引擎管，含證據檔）；
3. **人工抽查協定（L3，最終驗收必做）**：人隨機抽 K 項（建議 K=5 或 5%取大者）做兩種核對——
   - **正向**：對著結論找 檔:行，確認來源真的支持結論；
   - **反向（最有效）**：挑一個具體情境問「輸入 X 時系統行為是什麼？」，先用分析文件回答，再讀碼（或實際跑舊系統）對答案。答錯 → 該單位打回 NEEDS_REVISION，且抽查加倍。
4. 分析文件必須同步維護 `docs/INDEX.md`（知識索引，供後續 phase 查詢——見計畫書 4 M2.4）。

### 常見假收斂
- ❌ 「重驗一致」但重推稿沒有 檔:行 來源 → 抄既有產出的橡皮圖章（convergence.md 防偽獨立條款）。
- ❌ 難分析的單位標 DEAD 清分母 → DEAD 必附零引用證據。
- ❌ 只寫 happy path、分支「略」→ 逐分支是硬要件。

---

## 4. 遷移 / 搬移專案（legacy → 新技術棧）★ 綜合題，最需要事前定標準

**北極星：行為對等（behavioral parity）。** 遷移的 DoD 不是「新系統寫完了」，而是「**新舊系統對同一輸入給出同一輸出**，差異只存在於一份人簽核過的已知差異清單」。

### 4.1 技術對齊：先立「遷移契約」再動工

第一個先行任務（人核可後才 fan-out）：產出 **`MIGRATION_CONTRACT.md`**，內容：
```
1. 技術對照表：舊 → 新 逐項對應與理由
   （例：JSP scriptlet → React 元件 + REST API；Session 驗證 → JWT；
     存储過程 → service 層方法；iBatis XML → ORM schema…）
2. 邊界與例外：哪些「不遷移」（棄用功能，列清單人簽核）、哪些「先原樣後重構」。
3. 對等性容忍表：已知且接受的行為差異（日期格式、錯誤訊息文案、分頁大小…），
   每條附「為什麼可接受」與簽核人。
4. 對照驗證方式的選型（見 4.2，選哪一級寫明）。
```
> 為什麼是先行任務：對照表錯一格，下游全部返工——這正是「base 契約要先磨硬再 fan-out」原則的遷移特化。

### 4.2 驗證方法梯度（按可行性由強到弱選，plan 期定案）

| 級 | 方法 | 適用前提 | verify 落地 |
|----|------|----------|-------------|
| **P1 對照測試（parity test）** | 同一 request/輸入同時打舊系統與新系統，機械 diff 輸出（容忍表過濾已知差異） | 舊系統還能跑（本地/測試環境） | `command`：parity 腳本，每隻 API/功能一條 |
| **P2 特徵測試（characterization）** | 先對舊系統**錄製**行為成測試集（golden files），新系統過同一套 | 舊系統能跑但不便常駐 | 分析 phase 產 golden files（L2 證據），實作 phase `command` 對 golden 斷言 |
| **P3 規格對照** | 舊系統跑不起來：分析文件（第 3 節標準產出）即規格，新系統的 integration test 逐條對規格斷言 | 只剩程式碼 | 分析 phase 用第 3 節標準 + 實作 phase 用第 1/2 節標準，**需求驗收表逐條掛 R###** |
| 資料遷移（如有） | 筆數對帳 + 全表 checksum + 分層抽樣逐欄比對 + 新系統反查舊主鍵 | — | `command`：對帳腳本，數字不平 = FAIL |

**選型規則**：能 P1 就 P1（訪談時務必問「舊系統現在跑得起來嗎？」——這個答案決定整個驗證架構）；P3 是底線，且 P3 的分析 phase 收斂門檻應取高（3）。

### 4.3 完成定義（DoD 模板句）
```
遷移完成 =
  a. MIGRATION_CONTRACT.md 已人簽核，且執行期未出現契約外的技術決策（有 → 開 Issue 回契約）。
  b. Parity/characterization/規格對照 suite（依選型）全綠；
  c. 差異只存在於容忍表；容忍表每條有簽核；
  d. 核心使用者旅程 E2E 在新系統全綠（第 2 節標準）；
  e. （有資料遷移）對帳腳本全平 + 抽樣比對通過；
  f. 舊系統下線檢查清單（排程任務、對外 callback、cron）逐項確認有對應或明列不遷移。
```

### 常見坑（訪談時主動提醒使用者）
- ❌ 只驗 happy path parity → 錯誤路徑（4xx/5xx、驗證失敗訊息）常是行為差異重災區，contract 要涵蓋。
- ❌ 隱性行為沒進容忍表：**排序穩定性、時區、四捨五入、字元編碼、空值 vs 缺欄位**——P1 diff 會抓到，P3 靠人記，所以 P3 時這五項必列入分析清單。
- ❌ 「順便重構/順便加功能」混進遷移 → parity 永遠對不平。新功能另開需求，遷移期凍結行為變更。

---

## 5. 資料清洗 / 批次生成類

```
DoD：a. 分母對帳：輸入筆數 = 輸出筆數 + rejected 筆數（rejected 附原因清單）；
     b. 輸出 100% 通過 schema 驗證（command）；
     c. 抽樣 K 筆人工核對（L3）；
     d. 冪等：重跑一次，輸出 diff 為空（command）。
```

---

## 6. 給規劃 agent 的速查表（plan 期照表填 verify）

| 任務型 | verify.kind | 收斂門檻建議 | phase 收尾 gate.check |
|--------|-------------|--------------|----------------------|
| 後端 API 實作/移植 | command（integration test） | 1（check 綠即定稿） | 整包 integration suite |
| 前端元件/頁面 | command（component/E2E test） | 1 | 全 E2E + build |
| 共用契約先行任務 | command（schema/冒煙） | 1，但**人核可後才解鎖下游** | — |
| 邏輯分析/逆向 | enumerate + reverify | 2（核心模組 3） | 完整性 Gate + 人工抽查 |
| 遷移契約 | reverify + **人簽核** | 2 | — |
| parity/對帳 | command | 1 | parity suite 全綠 |
| 主觀品質（美感/易用） | `MANUAL` | — | 人審清單，不擋機械停止 |

**plan gate 抽查基準**：任一任務的驗證方式低於本表對應行（例：API 任務只有「能編譯」、分析任務沒有 inventory 分母）→ 退回 `1-plan-generator.md` 重寫。

---

## 7. 訪談時的三個必問（把標準前置到需求期）

1. **「這條需求做完，我用什麼**指令或動作**在 10 分鐘內確認它是對的？」**——答不出來就一起翻本檔對應章節套模板。
2. **「舊系統/依賴環境現在跑得起來嗎？」**——決定遷移驗證選 P1/P2/P3、決定 integration test 環境方案。
3. **「哪些部分你願意接受人工驗收？」**——`MANUAL` 清單越早劃清，機械停止條件越乾淨。
