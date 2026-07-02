# 🔭 框架演化路線圖（Post-Refactor Roadmap）

> **起點假設**：`docs/refactor/` 計畫書 1–5 全部落地——引擎主導編排（任務卡）、verify 契約、overnight 工作流、context 預算執法、分析與校準迴圈都已存在。
> **本文性質**：願景與方向盤點，**不是實作計畫書**。每項附動機、概念設計、前置條件與風險；要動工時再依 `docs/refactor/` 的格式展開成計畫書。
> **北極星**：從「一個人下班前放一個任務」演化到「**團隊的自主工程平台**——任務排進佇列、夜間並行消化、早上集中裁決」。人的角色從「操作者」升級為「裁決者」，且裁決點永遠明確、可稽核。

---

## 演化全景圖

```
現在（1–5 完成）          Horizon 1（深化單機）        Horizon 2（團隊平台化）      Horizon 3（方法論演化）
─────────────────        ─────────────────────        ────────────────────        ─────────────────────
單 workspace 串行跑   →   H1.1 任務級並行             H2.1 佇列與排程 daemon       H3.1 規格即測試
停機才能問人          →   H1.2 非阻塞提問（問題佇列）  H2.2 CI/容器沙箱執行         H3.2 樹模式回歸（遞迴拆解）
每次從零開始          →   H1.3 跨 run 語意記憶        H2.3 行動端裁決介面          H3.3 Loop 改 Loop（自我演化閉環）
單一 provider         →   H1.4 provider 容錯切換      H2.4 成本治理與配額          H3.4 框架基準測試場
執行期結構凍結        →   H1.5 有界動態重規劃         H2.5 版本化發佈與生態        H3.5 信心分級人審
```

排序原則：**每一項都必須保住框架的三條命根**——(1) 文件即狀態、可冷接手；(2) 授權紅線（價值判斷交人、邊界不自我放寬）；(3) context 預算紀律。任何 feature 若要犧牲其一，寧可不做。

---

# Horizon 1 — 深化單機能力（1~2 季）

## H1.1 任務級並行執行 ★ 效益最大的單項

**動機**：夜間 8 小時是固定資源，串行執行下輪數 × 單輪時長就是硬上限。v3 之後任務有 DAG（depends_on）+ 檔案範圍宣告（output/reads），**引擎已經知道哪些任務互不相干**——沒有理由讓 20 個獨立的 API 移植任務排隊。

**概念設計**：
- orchestrator 的 `select_action` 從「取第一個可做」改為「取最多 N 個**檔案範圍互斥**的可做任務」（互斥判定：output 目錄與 reads 檔案集合兩兩無交集；共用檔任務天然串行——這正是 plan 期「共用契約抽先行任務」原則的機械回報）。
- 每個並行任務在**臨時 worktree** 執行（`git worktree` 機制已有，parallel.py 經驗可沿用），完成後引擎依序 merge 回 run branch；merge 衝突 = 互斥判定失誤 → 該任務作廢重跑並記 trace（餵校準迴圈修互斥規則）。
- state 寫入天然無衝突：v3 下任務狀態由**引擎單線程**推進，agent 只交 report。
- verify check 也可並行（獨立測試檔）。
- config：`runtime.parallel_slots: 1`（預設 1 = 行為不變，漸進採用）。

**前置**：計畫書 4 的 output/reads 宣告品質要夠好（plan gate 已檢查）。
**風險**：API rate limit（並行 = 更快燒 quota，需接 H2.4 配額）；「假獨立」任務（review 報告 §3.10 的老問題）——首版保守：只並行 verify.kind=command 的實作任務。

## H1.2 非阻塞人類提問（問題佇列）

**動機**：現況 `human_required` 是全域剎車——一個任務的規格矛盾會凍結整晚。但 FROZEN 機制其實已經是任務級的，缺的只是「其餘任務繼續跑」的語意與「問題收件匣」。

