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
            p{last}_consecutive_pass >= config.stop_condition.final_phase_pass_gte AND
            blocking_issues == 0:
             → 輸出「LOOP COMPLETE」,立即結束。
         IF stop_condition_met==true → 同樣輸出「LOOP COMPLETE」結束。

STEP 3 ▶ 檢查 Phase Gate(對任意相鄰階段 i→i+1):
         IF current_phase==i AND（phase i 全任務 CONVERGED 且 p{i}_consecutive_pass>=門檻 且 blocking==0）:
             → current_phase=i+1、p{i+1}_consecutive_pass=0、寫日誌「PHASE GATE PASSED i→i+1」。

STEP 4 ▶ 看 current_phase 對應的狀態表,依「收斂規則」挑本輪任務:
           · status==TODO            → 本輪做「初稿」(第一次分析/實作)
           · status==DRAFTED 且 conv<門檻 → 本輪做「獨立重驗」(見 convergence.md)
           · status==NEEDS_REVISION  → 本輪先修正,修正後視為重新 DRAFTED
           · status==FROZEN          → 跳過(規格衝突凍結,待人類解凍,見 oscillation-escalation.md)
         若剩下任務都 CONVERGED 或 FROZEN → 本輪是「驗證模式」(跑該 phase 全量驗證)。

STEP 5 ▶ 依 current_phase 開「對應的那一個 phase 檔」(config.phases[i].spec),
         只讀「本輪任務那一節」(或驗證模式讀驗證清單)。不要整檔讀完。(context-budget.md)

STEP 6 ▶ 依該任務宣告的「依賴讀取」,只讀需要的那幾個輸入/產出檔的那幾行(大檔分段讀)。
         ❌ 嚴禁「為了保險把整個 outputs 讀一遍」——完整性靠列舉清單+行覆蓋,不靠全讀。

STEP 7 ▶ 執行任務 / 驗證。
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
         一輪一 commit,此 commit 即下一輪 STEP G 的還原基準。

STEP 10 ▶ 把本輪詳細日誌 append 到 loop.log(人看,agent 不回讀);
          CONTROL 內只更新最近一筆摘要。結束本輪。
══════════════════════════════════════════════════════
```

**Context 管理鐵則(見 context-budget.md)**:每輪固定只全讀 CONTROL + 當輪 phase 那一節 + 當輪用到的那一份 rules + 任務宣告的少數依賴檔。其餘一律不載入。
