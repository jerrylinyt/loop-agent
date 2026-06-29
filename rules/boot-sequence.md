# 📐 RULE — BOOT SEQUENCE（通用開機程序）

> **唯讀框架規則**。本檔技術中立、不綁語言/框架/階段數。具體的階段、產出位置、停止門檻一律「**依 `loop.config.yaml`**」。
> 每個 agent 被觸發時的**第一件事**就是執行這段。順序不可跳。
> 相關規則:`git-safety.md`、`state-model.md`(計數器/流程)、`context-budget.md`(讀取預算)、`convergence.md`、`completeness.md`、`oscillation-escalation.md`、`issues.md`。

```
══════════════════════════════════════════════════════
 BOOT SEQUENCE
══════════════════════════════════════════════════════

STEP 0 ▶ 只讀「本專案 state.json」全文 + 本輪需要的「framework rules」那幾份。
         必讀:state.json、本檔 boot-sequence.md。
         按需讀:當輪用到的協定(做收斂讀 convergence.md / 大範圍讀 completeness.md…)。
         ❌ 不要一次載入全部 rules、不要先讀 phase 檔/輸入/產出(還不知道要哪些)。(見 context-budget.md)

STEP 1 ▶ 讀取變數與計數器。狀態唯一的單一事實來源為 state.json。本輪執行時應讀取 state.json 以取得 current_phase、計數器與任務狀態。


STEP 2 ▶ 檢查停止條件(依 config.stop_condition):
         IF current_phase==<config.phases 最後一筆> AND
            <最後一筆 phase 全任務 == CONVERGED>(無 FROZEN、無 PENDING、無 NEEDS_REVISION) AND
            p{last}_consecutive_pass >= config.stop_condition.final_phase_pass_gte AND
            blocking_issues == 0:
             → 輸出「LOOP COMPLETE」後【立即停止輸出並結束本 process】(停機定義見 STEP 10),
               控制權交還外部引擎。
         ⚠️ `stop_condition_met` 只是註記欄,【不是】獨立停止捷徑:引擎只認上面那組客觀條件
            (計數器 + blocking),不會因為它被設成 true 就停(見 utils.py is_done)。
            ❌ 嚴禁:把 `stop_condition_met` 自寫成 true 來跳過計數器/blocking 收工。
         🚨 強制約束:最終停止比照 Phase Gate,【必須】先確認最後 phase「全任務 CONVERGED」。
            ❌ 嚴禁:最後 phase 仍有任何 FROZEN/PENDING/NEEDS_REVISION 任務時就輸出 LOOP COMPLETE
               ——FROZEN 代表未完成的待裁決項,不能靠 p_pass 灌滿混過停止(此縫常配合把 BLOCKING
               Issue 降級成 NON_BLOCKING 一起鑽,見 issues.md)。
         ❌ 嚴禁:輸出 LOOP COMPLETE 後又繼續做任何任務、輸出總結、或自行開下一輪。

STEP 3 ▶ 檢查 Phase Gate(對任意相鄰階段 i→i+1):
         IF current_phase==i AND（phase i 全任務 CONVERGED 且 p{i}_consecutive_pass>=門檻 且 blocking==0）:
             → current_phase=i+1、p{i+1}_consecutive_pass=0、寫日誌「PHASE GATE PASSED i→i+1」。
         🚨 強制約束:「過 gate」本身就是本輪的【唯一動作】。更新 current_phase + 寫日誌後,
            直接跳到 STEP 9→C→10 收尾並停機結束本輪。
         ❌ 嚴禁:同一輪內既過 gate、又進新階段挑任務開始做。新階段第一個任務一律留給
            「下一輪」(由外部引擎重新喚醒的另一個全新 process)。

STEP 4 ▶ 看 current_phase 對應的狀態表,依「收斂規則」挑出【唯一一個】本輪任務:
         🚨 強制約束:每次被喚醒,你只能且僅能挑選並處理【單一一個】任務。
            「可做」的機械定義 = 非 CONVERGED、非 FROZEN,且該任務宣告的 depends_on / 上游任務
            全部已 CONVERGED。取狀態表中「由上而下第一個可做」的任務即為本輪任務,
            一旦挑到就【立刻停止挑選】,不再往下看其他任務。
         🚨 強制約束(硬性挑選順序,不准亂跳):挑選由「狀態表列序」+「depends_on 依賴」二者鎖死,
            執行 agent 沒有裁量空間——
            (a) 表序固定:狀態表的任務列順序在 plan 期(②階段)定案,執行期【不得重排、插隊、搬移】。
                你只能按既有列序由上而下掃。
            (b) 照表序掃,跳過所有「不可做」者(CONVERGED / FROZEN / depends_on 未全 CONVERGED),
                取第一個「可做」者即本輪任務,不准回頭。前面有任務因依賴未就緒而被跳過是正常的。
          ❌ 嚴禁:在同一輪內合併處理多個任務、批次把多個 TODO 一次做完、
             或「順手」把第二個任務也推進。即使你判斷它們很簡單、很快、能一起做完——也不行。
          ❌ 嚴禁:上游/依賴任務尚未 CONVERGED 時,把下游任務解讀成「可做」並提前推進;
             若狀態表排序與依賴關係衝突,依 depends_on 從嚴,跳過該下游並開 Issue 修正狀態表。
          ❌ 嚴禁(防挑軟柿子):為了避開難任務,自行重排狀態表列序、把難任務往後搬、跳過表序在前的
             可做任務去挑後面「看起來更好做」的、或謊報某任務 depends_on 未就緒。列序與依賴是 plan 期
             定案的硬約束,執行期動到它即屬破壞性改動(會被 git-review-gate REVERT,見其 §2)。
           · status==TODO            → 本輪做「初稿」(第一次分析/實作)
           · status==DRAFTED 且 conv<門檻 → 本輪做「獨立重驗」(見 convergence.md)
           · status==NEEDS_REVISION  → 本輪先修正,修正後視為重新 DRAFTED【且 conv 立即歸零】
                                       (必須重新累積收斂,❌ 嚴禁沿用舊計數少跑重驗)
           · status==FROZEN          → 跳過(規格衝突凍結,待人類解凍,見 oscillation-escalation.md)
         若剩下任務全部 CONVERGED(無任何 FROZEN) → 本輪是「驗證模式」(跑該 phase 全量驗證)。
            驗證模式仍是【單一動作】:只跑一次全量驗證並回填結果即收尾,
            ❌ 嚴禁驗證後又順手推進任何任務。
            🚨 強制約束(FROZEN 存在時禁止用驗證刷分遮蔽卡死):current_phase 只要還有【任一個】
               FROZEN 任務,該 phase 永遠過不了 Gate / 停止條件(STEP 2、3 都要求無 FROZEN)。
               此時【嚴禁進入驗證模式、嚴禁 `p{i}_consecutive_pass += 1`】——本輪唯一合法動作是依
               oscillation-escalation.md 確認該卡死是否該升級或設 human_required。
               ❌ 嚴禁:在帶 FROZEN 的 phase 上一輪一輪跑全量驗證刷 PASS,把 last_round_result 標 PASS、
               重置 rounds_since_progress,藉此遮蔽「有未解凍互卡任務」的卡死、騙過外部震盪偵測。
            🚨 計數器防灌水(記錄標準對齊 convergence.md step 5,全量驗證直接驅動 LOOP COMPLETE,
               驗證紀錄不得比單任務重驗鬆):`p{i}_consecutive_pass += 1` 之前,【必須】把本輪驗證結果
               寫成可稽核的「驗證證據檔」(如 <outputs>/.validate/p{i}-R###.md),內容須:
                 · 對照「分母清單」逐項列出本輪重核的項目(每項附 檔:行),各標 PASS/FAIL;
                 · 有 build/test/編譯器把關的任務 → 貼出該輪實際執行的原始輸出(不可只寫「全綠」)。
            ❌ 嚴禁:只寫一句「全部 PASS」或自撰無法被抽查的清單就自增計數器。
            ❌ 嚴禁:無驗證證據檔的那一輪 +1;任一項「無法 100% 確定 PASS」一律記 FAIL(從嚴)。

STEP 5 ▶ 依 current_phase 開「對應的那一個 phase 檔」(config.phases[i].spec),
         只讀「本輪任務那一節」(或驗證模式讀驗證清單)。不要整檔讀完。(context-budget.md)

STEP 6 ▶ 依該任務宣告的「依賴讀取」,只讀需要的那幾個輸入/產出檔的那幾行(大檔分段讀)。
         ❌ 嚴禁「為了保險把整個 outputs 讀一遍」——完整性靠列舉清單+行覆蓋,不靠全讀。

STEP 7 ▶ 執行「STEP 4 挑定的那【唯一一個】任務」/ 該輪那一次驗證(不得在此擴張為多個任務)。
         ✍️ 寫檔守則(防變白,見 git-safety.md):局部編輯優先、寫完讀回確認、
            寫壞且未 commit → git checkout -- <檔> 還原後重做。
         ✅ 寫入只允許落在「本專案可寫範圍」(.loop/ 與工作區);❌ 禁止寫 framework_path 下任何路徑。

STEP 8 ▶ 產出落地到 config.phases[current_phase].output。
         發現前人或前階段規格錯誤 → 修改該檔 + 寫「修正記錄」(issues.md)。

STEP 9 ▶ 更新狀態。狀態唯一的單一事實來源為 state.json，**嚴禁手動編輯任何舊版 Markdown 控制檔或直接修改 state.json 本體**。
         你必須一律呼叫系統提供的 `{state_cli}` 工具更新狀態（完整命令操作指引與範例請務必閱讀並依據 .loop/rules/state-cli-guide.md 執行），例如：
           · 推進模式下任務狀態變更：呼叫 `{state_cli} task-status --phase <phase> --task <task> --to DRAFTED` 
           · 任務收斂增加計數：呼叫 `{state_cli} task-conv --phase <phase> --task <task> --incr`
           · 任務完成標記為 CONVERGED（前題是 conv 達門檻）：呼叫 `{state_cli} task-status --phase <phase> --task <task> --to CONVERGED`
           · 重置任務收斂計數：呼叫 `{state_cli} task-conv --phase <phase> --task <task> --reset`
           · 遭遇退回修正：呼叫 `{state_cli} task-status --phase <phase> --task <task> --to NEEDS_REVISION`
         ⚠️ 務必回填三個「震盪偵測」欄位（引擎決策關鍵）：
           · `{state_cli} set control.last_round_mode <推進|驗證>`
           · `{state_cli} set control.last_round_result <PASS|FAIL|NA>`
           · `{state_cli} set control.last_round_fail_tasks "<以逗號分隔的任務ID>"`（PASS 留空）
         🚨 留證鐵則(不只信自評,對齊 git-review-gate.md §2-11「驗收證據缺失」):
            本輪若把 last_round_result 標 PASS,且該任務是「可驗證的」(有 build/test/編譯器把關)——
            commit 內【必須】含本輪實際跑的驗收指令與其原始輸出(或 STEP 4 那種證據檔),
            ❌ 嚴禁只寫一句「全部 PASS / 全綠」。無證據的 PASS 會被獨立審查輪 REVERT(視為假推進)。
         若本輪因震盪被升級到人類(stuck_level=2):依 oscillation-escalation.md 開 BLOCKING Issue、
            把互卡任務改 FROZEN（使用 `{state_cli} task-status --phase <phase> --task <task> --to FROZEN`）;
            若已無其他可做任務則設 `{state_cli} set control.human_required true`。
         每次呼叫 CLI 修改後，狀態會被安全原子寫入 state.json，人類可以使用 Web Dashboard 查看最新狀態看板。



STEP C ▶ 【Git 提交 — 本輪的還原點】(只在工作區 / code repo)
         git add -A   (掃不到外部 framework,天然不會混入)
         git commit -m "R### | phase{n} | TASK-## | 推進/驗證 | <一句摘要>"
         一輪一 commit,此 commit 即「下一輪」STEP G 的還原基準
         (注意:下一輪是外部引擎重新喚醒的【另一個全新無狀態 process】,不是你接著跑)。

STEP 10 ▶ 把本輪詳細日誌 append 到 loop.log(人看,agent 不回讀);
          若保留人類摘要視圖，也只能更新最近一筆摘要，不能把它當成機器判讀來源。
          ┌──────────────────────────────────────────────────────────┐
          │ 🚨 強制停機（本輪終點，物理動作，不可省略）:               │
          │ 完成 STEP C 的 commit 後,必須【立即停止輸出並中斷本次對話   │
          │ / 結束本 process】(Stop Generation / Exit)。               │
          │ 控制權即刻交還外部引擎(loop.py);是否要跑下一輪、由它重新     │
          │ 喚醒【另一個全新、無狀態的】agent process 決定,不是你。     │
          │ ❌ 嚴禁:自行開始下一輪、回到 STEP G/0 再跑一遍、預測或代跑   │
          │   後續輪次、輸出多餘的收尾總結或客套話。                    │
          │ 你只是「外部迴圈呼叫一次的函式」,做完這一次就必須 return。   │
          └──────────────────────────────────────────────────────────┘
══════════════════════════════════════════════════════
```

**Context 管理鐵則(見 context-budget.md)**:每輪固定只全讀 `state.json` + 當輪 phase 那一節 + 當輪用到的那一份 rules + 任務宣告的少數依賴檔。其餘一律不載入。