**概念設計**：
- BLOCKING Issue 分裂出新等級 `QUESTION`：附「具體問題 + 選項」，關聯任務 FROZEN，**loop 不停**，繼續消化其他可做任務。
- 全部剩餘任務都被 QUESTION 卡住時才真正停機（human_required）。
- 早上人打開 `loop questions`（或 dashboard / RUN_REPORT 的「待你裁決」節）批次作答：`loop answer ISSUE-07 --choice B --note "..."` → 解凍 + 答案走 HUMAN_NOTES 通道注入。
- 通知分級：QUESTION 產生 → 低優先通知（不吵醒人）；全面停機 → 高優先。

**紅線對齊**：這不是讓程式代答——是把「等人」從同步改非同步，裁決權還是人的。
**前置**：計畫書 2 的 notify + HUMAN_NOTES；計畫書 4 的 issue 引擎代寫。

## H1.3 跨 run 語意記憶（lessons）

**動機**：校準迴圈（計畫書 5）是**數字記憶**；但「這個 repo 的 build 要先跑 codegen」「這個 legacy 模組的日期欄位其實是字串」這類**語意教訓**每個 run 都重新踩一次。

**概念設計**：
- `.loop/lessons.md`（repo 級，跨 workspace 共享）：條目式，每條 ≤ 3 行、帶標籤（路徑 glob / 任務型）。
- **寫入有 gate**：agent 在 report 裡可以 `--propose-lesson "..."`；引擎收集到 `RUN_REPORT` 的「建議入庫的教訓」節，**人在 accept 時勾選**才真正入庫（防垃圾記憶淹沒 context——記憶庫是最典型的無限增長源，必須人工策展 + 條目數上限）。
- **讀取走任務卡**：build 卡片時依 task 的 reads/output 路徑比對 lessons 標籤，只注入命中的 ≤ 5 條。
- lessons.md 進版控（是團隊資產）。

**風險**：記憶污染（錯誤教訓比沒教訓糟）——所以人審入庫是硬條件，且每條帶來源 run_id 可追溯。

## H1.4 Provider 容錯與備援 profile

**動機**：凌晨兩點 provider 掛掉/限流，現況＝fail-fast 停機通知（計畫書 1）。更好：**自動切備援，早上才告訴你切過**。

**概念設計**：
- config `agent.fallback_profile`：主 profile 連續 fast-fail 達門檻 → 引擎切備援 profile 續跑（模型層對映照舊），記 trace + 降級標記；主 provider 恢復探測（每 N 輪試一次）。
- doctor 同時冒煙主/備 profile。
- RUN_REPORT 明示哪些輪跑在備援上（成本與品質歸因要分開）。

**紅線對齊**：切換是「同能力層的機械替換」，不是放寬任何門檻，程式可自主。

## H1.5 有界動態重規劃

**動機**：執行期發現 plan 有結構性缺漏（缺任務、拆錯），現況一律停機交人（正確但重）。中間態：**引擎偵測結構性訊號 → 排一個「範圍受限的 replan 輪」→ 產出 plan diff → 走非同步核可（H1.2 的問題佇列）**。

**概念設計**：
- 觸發訊號（機械）：同 phase 內 NEEDS_REVISION 反覆指向「缺上游」、agent report 連續提出同型 BLOCKED。
- replan 輪 = plan_loop 的 diff 模式（generators 已有）限定在受影響 phase；產出 `PLAN_DIFF.md` + 新任務進 state 但標 `PENDING_APPROVAL`（不可被挑中）。
- 人核可（`loop approve-plan --diff`）後解鎖。**未核可前新結構不生效**——結構變動的裁決權不下放，只是把「發現問題→擬好方案→等蓋章」流水線化。

---

# Horizon 2 — 團隊平台化（2~4 季）

## H2.1 佇列與排程 daemon（fleet）

**動機**：「下班前放**一個**」→「團隊把**一批**丟進佇列，夜間依優先序與資源消化」。

**概念設計**：
- `loopd`：常駐 daemon，讀 `~/.loop/queue/`（一 job 一 yaml：repo/workspace/優先序/預算/時窗）；依 `parallel_slots`（機器級）與 H2.4 配額調度，逐 job 呼叫既有 run 流程——**引擎本體不改，daemon 是外掛的第四層迴圈**。
- `loop queue add/ls/rm`；團隊 dashboard 聚合各 job 狀態（registry.json 已是地基）。
- 時窗排程：「22:00 起跑、07:00 全部收工」（牆鐘上限已有，daemon 負責啟停）。

