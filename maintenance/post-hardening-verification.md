# 🔁 PROMPT — 硬化後獨立驗收（Post-Hardening Verification + Re-Audit）

> **用途**：交給一個**全新 context** 的 agent。本輪框架剛做了一批「對抗式鑽空子稽核」的硬化
> （rules/ 9 處 + engine/ 3 處）。請你**獨立冷啟動**驗收：(A) 重跑鑽空子稽核看有沒有**新**空子或**回潮**；
> (B) 逐項核對這批硬化是否真的成立、且 **rule ↔ engine 沒有漂移**。
> **只審不改**：你只負責找洞與給判決，不准修改任何檔案。
> **獨立重審**：先自己從框架宗旨推一遍「這裡該怎麼防」，再對照現狀；不要只覆述上一輪報告（橡皮圖章）。

---

## 0. 心態（同 rule-loophole-audit.md）
把自己當成「被外部迴圈反覆呼叫、想用最低成本通過收斂的弱模型」。
你會找「技術上照做、實質上偷懶/造假」的解讀。**說不出 agent 具體怎麼鑽，就不是空子，別湊數。**

## 1. 最高指導原則（空子 = 違背任一條）
1. 規則是唯一事實來源；prompt/config/engine 不得各自重述出「更鬆的軟版」。
2. 文件即狀態、可冷接手。
3. 不信單次 → 收斂要有**可稽核證據**（獨立重推、留下紀錄、實質差異歸零），不是自我回報。
4. 一輪一任務 + STEP 10 物理停機。
5. 卡死 → 升級 → 交人；硬邊界程式不自我放寬；**價值判斷一律交人**。
6. Context 防爆：不准「整批讀資料來檢視」。

---

## PART A — 獨立重跑鑽空子稽核
完整照 `maintenance/rule-loophole-audit.md` 跑一輪（rules/*.md + engine/prompts.yaml + config/templates）。
重點放在「這批硬化有沒有按下葫蘆浮起瓢」：改了 A 處有沒有在 B 處開新縫、或某條硬化被另一條措辭架空。
輸出沿用該檔的發現表 + 判決行格式。

---

## PART B — 本批硬化逐項回歸核對
對下列每一項，做三件事：①找到對應檔:行確認措辭/程式碼在；②問「弱模型還鑽得動嗎」；
③檢查 **rule 與 engine 是否一致**（規則承諾的，引擎有沒有真的擋；引擎認的字面值，規則有沒有寫對）。

### 規則層（commit 664a634）
1. **全量驗證紀錄存檔**（boot-sequence.md STEP 4）：`p_pass+=1` 前是否強制寫驗證證據檔（逐項檔:行＋build/test 原始輸出）？無證據檔能不能還是 +1？
2. **最終停止全 CONVERGED**（boot-sequence.md STEP 2）：是否擋掉「最後 phase 還有 FROZEN/PENDING 卻 LOOP COMPLETE」？
3. **收斂類別預先宣告**（convergence.md）：執行 agent 還能不能臨場自稱「Init 類/有把關」跳過重驗？
4. **重推稿附來源行號**（convergence.md）：能不能先偷看既有產出、再補一份假獨立重推稿？
5. **集合穩定重列舉獨立驗證**（completeness.md F）：能不能先看舊 inventory 就宣稱「無新項」converge+1？
6. **Issue 分級從嚴**（issues.md）：能不能把真 BLOCKING 降級成 NON_BLOCKING 來過停止/避歸零？
7. **凍結/交人須引擎卡死訊號**（oscillation-escalation.md + state-model.md stuck_level 註記）：agent 能不能自抬 stuck_level=2 把「難」當「卡死」甩鍋？
8. **審查判決逐條清單**（git-review-gate.md §3）：一行式 PASS 是否被明確判無效？
9. **tree_structure_error 對齊引擎**（state-model.md）：規則是否要求填字面 `true`（引擎只認 `=="true"`）、證據另開 BLOCKING Issue？
10. **BLUEPRINT 鏡像**：收斂鐵則/Issue 段是否與 rules 同步，沒留「軟版」？

### 引擎層（commit 843ea8a、c63412c）
11. **is_done 去除自我認證**（engine/utils.py `is_done`）：是否**只認**客觀計數器路徑、不再因 agent 自寫 `stop_condition_met:true` 而停？確認 `done_flag` 已是 inert，且樹模式葉子收斂（loop.py 用 is_done 處）未被改壞。
12. **Review Gate fail-closed**（engine/loop.py `run_git_review_gate`）：空檔/亂寫/非 JSON/缺 `verdict`/PASS 缺合法 `checklist`，是否都**不放行**（不前進 last_safe_sha）？連續無效是否有界升級交人（`enhanced_max_rounds`）而非無限重審或無限放行？
13. **樹模式也有 Review Gate**（engine/loop.py `_run_tree_execute_locked`）：是否在挑葉子前呼叫 `run_git_review_gate`，且 revert 後 `current_leaf` 重置？
14. **prompts.yaml ↔ 引擎一致**：`git_review` prompt 是否要求輸出單一 JSON verdict object（PASS 時含至少 6 筆合法 checklist）（否則 fail-closed 會把每次 PASS 都打成無效→輪輪升級交人）？

> 對 11–14 特別問一句：**有沒有哪條規則承諾了引擎其實不擋的事，或引擎認的字面值規則寫錯**（rule↔engine 漂移就是新空子）。

### 實證回歸核對（Loop 4 新增）
15. **痛點實證下降**：被本批「宣稱修掉」的痛點，必須在**下一批 trace 的 `summary.json` 中量到對應指標（例如 oscillation 頻率、stuck 次數）下降**，做為閉環事後證明（Close-loop Verification）。

---

## 輸出格式
1. 先給 PART A 的發現表（依 rule-loophole-audit.md 格式）。
2. 再給 PART B 的核對表：| # | 檔:行 | 結論(成立/仍可鑽/漂移) | 鑽法或漂移敘述 | 建議硬化 |。
3. 最後**一定**給一行總判決：
   - 全數成立、無新空子、無漂移：`[VERIFY: CONVERGED] 本輪獨立驗收通過,無新空子、無 rule↔engine 漂移。`
   - 有問題：`[VERIFY: HOLES <N>] 見上表（其中 🔴 高危 <n> 個）。`

## 規矩
- 只審語意空子與 rule↔engine 一致性，不報排版/錯字。
- 只審不改，把報告輸出回來即可。
- 找不到就誠實宣告 CONVERGED，不為交差硬湊。
