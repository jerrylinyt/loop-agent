# 🏁 FINAL ACCEPTANCE — Refactor 全系列收官驗收

> **這份文件是什麼**：docs/refactor 1–5 與 dashboard/refactor 1–4 **全部合併後**執行的最終驗收計畫。
> **為什麼需要它**：各計畫書的驗收只證明「該包在隔離下正確」；本檔驗的是三件只有最後才能驗的事——
> **(1) 跨計畫整合**（功能兩兩組合的縫）、**(2) 當初承諾的量化指標**（docs/review §8）、**(3) 誠實的缺口清點**（哪邊沒做好、哪些債要記下來）。
> **執行者**：coding agent 跑機械部分＋人類做最終簽核。**產出**：一份 as-built 驗收報告落 `docs/review/`，缺口分流進 backlog/roadmap。
> **前置**：九本計畫書全部合併、CI 綠、ROUTING.md §C 增補帳表面上已消帳（本檔會重驗）。

---

## A. 帳務重驗（不信任「當時打過勾」）

各計畫書的最終驗收清單是合併當下打的勾；後續計畫可能把前面的行為改壞（例：計畫書 4 重寫 prompts 後，計畫書 1 的 preflight 煙霧還綠嗎？）。**全部重跑一次**：

- [ ] A1. 九本計畫書的「最終驗收清單」在**最終 HEAD** 上逐條重跑（機械項直接跑、演練項重演），逐條記 PASS/FAIL/N.A.（含理由）。
- [ ] A2. ROUTING.md §C 增補帳逐筆核對實作痕跡（L1 任務卡落檔、L2 registry owner、L3 rounds 欄位、L5 prompt 引用、L6 L1 上下文）——不是「計畫書寫了」，是「程式碼裡有」。
- [ ] A3. 全 repo 掃描：`grep -rn "TODO\|FIXME\|XXX" engine/ cli.py dashboard/`（排除測試 fixture）逐筆分類：本系列引入的 → 修掉或入 D 缺口清單；歷史遺留 → 記錄。
- [ ] A4. 死設定掃描：config DEFAULTS 每個鍵在 engine/dashboard 至少一個非測試引用（防再出 `journal_in_control_keep` 型死鍵）——寫成一次性腳本跑。
- [ ] A5. 文件引用掃描：CI 參照完整性測試綠之外，人工抽查 README／engine/README／bootstrap／checklist／errors.md 的指令範例**每條實際執行一次**（文件裡的指令打不動是新同事的第一個坑）。

## B. 跨計畫整合情境（各包單測不到的縫）

每個情境是一次真實執行（fake agent 或便宜真模型），FAIL → 開修復項、修完重跑本情境：

- [ ] B1. **完整 overnight 演練（主劇本）**：全新 repo → `loop init --profile` → confirm-requirements → plan → approve-plan → doctor → smoke → run（branch 模式）。運行中**依序注入故障**：(a) 撤掉 CLI 憑證 → 3 輪內 `cli_failing` 停機＋通知＋RUN_REPORT；(b) 恢復後 `resume --note` → note 出現在下一輪任務卡；(c) 觸發一次 REVERT → 下一輪 FIX 卡帶被退原因；(d) 逼出一次升級（連續同指紋）→ 快升生效；(e) 設 `max_wall_seconds` 到期 → 優雅收工。全程 dashboard 開著：每個狀態轉換在 30s 內反映於總覽卡。
- [ ] B2. **branch 模式 × 並行 worktree**：兩個 worktree 各自 run_branch，registry/總覽正確區分、互不污染 base branch。
- [ ] B3. **state 壓實 × dashboard 快取**：run 中觸發 compaction → dashboard 的 state/plan 視圖在 mtime 失效後正確重載（不殘留壓實前資料）。
- [ ] B4. **靜音時段 × 致命通知 × dead man's switch**：quiet hours 內製造 (a) complete（應入佇列不發）與 (b) disk_low（應即發）；同時心跳假 server 驗證整段期間 ping 不中斷。
- [ ] B5. **框架漂移 × 執行中 run**：run 進行中框架 clone 加 commit → 當前 run 不受影響；下次啟動被擋 → `upgrade-ack` 放行。
- [ ] B6. **reset 全家 × v3 schema**：reset-plan / reset-execute（含 --reset-to-task）在 v3 state 上行為正確（欄位齊、dashboard 顯示一致、rounds 歸因不錯亂）。
- [ ] B7. **INDEX/REPO_MAP 預算聯動**：構造超長 INDEX（>150 行）＋ embed 模式 REPO_MAP → 任務卡降級策略生效且總量不破 `task_card_max_bytes`。
- [ ] B8. **dashboard 操作 × 引擎守衛**：dashboard 連按兩次 resume／run 期間改 config／read-only 模式 POST——三者都被正確擋下且 audit 有記錄。

