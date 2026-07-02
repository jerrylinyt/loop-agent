# 📋 REQUIREMENTS — JSP → React 遷移：API 回歸驗證（第二階段需求）

> 階段①產出（需求訪談），依 `generators/templates/REQUIREMENTS.template.md` 填寫。
> **這是獨立於第一份需求的第二個 workspace**：第一份需求（mock 階段遷移）跑完、且真實後端
> API 已就緒後才啟動這份。**本輪不執行**，先備存，待條件成立時再用
> `python3 <framework_path>/init-project.py <repo> --name api-regression` 開新 workspace 帶入。
>
> 前置條件：第一份需求已把頁面/元件遷移完成，狀態為 `CONVERGED_MOCK`（所有資料串接走本地 mock）。

## 1. 目標（goal）
真實後端 API 就緒後，把所有先前以 mock 資料完成遷移（`CONVERGED_MOCK`）的頁面／元件，
逐一切換為呼叫真實 API，並重新跑驗證，把狀態從 `CONVERGED_MOCK` 提升為 `CONVERGED_REAL`，
確保「mock 階段驗證通過」不等於「真實環境會壞」。

## 2. 完成定義（DoD）/ 驗收標準
單一頁面／元件的回歸驗證，需同時滿足以下條件才算「Done」：
- [ ] 該頁面所有網路呼叫已從 mock route/handler 切換為真實 API endpoint，mock 攔截碼已移除
- [ ] Playwright smoke test 對接真實 API 重新跑一次：`consoleErrors` / `pageerror` / 4xx-5xx response 皆為空
- [ ] Mock 階段使用的 response schema，與真實 API 實際回傳的 schema 逐欄位比對一致；
      有落差一律開 Issue 記錄，**不得自行腦補修正掩蓋**（可能代表當初契約假設錯誤）
- [ ] Loading / Error / Empty 三種狀態在真實網路延遲與真實錯誤情境下重新驗證（mock 階段多半是
      同步瞬回、不含真實 delay，容易漏掉 loading spinner 缺失、race condition 等問題）
- [ ] 若頁面涉及登入態／權限：確認真實 auth 流程（token 取得、過期、401 導向）在真實 API 下運作正常
      （mock 階段若用假 token，這段完全沒被驗證過）
- [ ]（如原 JSP 站仍可存取）補做 L5 行為/視覺對比——此時才有真正意義，因為兩邊都是真實資料
- [ ]（如適用）確認真實 API 的回應時間下，頁面無 timeout 或使用者能感知的卡頓／無回饋

**全案 Done** = 前次 mock 階段清單中的所有頁面／元件皆完成上述回歸 DoD，
且最終 phase 全量驗證（逐條 R### 驗收）連續達門檻輪 PASS，`blocking_issues == 0`。

## 3. 需求清單（逐條編號，之後追溯到任務與驗證）
| 需求 ID | 描述 | 驗收方式 |
|---------|------|----------|
| R001 | 前次 mock 階段所有 `CONVERGED_MOCK` 頁面／元件，需完整列入本次回歸清單（inventory），不可遺漏 | 回歸 inventory 覆蓋率 100%，對照第一份需求的頁面/元件清單機械核對 |
| R002 | 每個頁面的 mock route/handler 需被移除，改為呼叫真實 API endpoint | 程式碼中無殘留 mock 攔截邏輯（grep 零引用），且 network tab 顯示真實 request |
| R003 | 每個頁面重新跑 Playwright smoke test，對接真實 API | `consoleErrors` / `pageerror` / 4xx-5xx response 三者皆為空陣列 |
| R004 | Mock schema 與真實 API schema 需逐欄位 diff，任何落差需開 Issue，不得腦補 | Issue 檔列出每個落差欄位（頁面/欄位名/mock 型別 vs 真實型別），或 diff 結果為空 |
| R005 | Loading/Error/Empty 三態需在真實 API 情境下重新驗證 | 模擬真實 delay（可用 Playwright 對真實 API 加人工延遲或觀察自然延遲）、模擬真實錯誤（如暫時關閉某 endpoint 觀察錯誤 UI），確認皆有對應處理而非白屏/無回饋 |
| R006 | 涉及登入態的頁面，需驗證真實 auth 流程（含 401/token 過期導向） | Playwright 模擬未登入/token 過期情境，確認導向或錯誤提示正確 |
| R007 |（如原站仍可存取）補做 L5 行為/視覺對比 | 關鍵 DOM 欄位 `textContent` 兩邊比對一致，或視覺差異率 < 5% |
| R008 | 真實 API 回應時間下頁面需有合理使用者回饋（無感知卡頓/無回饋的空窗） | 人工或 Playwright 觀察頁面在真實延遲下有 loading 指示，且無 timeout 錯誤 |

## 4. 輸入
- 位置：`<同一個 React 專案路徑，與第一份需求相同 repo，使用者填>`
- 前置產出：第一份需求（mock 遷移）的頁面/元件清單與其 mock schema 定義（作為本次 diff 的基準）
- 真實 API 規格：`<真實後端 API 文件/Swagger/OpenAPI 位置，若有，使用者填>`
- 是否近似重複：視第一份需求的 base+變體分組而定，可沿用同樣分組跑回歸

## 5. 限制與已知風險
- 真實 API 可能與當初 mock 假設的契約有落差（late-breaking backend 變更），這是本需求存在的主因，
  不應被當成「異常」而是預期會發生、需要機制去捕捉（R004）
- 可能出現只有真實環境才會有的問題：CORS、真實 auth token 流程、真實網路延遲下的 race condition
- 若真實 API 尚未完全涵蓋所有頁面所需的 endpoint（部分頁面可能還要繼續 mock），
  需要在回歸 inventory 裡標註「此頁本輪不回歸，繼續 mock」，不可硬套

## 6. 任務類型
回歸驗證（regression validation），非全新遷移——不需要重寫元件邏輯，
聚焦在「資料串接切換 + 重新驗證」，粒度仍是「一頁/一元件 = 一任務」。

## 7. 工作區拓撲
- 被改的 code repo：與第一份需求相同（`<路徑，使用者填>`）
- workspace：**新開一個**，例如 `--name api-regression`（不要沿用第一份需求的 workspace，
  避免規劃書/狀態互相覆蓋；兩份需求本質是不同批次的任務）
- workspace.mode：`in_repo`（建議，與第一份需求一致）

## 8. 防漏 / 防爆註記
- 分母 = 第一份需求跑完後的頁面/元件 inventory（`CONVERGED_MOCK` 清單），直接沿用、不重新盤點 JSP 原始碼
- 每頁的「mock schema vs 真實 schema diff」也要建成子清單，確保沒有頁面漏掉 diff 這一步
- 提醒：診斷落差時，不整批把 mock 定義與真實 API response 一次讀進 context；逐頁 diff、逐頁記錄

---
> 確認後在此標記：**REQUIREMENTS CONFIRMED（日期 / 確認人）**
> 啟動前提醒：本需求需等真實 API 就緒才開始，**不在本輪執行**。