**風險**：daemon 是新的單點——crash recovery 必須依然滿足「文件即狀態」：queue 目錄就是狀態，daemon 重啟冷接手。

## H2.2 容器沙箱執行

**動機**：團隊採用後，「agent 拿著我的憑證在我機器上整晚自主跑」的信任問題會成為推廣瓶頸；且 verify check 在髒環境跑結果不可信。

**概念設計**：
- `loop run --sandbox`：在 devcontainer/docker 內執行（repo mount + 框架唯讀 mount + 網路 egress 白名單：僅 model API 與 package registry）；git 憑證用短期 token、只授權 run branch push（或完全不 push，早上人拉）。
- log 出容器前過 secret redaction（pattern 表）。
- CI 整合的自然前置：同一個 image 可跑在 GitHub Actions runner——「在 CI 觸發 loop 修 issue」（issue 打 label → workflow 起 loop → 開 PR）成為可能。

## H2.3 行動端裁決介面

**動機**：早上的裁決（accept / answer QUESTION / approve plan-diff）目前綁終端機。裁決量變大後，「通勤路上用手機清掉裁決佇列」是體驗質變。

**概念設計**：不自建 app——通知走既有 IM（Slack/Telegram bot），訊息附結構化按鈕（Approve / Reject / 選項 A/B），bot 回寫到一個裁決收件目錄，daemon 輪詢執行對應 `loop answer/accept` 指令。裁決記錄照常落檔（可稽核）。
**風險**：裁決通道的鑑別（誰按的）——bot 綁使用者身分，寫入記錄含裁決人。

## H2.4 成本治理與配額

**動機**：多人多 job 並行後，「這個月燒了多少、值不值」從個人感受變成管理需求。

**概念設計**：
- 計量：計畫書 5 已有輪數×時長×tier；補 provider 計價表（profile 內維護單價）→ 估算金額。
- 配額：job/人/團隊三級 `budget`（金額或輪數）；daemon 排程時檢查，超額 job 暫停排隊等隔日或人工加碼。**配額耗盡 = 停，不是降級亂跑**（紅線：預算邊界不自我放寬）。
- 月報：跨 job 聚合（analytics 管道延伸），「每個 CONVERGED 任務平均成本」成為團隊 KPI。

## H2.5 框架版本化發佈與生態

**動機**：`sync_framework_docs` 讓所有專案跟著框架 main 走——團隊規模化後需要「昇級是個決定，不是被動發生」。

**概念設計**：框架打 tag 發版（semver）+ changelog；專案 config 可 pin `framework_version`；`loop upgrade` 顯示 diff 與遷移註記後才升。preset / profile / verify recipe 做成可分享的套件目錄（團隊內 marketplace 雛形）。

---

# Horizon 3 — 方法論演化（研究向，擇機投入）

## H3.1 規格即測試（Spec-as-Test）★ 方法論上的下一個大台階

**動機**：v3 讓「任務級驗收」客觀化了，但「**逐條需求驗收**」（R### 級）仍靠 LLM 對照與人審。終極形態：**plan 期把每條 R### 編譯成可執行的驗收測試**，最終驗收 = 引擎跑 R-test 套件全綠。

**概念設計**：
- REQUIREMENTS 訪談時就要求需求寫成可測形式（Given/When/Then）；plan 期新增「驗收測試先行任務」：為每條 R### 產出 acceptance test（初期允許人審這些測試——**測試本身是規格的投影，值得人花時間看**，比看實作划算）。
- 停止條件升級：`R-test 全綠` 取代「p_pass ≥ 10 次 LLM 全量驗證」——最貴的收斂層被免費的測試取代。
- 做不到可測的需求（「介面要好看」）明確標記 `MANUAL`，進人審清單——誠實劃界，不假裝自動化。

## H3.2 樹模式回歸（遞迴漸進拆解）

**動機**：BLUEPRINT §3.10 的樹模式因複雜度被砍掉，但它針對的問題（任務大到 plan 期一次拆不完）是真的。v3 之後**重做成本大幅下降**：任務卡機制天然支援「DECOMPOSE 動作」的卡片，狀態機加節點型別即可，不再需要當初那套平行的 tree 引擎。