## C. 量化指標驗收（對 docs/review §8 的承諾結帳）

用計畫書 4 收尾的「真實 LLM 對照演練」數據（v2 對照組 vs v3）填表；**未達標不是擋合併（已合併），是強制進 D 缺口清單並附差距分析**：

| 指標 | 承諾 | 實測 | 判定 |
|------|------|------|------|
| 每輪平均 prompt bytes | −40% 以上 | ｜ | ｜ |
| `command` 任務平均收斂輪數 | ≤ 2 | ｜ | ｜ |
| Review LLM 呼叫次數 | −50% 以上 | ｜ | ｜ |
| 機械類 REVERT 由 L0 攔截率 | 100% | ｜ | ｜ |
| agent 每輪固定必讀 | ≤ 50 行 | ｜ | ｜ |
| 「一分鐘根因路徑」點擊數（dashboard 3） | ≤ 6 | ｜ | ｜ |
| overnight 演練（B1）無人工介入完走 | 是 | ｜ | ｜ |

## D. 缺口清點（「哪邊沒做好」的正式產出）

- [ ] D1. 彙整 A/B/C 全部 FAIL 與未達標項，逐項分流三類（**每項必須落一類，不准懸空**）：
  - **修**：開修復任務（列清單、指派、修完回頭重跑對應驗收項）；
  - **降級接受**：寫明風險與理由，**人類簽名**（agent 不得自行降級——授權紅線）；
  - **入 backlog**：移到 roadmap 對應 Horizon 或新開 backlog 檔，附觸發重啟的條件。
- [ ] D2. 已知設計債登記：各計畫書內文標注「首版保守／未來再議」的決策（如並行首版只開 command 型、P3 遷移驗證的人審負擔、ETA 未校正期）集中列表——這些不是 bug，但下一個接手的人必須知道。
- [ ] D3. 防疲勞記錄：驗收過程中被人類駁回的修改建議記錄駁回理由（沿用 maintenance proposals 慣例，避免未來 agent 重複提案）。

## E. 文件收斂與發佈

- [ ] E1. ROUTING §A/§B 畢業為 `docs/architecture/routing.md`（依 as-built 校正）；原檔標 superseded。
- [ ] E2. README／engine/README／bootstrap／checklist 終審：與 as-built 一致、以 `loop` CLI 為主入口、無舊入口殘留為主指引。
- [ ] E3. `docs/errors.md` 覆蓋測試綠 ＋ 人工抽讀三節可照做。
- [ ] E4. 打 tag（如 `v3.0.0`）＋ CHANGELOG（面向使用框架的專案：什麼變了、要重 init、profile 怎麼填）。
- [ ] E5. **驗收報告**落 `docs/review/<date>-refactor-acceptance.md`：A–E 各節結果、C 指標表、D 缺口三類清單、簽核記錄——與當初的體檢報告（2026-07-02-framework-review.md）首尾呼應，形成完整證據鏈。

## F. 人類最終簽核（gate，不可省）

- [ ] F1. 人類讀 E5 報告，對 D1 的「降級接受」逐項簽名、對 backlog 分流點頭。
- [ ] F2. 簽核後宣告 refactor 系列關閉；此後的改進走 maintenance 迴圈與 roadmap，不再回填本系列計畫書。

---

> **執行提示**：本檔適合排成 2–3 天的收官衝刺：Day 1 = A 帳務＋B 機械情境；Day 2 = B1 主劇本＋C 指標演練；Day 3 = D/E/F 收斂簽核。B1 建議用最便宜的真模型跑（fake agent 驗不出 prompt 品質問題）。
