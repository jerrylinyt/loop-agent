# 🚦 GENERATOR — 階段②門：Plan Review Gate

> **怎麼用**:階段②生成規劃書後、開始執行(階段③)前,跑這份檢查表。**全過**才放行;**人類確認 plan + 看輪數估算**後才開始。
> 由一個 agent(最好是新 context)對著生成的 `loop.config.yaml` + `state.json` + `phases/*.md` 逐項打勾並附證據。


## 檢查表（全過才放行）
```
□ 需求全覆蓋:state.json（或 loop.config.yaml）的「需求→任務」追溯表中，每條 R### 都對應到至少一個任務(逐條列出對應)。

□ 需求逐條驗收:最終 phase 的「全量驗證清單」必須明列『逐條 R### 驗收』項——
            停止條件只看 p{last}_pass>=N 與 blocking==0,若驗證清單沒把每條需求當作驗收項,
            就可能「內部計數全綠卻沒真正達標」(BLUEPRINT 原則1/反模式「解錯問題」)。
□ 任務粒度:每個任務 = 一個可被「單獨判 pass/fail」的自然單位,不是「一輪感覺做得完」就算過(逐 phase 抽查)。
            · 一隻 API(移植/新增)= 一個任務;一個 component = 一個任務。
            · 共用介面/型別/schema/路由註冊 → 抽成一個先行任務,其餘 depends_on 它。
            · 涵蓋 >1 個自然單位、或寫不出對這片單獨的 pass/fail 檢查 → 退回 1-plan-generator 重拆。
            🚨 典型反例:把一個 controller 的 20 隻 API 包成「移植 controller」一輪——
               那是 20 個自然單位,須拆成約 20 個任務(+ 視情況 1 個共用契約先行任務)。
            煙霧圍欄(僅警訊、非切割準則):單位遠超 config.min_unit.max_files 檔 / max_lines 行
               → 回頭確認是不是包了多個單位;確為單一自然單位者不因行數硬拆。
            下限:別過細——切太碎被每片固定開銷(boot/context/review/收斂×N)吃掉,
               甜蜜點是「仍可單獨驗證、又仍是有意義的整體」。
□ 葉子粒度（樹模式）:上一條「任務粒度」在樹模式的具體化。若啟用拆解樹,每個 LEAF 節點須符合最小工作單位定義——
            可獨立驗證的單一 component；proxy：≤ config.min_unit.max_files 檔、
            ≤ config.min_unit.max_lines 行、單一關注點。
            過大的葉子退回重拆。只有葉子受此約束,中間節點不受。
□ 驗收標準達標:逐 phase 抽查任務的「驗證標準」欄,不得低於 acceptance-standards.md §6 速查表——
            · 後端 API 任務:有 integration test(真 request、斷言 status+schema+資料值,含錯誤路徑),
              只寫「能編譯/status 200」→ 退回。
            · 前端任務:有 component test 或 Playwright E2E(含操作與資料斷言),只寫「畫面正常」→ 退回。
            · 分析任務:有 inventory 分母 + 行覆蓋 + 逐分支 + 檔:行 追溯要求,只寫「分析完成」→ 退回。
            · 遷移專案:存在 MIGRATION_CONTRACT 先行任務(人簽核),且對照驗證選型(P1 parity/P2 特徵/P3 規格對照)已定。
            · 純主觀品質項:已標 MANUAL 且不在機械停止條件內。
□ 無循環依賴:階段/任務依賴是 DAG(畫出依賴、確認無環)。
□ 停止可判讀:config.stop_condition 全是可 grep 的計數器,且不會死結
            (確認用 blocking_issues==0,非「Open Issue=0」)。
□ 收斂就位:不信單次的任務都指定了收斂層級與門檻;大範圍任務套了 completeness 協定
          (列舉清單 + 行覆蓋 + 集合穩定收斂)。
□ 逃生門就位:oscillation 門檻、FROZEN、human_required 都已設定。
□ Context 防爆(context-budget.md):無任何「會無限長大且會被每輪讀進 context」的設計——
            執行日誌移出 `state.json`、Issue/產出分散成檔、log rotation 已設、
            每輪讀取預算明確、沒有「整批讀資料來檢視」的任務。
□ 框架唯讀邊界:沒有任務會寫入 framework_path;寫入白名單只含 .loop/ 與工作區。
□ 引擎可讀性:config 能被引擎解析(phases 有 id、最後一筆=最終階段;stop_condition 欄位齊全)。
□ 輪數估算:粗估總輪數(收斂門檻 × 任務數 × 階段 × 驗證次數),提供給人類判斷是否調門檻。
```

## 輸出
- 全過 → 輸出「PLAN GATE PASSED」+ 輪數估算,提示人類確認後可啟動引擎(`engine/loop.py`)。
- 任一項未過 → 列出未過項與修正建議,退回 `1-plan-generator.md` 修補後重檢。
