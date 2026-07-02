# 📋 REQUIREMENTS — JSP → React 遷移專案

> 階段①產出（需求訪談）。**人類最終確認**後才進階段②生成規劃書。
> 本檔依 loop-agent 框架 `generators/templates/REQUIREMENTS.template.md` 填寫，
> 驗收標準整合自《JSP → React 遷移驗證規劃文件》的 L1~L6 分層驗證設計。

## 1. 目標（goal）
把既有 JSP 網站的頁面／元件，逐一遷移為 React（TypeScript）實作，遷移後行為與內容需與原 JSP
版本等價，且每個頁面／元件都必須通過六層驗證（L1 靜態分析～L6 覆蓋度稽核）才算完成，
而不是「編譯過就當作完成」。

## 2. 完成定義（DoD）/ 驗收標準
單一頁面／元件遷移，需**同時**滿足以下條件才算「Done」（對應 phase 任務的驗證標準）：
- [ ] `tsc --noEmit --strict` 零錯誤
- [ ] `eslint`（含 `import/no-unresolved`、`import/named`、`import/default`、
      `react-hooks/rules-of-hooks` 等規則）零 error
- [ ] Production build 成功，log 中無 `Could not resolve` / `Module not found`
- [ ] Playwright smoke test：目標路由 `consoleErrors` = 空陣列
- [ ] Playwright smoke test：`pageerror`（未捕捉例外）= 空陣列
- [ ] Playwright smoke test：network response 無 4xx/5xx
- [ ] 主要互動流程（表單送出、按鈕點擊、tab 切換等）已模擬執行且無錯誤
- [ ] 原 JSP 邏輯覆蓋度稽核 100%，或遺漏項目已人工簽核（不得自行標記 DEAD 了事）
- [ ]（如適用）與原頁面關鍵資料欄位比對一致，或視覺差異率 < 5%
- [ ]（如原案有對應測試）單元測試通過

**全案 Done** = 所有頁面／元件皆達成上述單頁 DoD，且最終 phase 的全量驗證
（逐條 R### 驗收 + L6 全域覆蓋度掃描）連續達門檻輪 PASS，`blocking_issues == 0`。

## 3. 需求清單（逐條編號，之後追溯到任務與驗證）
| 需求 ID | 描述 | 驗收方式 |
|---------|------|----------|
| R001 | 所有原始 `.jsp` 檔案都需被機械式列舉、無遺漏地列入遷移清單（inventory） | inventory 檔覆蓋率 100%，可對照原始 `.jsp` 檔案清單機械核對 |
| R002 | 共用型別／API client／路由註冊／共用元件庫，需作為先行任務完成並收斂，其餘頁面 `depends_on` 它 | 先行任務 CONVERGED 後，依賴頁面任務才可開始；`loop.config.yaml` 依賴圖無環 |
| R003 | 每個頁面／元件遷移後，型別檢查與 Lint 全過（對應 L1） | `tsc --noEmit --strict` 與 `eslint` exit code 皆為 0（warning 可容忍，error 不可） |
| R004 | 每個頁面／元件遷移後可成功納入 production build（對應 L2） | build 成功，log 無 `Could not resolve` / `Module not found` |
| R005 | 每個頁面於 headless browser 中可真正執行，且無隱藏 runtime 例外（對應 L4，最關鍵一層） | Playwright smoke test：`consoleErrors` / `pageerror` / 4xx-5xx response 三者皆為空 |
| R006 | 主要互動流程（表單、按鈕、tab）在遷移後仍可正確觸發，不只是首屏渲染 | Playwright 對關鍵 `data-testid` 元素模擬互動後仍零例外 |
| R007 | （如原站仍可存取）遷移後與原 JSP 版本關鍵資料欄位／行為需等價（對應 L5） | 關鍵 DOM 欄位 `textContent` 比對一致，或視覺差異率 < 5% |
| R008 | 原 JSP `scriptlet`（`<%...%>`）、EL（`${...}`）、自訂 taglib 邏輯需 100% 被轉換覆蓋，或經人工簽核排除（對應 L6） | 覆蓋度稽核腳本輸出之「未確認轉換項目」清單為空，或每筆遺漏皆有人工簽核註記 |
| R009 | （如原案有涵蓋業務邏輯的測試）遷移後單元測試需通過（對應 L3） | `vitest run --coverage` 全過；若原本無對應測試，此項降級為 Nice to have 並在報告中標註「無測試覆蓋」 |
| R010 | 逐頁遷移，不可批次遷移多頁後才驗證；每頁任務失敗時，原始錯誤訊息（非摘要）需回饋給下一輪修正 | `state.json` 任務狀態顯示逐頁完成順序；Issue/失敗記錄含原始 stack trace / console 輸出全文 |

