# 🏗️ GENERATOR — 階段②：生成規劃書（config + CONTROL + phases）

> **怎麼用**:輸入 `REQUIREMENTS.md`(已人類確認)+ `rules/BLUEPRINT.md`,**產出這個專案專屬的規劃書**。產完跑 `2-plan-review-gate.md` 的檢查,**人類確認 plan**後才開始執行(階段③)。
> 階段數、任務、收斂門檻、停止條件**全部在這一段生出來**,不預設幾個階段。

## 你要產出三樣東西（放 code repo 的 .loop/）
1. **`loop.config.yaml`**（填 `templates/loop.config.template.yaml`）
   - 依需求決定 **phases**(幾個、各 name、spec 檔、output 位置、converge_threshold)。最後一筆=最終階段。
   - 設 `stop_condition`、`oscillation` 門檻、`runtime`(含 context 防爆旋鈕)、`models`(或交給 profile)。
   - `framework_path` 指向共享框架 clone;`workspace.mode` 依需求。
2. **`CONTROL.md`**（填 `templates/CONTROL.template.md`）
   - **每個 phase 一張狀態表**(任務清單,Status/Conv/Round 欄)。
   - coverage 定義(每個指標寫清楚**分母來源**)。
   - repo 結構(這個專案的輸入/產出夾)。
   - 通用協定段落**引用** `framework_path/rules/*`(boot/git/收斂/防漏/震盪/issue),**不要 copy-paste**。
   - 活計數器區(依 `rules/state-model.md`,每 phase 一組 `p{id}_*`)。
3. **`phases/PHASE1.md … PHASEn.md`**（填 `templates/PHASE.template.md`）
   - 每階段一份,把該階段的任務逐一寫成「依賴讀取 / 做什麼 / 產出位置 / 驗證標準」。
   - 數量 = config.phases 數。

## 必須落實的規劃原則（對映 BLUEPRINT 第七部）
- **需求全覆蓋**:每條 R### 至少對應一個任務。在 CONTROL 放一張「需求→任務」追溯表。
- **任務粒度**:每個任務「一輪可完成」;太大就拆。
- **依賴無循環**:階段/任務依賴是 DAG。
- **收斂安排**:不信單次的任務 → 指定收斂層級與門檻(convergence.md);大範圍怕漏的任務 → 套 completeness.md(列舉清單 + 行覆蓋 + 集合穩定收斂)。
- **停止可判讀**:stop_condition 全是可 grep 的計數器,**不可**設成「Open Issue=0」(用 blocking_issues==0)。
- **逃生門**:震盪/卡死門檻、FROZEN、human_required 就位(oscillation-escalation.md)。

## Context 防爆（生成時就把關，見 context-budget.md F）
- CONTROL 保持「決策最小集」:執行日誌移出(進 loop.log)、Issue 一檔一個只留索引、產出一檔一主題。
- 任務的「依賴讀取」要**最小且具體**(只讀哪幾個檔、哪幾行),不可出現「讀整個 outputs 檢視」這種任務。
- 設好 log rotation / control_max_bytes。

## 重生 / 需求變更（diff 模式）
- 若是「需求變更回流」而非首次生成:**diff 模式**——只改受影響的 config/CONTROL/phases 段落,不整碗重寫;把受影響任務改 `NEEDS_REVISION`;`plan_version++` 並打 tag `plan-v{n}`。

## 產出後
- 跑 `2-plan-review-gate.md` 自檢 → 通過 → 提示人類確認 plan + 看輪數估算 → 才開始階段③(跑引擎)。
