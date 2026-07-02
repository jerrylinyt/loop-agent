# 🏗️ GENERATOR — 階段②：生成規劃書（config + state.json + phases）

> **怎麼用**:這份是**每輪的指令**,由 `engine/plan_loop.py` 反覆觸發(規劃書本身是收斂目標)。
> 輸入 `REQUIREMENTS.md`(已人類確認)+ `rules/BLUEPRINT.md`,**產出這個專案專屬的規劃書**。
> 階段數、任務、收斂門檻、停止條件**全部在這一段生出來**,不預設幾個階段。
>
> **收斂迴圈行為(每輪務必遵守)**:
> 1. 若已存在規劃書 → **先不看舊版、從 REQUIREMENTS 獨立重推一份**,再與現有比對。
> 2. **只在有「實質差異」時才改檔**;無實質差異就不要動檔(讓它穩定下來)。
> 3. 更新 `state.json` 中的 `plan` 物件:`plan_changed_last`(true=本輪有實質改動/false)與 `plan_status`。
> 4. ❗**Plan Gate 由獨立的下一輪負責審查**(全新 context,讀 `2-plan-review-gate.md`,只審不生)——
>    這一輪(生成輪)不要自己跑 Gate，以免自己生、自己審的橡皮圖章。
> 連續達門檻輪「無實質變更且 Gate PASS」→ plan_loop 判定規劃書收斂(gated 停下交人類 / auto 接執行)。

## 你要產出兩樣東西（放 code repo 的 .loop/<name>/ 目錄下）
1. **`loop.config.yaml`**（填 `templates/loop.config.template.yaml`）
   - 依需求決定 **phases**(幾個、各 name、spec 檔、output 位置、converge_threshold)。最後一筆=最終階段。
   - 設 `stop_condition`、`oscillation` 門檻、`runtime`(含 context 防爆旋鈕)。
   - `framework_path` 指向共享框架 clone;`workspace.mode` 依需求。
   - ⚠️ **不要動 `agent.build_cmd` / `agent.models`**——這兩項已由人類在 `bootstrap.md` STEP 2 填好實際值
     (preflight 會在這個迴圈啟動前就檢查過,若還是佔位值根本進不到這一輪)。
   - 🚨 **不需要產出任何 Markdown 狀態檔案**，也嚴禁手動或寫腳本修改 `state.json`。收斂後系統會自動依據你的 `loop.config.yaml` 建立 `state.json` 骨架。你如果需要定義「需求→任務追溯表」或「Coverage 定義」，這些資訊會被直接定義在 `loop.config.yaml`（例如 requirements_map 欄位）或隨後自動寫入 `state.json`。
2. **`phases/PHASE1.md … PHASEn.md`**（填 `templates/PHASE.template.md`）
   - 每階段一份,把該階段的任務逐一寫成「依賴讀取 / 做什麼 / 產出位置 / 驗證標準」。
   - 數量 = config.phases 數。

## 必須落實的規劃原則（對映 BLUEPRINT 第七部）
- **需求全覆蓋**:每條 R### 至少對應一個任務。把「需求→任務」追溯資訊定義在 `loop.config.yaml` / `state.json` 可讀取的結構欄位中。
- **任務粒度**:每個任務 = 一個可被**單獨驗證**的「自然單位」,由語意切、不是看「一輪做不做得完」——
  一隻 API(移植/新增)= 一個任務、一個 component = 一個任務;共用介面/型別/schema/路由註冊
  抽成一個**先行任務**(其餘 `depends_on` 它)。涵蓋 >1 個自然單位、或寫不出「對這片單獨判
  pass/fail 的檢查」→ 再往下拆。🚨 別把一個 controller 的 20 隻 API 包成一輪(那是 20 個自然單位,
  應拆成約 20 個任務 + 視情況 1 個共用契約先行任務)。反向也別過細:切太碎被每片固定開銷
  (boot/context/review/收斂×N)吃掉,甜蜜點是「仍可單獨驗證、又仍是有意義的整體」。
  (定義見 BLUEPRINT §3.10「最小工作單位」——該節雖在樹模式段,粒度判準對平 phase 模式同樣適用。)
- **依賴無循環**:階段/任務依賴是 DAG。
- **收斂安排**:不信單次的任務 → 指定收斂層級與門檻(convergence.md);大範圍怕漏的任務 → 套 completeness.md(列舉清單 + 行覆蓋 + 集合穩定收斂)。
- **驗收標準達標**:每個任務的驗證方式【不得低於】`acceptance-standards.md` §6 速查表對應行——
  後端 API 一律 integration test(真 request 斷言完整資料)、前端一律 component/Playwright E2E、
  分析任務一律 inventory 分母 + 行覆蓋 + 檔:行 追溯、遷移任務先立 MIGRATION_CONTRACT 再依 P1/P2/P3 選對照驗證。
  只能寫「能編譯/能跑」當驗收的任務,回頭重想;真的只能人工判定的,明確標 MANUAL 進人審清單、不擋機械停止。
- **停止可判讀**:stop_condition 全是可 grep 的計數器,**不可**設成「Open Issue=0」(用 blocking_issues==0)。
- **逃生門**:震盪/卡死門檻、FROZEN、human_required 就位(oscillation-escalation.md)。

## Context 防爆（生成時就把關，見 context-budget.md F）
- `state.json` 保持「決策最小集」:只放引擎/agent 需要判讀的結構化狀態；執行日誌移出(進 loop.log)、Issue 一檔一個只留索引、產出一檔一主題。
- 任務的「依賴讀取」要**最小且具體**(只讀哪幾個檔、哪幾行),不可出現「讀整個 outputs 檢視」這種任務。
- 設好 log rotation / control_max_bytes。

## 重生 / 需求變更（diff 模式）
- 若是「需求變更回流」而非首次生成:**diff 模式**——只改受影響的 `loop.config.yaml` / `state.json` / `phases` 段落,不整碗重寫;把受影響任務改 `NEEDS_REVISION`;`plan_version++` 並打 tag `plan-v{n}`。

## 產出後
- 不要在這一輪自審。下一輪(獨立 context)會依 `2-plan-review-gate.md` 審查;
  全過 → 提示人類確認 plan + 看輪數估算 → 才開始階段③(跑引擎)。