## 4. 輸入
- 位置：`<原 JSP 專案路徑，使用者填>`；新 React 專案：`<目標 code repo 路徑，使用者填>`
- 格式：`.jsp` 檔案，內含 scriptlet / EL 表達式 / 自訂 taglib，可能搭配 Struts / Spring MVC controller
- 是否近似重複：**是**——多數頁面共用 layout／表單元件／表格元件結構相近 → 套「base + 變體」
  最大化複用（先遷移一個代表頁作為 base，其餘頁面標記與 base 的差異點）
- 跨專案唯讀參考：若 JSP 原始碼與新 React 專案是不同 repo，依框架規範用唯讀 worktree 掛載：
  ```bash
  git -C /path/to/OLD-JSP-REPO worktree add ./.loop/<name>/inputs/jsp-src HEAD
  echo ".loop/*/inputs/" >> .gitignore
  chmod -R a-w ./.loop/<name>/inputs/jsp-src
  ```
  完成後在此標註實際路徑：`./.loop/<name>/inputs/jsp-src/`（唯讀參考輸入，用完 `git worktree remove`）

## 5. 限制與已知風險
- 部分 JSP scriptlet 可能耦合 server-side session／state，無法 1:1 對應 React（需先確認是否已有
  對應 API，沒有的話遷移範圍需擴及後端 API 化，這會顯著影響 phase 切法）
- EL/scriptlet 可能呼叫後端 Java 服務／自訂 taglib，需要有人（或文件）能解釋這些 tag 的語意，
  否則 agent 只能「看起來轉完但邏輯漏掉」（L6 要防的正是這個）
- 若原站已下線或無 staging 環境，L5（行為/視覺對比）與「關鍵資料欄位比對」需改用固定測資或 mock，
  否則此驗收方式無法執行
- 頁面若需要登入態才能到達，需先準備測試帳密或 mock 登入，供 Playwright smoke test 使用
- 頁面總數若很大（大量頁面），需要套用 completeness 防漏協定（見第 8 節）避免遷移清單本身漏頁

## 6. 任務類型
遷移（migration），且因頁面量體大、結構近似重複 → 適用「base + 變體」模式；
同時因「遺漏不會反映在編譯/runtime 錯誤上」（L6 的核心風險）→ 需疊加大範圍防漏協定（completeness）。

## 7. 工作區拓撲
- 被改的 code repo：`<新 React 專案路徑，使用者填>`
- workspace.mode：`in_repo`（建議）

## 8. 防漏 / 防爆註記
- 大範圍輸入：**是**（多個 `.jsp` 檔案）→ 需 completeness 列舉清單協定：
  - 分母 = 機械式掃描全部 `.jsp` 檔案得到的清單（含檔案路徑），每項狀態 `PENDING/ANALYZED/DEAD`
  - 每個 `.jsp` 內的 scriptlet / EL / 自訂 tag 使用點，也要建成子清單（對應 L6 覆蓋度稽核的分母）
  - 大檔（如 >300 行的 `.jsp`）分段精讀，維護行覆蓋記錄
  - `DEAD`（確認該邏輯冗餘、故意不轉）必須附機械式證據（如「grep 全站零引用」），不接受純文字理由
- 提醒：完整性靠列舉清單 + 行覆蓋，**不整批**把所有 JSP 原始碼一次讀進 context；逐頁讀取、逐頁驗證。

---
> 確認後在此標記：**REQUIREMENTS CONFIRMED（日期 / 確認人）**

---

## 附錄：給階段②（`1-plan-generator.md`）的規劃建議（非必填，僅供參考）

實際 phase/task 切法由 `engine/plan_loop.py` 每輪生成，但依 BLUEPRINT 的任務粒度原則，
這個專案大致會落成類似下面的形狀（一個頁面/元件 = 一個任務，不可把多頁包成一輪）：

- **Phase 1｜共用基礎設施**（先行任務，Init 類，完成即定稿）
  - 共用型別／API client／路由註冊／共用元件庫（Layout、表格、表單元件等）
  - 建立 JSP 全站 inventory（R001 的分母）與遷移清單自動產生腳本
  - 建立 L1~L4 驗證 pipeline 骨架（`tsc`/`eslint` 設定、Playwright 專案初始化、
    路由清單自動從遷移進度產生，不手動維護）
- **Phase 2｜逐頁遷移**（每頁一個任務，`depends_on` Phase 1 的共用契約任務；
  收斂類別＝「有客觀把關」，以 L1+L2+L4 pass 為收斂依據，不需多輪主觀重推）
  - 每個任務＝一個 JSP 頁面／React 元件，驗證標準＝第 2 節的單頁 DoD 清單
  - base 頁面先做，變體頁面在 base CONVERGED 後才開始（複用其驗證腳本骨架）
- **Phase 3｜全案收尾驗證**（全量驗證收斂，門檻建議 ≥10 輪）
  - L6 全域覆蓋度稽核（掃描所有頁面，未覆蓋項目清單需為空或全部人工簽核）
  - （如適用）L5 抽樣行為/視覺對比、L3 單元測試批次跑
  - 逐條 R001~R010 驗收（不可只看內部計數器全綠就結案）
