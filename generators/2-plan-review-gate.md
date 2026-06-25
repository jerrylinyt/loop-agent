# 🚦 GENERATOR — 階段②門：Plan Review Gate

> **怎麼用**:階段②生成規劃書後、開始執行(階段③)前,跑這份檢查表。**全過**才放行;**人類確認 plan + 看輪數估算**後才開始。
> 由一個 agent(最好是新 context)對著生成的 `loop.config.yaml` + `CONTROL.md` + `phases/*.md` 逐項打勾並附證據。

## 檢查表（全過才放行）
```
□ 需求全覆蓋:CONTROL 的「需求→任務」追溯表中,每條 R### 都對應到至少一個任務(逐條列出對應)。
□ 任務粒度:每個任務「一輪可完成」,無一輪做不完的巨任務(逐 phase 抽查)。
□ 無循環依賴:階段/任務依賴是 DAG(畫出依賴、確認無環)。
□ 停止可判讀:config.stop_condition 全是可 grep 的計數器,且不會死結
            (確認用 blocking_issues==0,非「Open Issue=0」)。
□ 收斂就位:不信單次的任務都指定了收斂層級與門檻;大範圍任務套了 completeness 協定
          (列舉清單 + 行覆蓋 + 集合穩定收斂)。
□ 逃生門就位:oscillation 門檻、FROZEN、human_required 都已設定。
□ Context 防爆(context-budget.md):無任何「會無限長大且會被每輪讀進 context」的設計——
            執行日誌移出 CONTROL、Issue/產出分散成檔、log rotation 已設、
            每輪讀取預算明確、沒有「整批讀資料來檢視」的任務。
□ 框架唯讀邊界:沒有任務會寫入 framework_path;寫入白名單只含 .loop/ 與工作區。
□ 引擎可讀性:config 能被引擎解析(phases 有 id、最後一筆=最終階段;stop_condition 欄位齊全)。
□ 輪數估算:粗估總輪數(收斂門檻 × 任務數 × 階段 × 驗證次數),提供給人類判斷是否調門檻。
```

## 輸出
- 全過 → 輸出「PLAN GATE PASSED」+ 輪數估算,提示人類確認後可啟動引擎(`engine/loop.py`)。
- 任一項未過 → 列出未過項與修正建議,退回 `1-plan-generator.md` 修補後重檢。
