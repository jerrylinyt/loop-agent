# 📐 RULE — BOOT SEQUENCE（通用開機程序）

> **唯讀框架規則**。本檔技術中立、不綁語言/框架/階段數。具體的階段、產出位置、停止門檻一律「**依 `loop.config.yaml`**」。
> 每個 agent 被觸發時的**第一件事**就是執行這段。順序不可跳。
> 相關規則:`git-safety.md`、`state-model.md`(計數器/流程)、`context-budget.md`(讀取預算)、`convergence.md`、`completeness.md`、`oscillation-escalation.md`、`issues.md`。

```
══════════════════════════════════════════════════════
 BOOT SEQUENCE
══════════════════════════════════════════════════════

STEP 0 ▶ 只讀「本專案 CONTROL.md」全文 + 本輪需要的「framework rules」那幾份。
         必讀:CONTROL.md、本檔 boot-sequence.md。
         按需讀:當輪用到的協定(做收斂讀 convergence.md / 大範圍讀 completeness.md…)。
         ❌ 不要一次載入全部 rules、不要先讀 phase 檔/輸入/產出(還不知道要哪些)。(見 context-budget.md)

STEP 1 ▶ 讀 CONTROL「變數與計數器」,取得 current_phase 與計數器(定義見 state-model.md)。

STEP 2 ▶ 檢查停止條件(依 config.stop_condition):
         IF current_phase==<config.phases 最後一筆> AND
            <最後一筆 phase 全任務 == CONVERGED>(無 FROZEN、無 PENDING、無 NEEDS_REVISION) AND
            p{last}_consecutive_pass >= config.stop_condition.final_phase_pass_gte AND
            blocking_issues == 0:
             → 輸出「LOOP COMPLETE」後【立即停止輸出並結束本 process】(停機定義見 STEP 10),
               控制權交還外部引擎。
         IF stop_condition_met==true → 同樣輸出「LOOP COMPLETE」並【立即停止輸出、結束 process】。
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
            取狀態表中「由上而下第一個可做(非 CONVERGED、非 FROZEN)」的任務即為本輪任務,
            一旦挑到就【立刻停止挑選】,不再往下看其他任務。
         ❌ 嚴禁:在同一輪內合併處理多個任務、批次把多個 TODO 一次做完、
            或「順手」把第二個任務也推進。即使你判斷它們很簡單、很快、能一起做完——也不行。
           · status==TODO            → 本輪做「初稿」(第一次分析/實作)
           · status==DRAFTED 且 conv<門檻 → 本輪做「獨立重驗」(見 convergence.md)
           · status==NEEDS_REVISION  → 本輪先修正,修正後視為重新 DRAFTED【且 conv 立即歸零】
                                       (必須重新累積收斂,❌ 嚴禁沿用舊計數少跑重驗)
           · status==FROZEN          → 跳過(規格衝突凍結,待人類解凍,見 oscillation-escalation.md)
         若剩下任務都 CONVERGED 或 FROZEN → 本輪是「驗證模式」(跑該 phase 全量驗證)。
            驗證模式仍是【單一動作】:只跑一次全量驗證並回填結果即收尾,
            ❌ 嚴禁驗證後又順手推進任何任務。
            🚨 計數器防灌水(留痕標準對齊 convergence.md step 5,全量驗證直接驅動 LOOP COMPLETE,
               留痕不得比單任務重驗鬆):`p{i}_consecutive_pass += 1` 之前,【必須】把本輪驗證結果
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

STEP 9 ▶ 回 CONTROL 更新:對應狀態表、覆蓋率/統計、Issue 索引、計數器。
         ⚠️ 務必回填三個「震盪偵測」欄位(外部 loop 靠它判斷卡死):
            last_round_mode(推進/驗證)、last_round_result(PASS/FAIL/NA)、
            last_round_fail_tasks(驗證失敗被打回的任務,逗號分隔,PASS 留空)。
         若本輪因震盪被升級到人類(stuck_level=2):依 oscillation-escalation.md 開 BLOCKING Issue、
            把互卡任務改 FROZEN;若已無其他可做任務則設 human_required=true。
         📌 CONTROL 要保持「決策最小集」:執行日誌只留最近 1~2 筆,其餘只進 loop.log(context-budget.md)。

STEP C ▶ 【Git 提交 — 本輪的還原點】(只在工作區 / code repo)
         git add -A   (掃不到外部 framework,天然不會混入)
         git commit -m "R### | phase{n} | TASK-## | 推進/驗證 | <一句摘要>"
         一輪一 commit,此 commit 即「下一輪」STEP G 的還原基準
         (注意:下一輪是外部引擎重新喚醒的【另一個全新無狀態 process】,不是你接著跑)。

STEP 10 ▶ 把本輪詳細日誌 append 到 loop.log(人看,agent 不回讀);
          CONTROL 內只更新最近一筆摘要。
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

**Context 管理鐵則(見 context-budget.md)**:每輪固定只全讀 CONTROL + 當輪 phase 那一節 + 當輪用到的那一份 rules + 任務宣告的少數依賴檔。其餘一律不載入。