**概念設計**：任務可宣告 `kind: composite` → orchestrator 對它發 DECOMPOSE 卡（產子任務清單，集合穩定收斂）→ 人核可子樹（走 H1.5 的 plan-diff 核可管道）→ 子任務照常執行。breaker 三旋鈕（max_depth/max_leaves/max_leaf_reflow）原設計照搬。
**前置**：H1.5（結構變更核可管道）。先有平模式的成熟數據（計畫書 5），再決定樹值不值得回來。

## H3.3 Loop 改 Loop（自我演化閉環）

**動機**：maintenance 迴圈目前產出「提案 + diff 草稿」，人拍板後**人自己動手改框架**。下一步：**提案核可後，由一個 loop run 在框架 repo 上實作該提案**——框架用自己改自己。

**概念設計**：
- `maintenance/proposals/*.md` 中 `APPROVED` 的提案 → 自動轉成框架 repo 的一個 workspace REQUIREMENTS → 排進佇列（H2.1）→ 產出 PR → **人審 PR 合併**（第二道人 gate，不可省）。
- 框架自己的 verify 契約 = 既有 pytest + H3.4 基準場——改壞自己會被自己的測試攔下。
- 這是吃自己狗糧的終極形態：框架的可用性問題會第一時間被框架團隊自己踩到。

**紅線**：兩道人 gate（提案核可、PR 審查）一道都不能少；框架 repo 的 loop 永遠 gated 模式。

## H3.4 框架基準測試場（Harness Benchmark）

**動機**：H3.3 與所有調參都需要答案：「這次改動讓框架變好還是變壞？」目前只能靠真專案的事後 trace。需要**受控實驗環境**。

**概念設計**：
- `benchmark/` 目錄：5~10 個小型合成任務（迷你遷移、迷你測試補齊、故意埋規格矛盾的卡死劇本、故意的大檔防漏劇本），每個附標準答案判分器。
- `loop benchmark`：對當前框架版本全套跑一遍（用便宜模型），輸出：完成率、總輪數、總成本、卡死劇本是否正確停機交人、防漏劇本的漏抓率。
- 進 CI（每週 + 每次框架 PR）：指標劣化超閾值 → PR 標紅。**框架從此有了自己的回歸測試——不只測程式碼，測「方法論的有效性」**。

## H3.5 信心分級與風險導向人審

**動機**：驗收人力是最貴資源。任務不是等風險的：有 command check 全綠的任務 vs 純 LLM 收斂的主觀分析任務，該花的人審時間差一個量級。

**概念設計**：
- 每個 CONVERGED 任務由引擎打信心分（機械公式：verify 類型權重 + 收斂路徑乾淨度（有無歸零/REVERT/升級）+ L1 抽查結果）。
- RUN_REPORT 的驗收清單按信心升序排——**人從最可疑的看起**；高信心任務折疊為抽樣審。
- 校準：analytics 追蹤「人審推翻率 vs 信心分」的相關性，公式權重據此調（建議制，人核可）。

---

## 決策點與建議路徑

不必全做，關鍵是三個分岔口：

1. **「一個人用」還是「團隊用」？**（決定 H2 投不投）——若同事採用順利（計畫書 2 的成功指標達標），H2.1 佇列 + H2.4 配額是下一步；否則先深化 H1。
2. **任務型偏「可測實作」還是「主觀分析」？**——前者多：優先 H1.1 並行 + H3.1 規格即測試（客觀驗證紅利最大化）；後者多：優先 H1.3 記憶 + H3.5 信心分級（主觀鏈路的品質槓桿）。
3. **框架團隊有多少人力持續投入？**——H3.3/H3.4 是「框架的框架」，回報週期長；至少先做 H3.4 基準場（它同時是所有其他決策的量尺——沒有基準場，後面每個 feature 的「有沒有變好」都是感覺）。

**個人建議的預設路徑**：H1.2（非阻塞提問，小工大效）→ H1.1（並行，時間紅利）→ H3.4（基準場，之後一切有尺）→ H2.1（佇列）→ H3.1（規格即測試）→ 視數據決定其餘。
