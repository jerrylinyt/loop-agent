# 📋 PHASE<n> — <階段名稱> 任務規格

> **僅當 `state.json` 中 `current_phase == <n>` 時讀此檔。**
> **只讀你本輪要做的那一個 TASK 小節**,不要整檔讀完(省 context,見 framework rules/context-budget.md)。
> 狀態、計數器、Coverage、通用協定都以 `state.json` / framework rules 為準。
>
> 🔁 收斂:本階段任務依 `state.json` 與 `convergence.md` 定義——初稿後做「獨立重驗」(先不看舊文件、從來源重推一份再對比),有實質差異就修正並把 conv 歸零,連續達門檻才 CONVERGED。
> 大範圍怕漏的任務另套 `completeness.md`(列舉清單 + 行覆蓋 + 集合穩定收斂)。
> 每輪結束別忘 BOOT STEP C:`git add -A && git commit`(只在工作區)。

---

## TASK-01｜<任務名>
- **依賴讀取**: <只列要讀的那幾個檔、哪幾行；不可「讀整個 outputs」>
- **做什麼**:
  1. <步驟…>
- **產出位置**: <config.phases[n].output 下的哪個檔>
- **驗證標準**（也是重驗時的對比基準）: <怎樣算對>
- **收斂**: <用單任務收斂(門檻 N) / 集合穩定收斂(page_converge) / Init 不需收斂>

---

## TASK-02｜<任務名>
- **依賴讀取**: <…>
- **做什麼**: <…>
- **產出位置**: <…>
- **驗證標準**: <…>
- **收斂**: <…>

---

## 本階段全量驗證（驗證模式時做）
- 檢查項:<覆蓋率 / 一致性 / 可追溯 / 技術正確 / 邊界 / **逐條需求驗收**>
- 全 PASS → 對應 `p<n>_consecutive_pass += 1`;任一 FAIL → 歸零 + 回填 last_round_fail_tasks。
