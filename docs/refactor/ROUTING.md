# 🧭 ROUTING — Prompt 與產出物路由總表（refactor 執行期工作版）

> **這份文件的身分（兩段式，避免混淆）**：
> 1. **現在（refactor 執行期）**：本檔是**規劃草稿 + 工作帳**——§A/§B 是路由規格的設計稿（依計畫書內容寫成，實作時可能微調）；§C/§D 是只在 refactor 期間有意義的增補帳與 PR 自查。
> 2. **完工後（常駐）**：§A/§B 依**實作後的真實狀態**更新，「畢業」安裝為 `docs/architecture/routing.md`（框架的永久架構文件，此後任何注入/產出物變更都必須同步維護它）；§C/§D 隨 refactor 結束退役，本檔標記 superseded 保留歷史。畢業動作是計畫書 4 收尾的正式工作項。
>
> 本表回答兩個問題：**(A) 每一種被喚醒的 agent，拿到什麼、從哪個通道拿？** **(B) 每一個產出物，誰生產、誰消費、進不進 agent context？**
> **維護規則（兩個時期都適用）**：任何變更 prompt 注入或產出物的 PR，必須同步更新當期的路由文件。表的正確性由 CI「參照完整性測試」機械保證（計畫書 4 M5 第 8 點）——prompt 指向的檔案/錨點不存在即紅。

---

## A. Runtime prompt 路由（引擎喚醒的每一種 agent）

| # | Agent 呼叫 | 注入內容（→ 來源通道） | 規格出處 |
|---|-----------|------------------------|----------|
| 1 | **執行輪（任務卡）** | 任務 id/title/動作類型 → 引擎 select_action；規格散文 → `spec_ref` 錨點擷取自 phases/*.md；依賴讀取 → task.reads；**知識索引** → docs/INDEX.md（>150 行降級為命中過濾）；**repo 地圖** → `.loop/REPO_MAP.md`（pointer 或 embed ≤8KB）；被退原因 → task.revert_history（≤3 筆）；FIX 輪錯誤現場 → check log 尾 50 行；**人類附註** → HUMAN_NOTES.md 最新一則（窗口 N 輪內）；動作指引 → rules 的 `<!-- CARD:… -->` 錨點區；升級提示 → escalation（stuck≥1 時）；收尾三步（report CLI 用法/commit 格式/停機）→ 任務卡固定段。**總量受 task_card_max_bytes 硬上限** | docs#4 M2.2/M2.4/M3、docs#2 T7/T10 |
| 2 | **Git Review L1** | diff --stat 全文 + diff 本文截斷（≤30KB）→ git；state 摘要（≤2KB）+ state.json 的 git diff → 引擎生成；**本輪上下文摘要**（task/action/output 範圍/宣稱推進）→ 引擎組裝；4 項檢查規則 → git-review-gate.md（L1 版） | docs#3 T3、docs#4 M4 |
| 3 | **Plan 生成輪** | REQUIREMENTS.md；`1-plan-generator.md`（含 verify 契約、spec_ref 錨點格式、tier_hint、INDEX 任務要求、acceptance-standards §6 下限）；rules（**重組後檔名**：PHILOSOPHY、context-budget、state-model(v3)、convergence、completeness）；上輪退回原因 → plan.gate_last_reason | prompts.yaml `plan` + docs#4 M5 第 8 點 |
| 4 | **Plan Gate 輪** | 規劃書檔（config/state/phases）；`2-plan-review-gate.md`（含驗收標準抽查項）；acceptance-standards.md | prompts.yaml `plan_gate` + docs#4 M5 |
| 5 | **前期準備（訪談，經 INTERVIEW.md 開工檔）** | `.loop/<ws>/INTERVIEW.md`（init 生成，內含完整開工指示：0-requirements-interview 問題清單、acceptance-standards DoD 模板、REQUIREMENTS 落點、bootstrap 邊界規則）——使用者貼一條指令啟動自己的 agent CLI 去讀它；bootstrap.md 保留為「純 agent 入口」的舊路徑 | docs#2 T2 第 5 點、dashboard#2 T6-b |

**不進任何 agent context 的東西（刻意）**：loop.log/plan.log、rounds.jsonl、state_events.jsonl、RUN_REPORT、PLAN_SUMMARY、ANALYSIS、CONFIG_SUGGESTIONS、errors.md、registry.json、dashboard 一切。人看的與機器記帳的，永不回流 prompt——context 紀律。

## B. 產出物 × 生產者/消費者矩陣

| 產出物 | 生產者 | 人類消費點 | agent/引擎消費點 | 進 agent context？ |
|--------|--------|-----------|------------------|-------------------|
| state.json (v3) | 引擎（agent 僅 report 區經 CLI） | dashboard 全站 | 引擎每輪決策 | **否**（v3 後 agent 只拿任務卡） |
| rounds.jsonl(+輪替) | 引擎 | dashboard 時間軸/洞察、RUN_REPORT、analyze | 引擎尾讀重建震盪史 | 否 |
| state_events.jsonl | state.py | dashboard 單輪「state 變化」區 | — | 否 |
| 任務卡落檔 `.loop_state/cards/R{n}.md` | 引擎 | dashboard 單輪詳情「本輪 prompt」 | 該輪 agent（即 prompt 本體） | 該輪 |
| phases/*.md（錨點格式） | plan 生成輪 | gate#2 review、dashboard 任務抽屜 | 引擎錨點擷取進任務卡 | 僅本任務小節 |
| docs/INDEX.md | plan 的 INDEX 維護任務 | dashboard | 任務卡注入 | 全文/過濾 |
| .loop/REPO_MAP.md（+鏡射 CLAUDE/AGENTS/GEMINI.md） | 引擎機械生成 | init 時人過目 | 任務卡 pointer/embed；支援原生知識檔的 CLI 自動載入 | pointer/embed |
| HUMAN_NOTES.md | 人（resume --note / reject --note / dashboard） | dashboard | 任務卡注入 N 輪 | 窗口內、單則 ≤4KB |
| evidence（.reverify/.enum/.validate）+ checks log | agent / 引擎(RUN_CHECK) | 人抽查、dashboard | 引擎存在性驗證、L1 抽查、FIX 卡尾段 | 僅 FIX 尾段 |
| issues/*.md + state 索引 | 引擎代寫（agent report 提案） | dashboard Issues 籤、RUN_REPORT | 引擎 blocking 計數/FROZEN 判定 | 否（FIX 相關資訊經 revert_history/notes） |
| RUN_REPORT.md | 引擎 finish() | 隔天驗收、通知連結 | — | 否 |
| PLAN_SUMMARY.md | 引擎 plan 收斂時 | gate#2、dashboard | —（estimated_rounds 進 state 供 ETA） | 否 |
| ANALYSIS.md / CONFIG_SUGGESTIONS.md / cross-summary | loop analyze | 人、maintenance 提案管道 | — | 否 |
| loop.config.yaml | init/人/dashboard（三道欄） | dashboard Config 籤 | 引擎每次 run 啟動載入 | 否（門檻值由引擎代入行為） |
| registry.json（+owner） | 引擎 update_index | dashboard fleet | analyze/collect 發現 workspace | 否 |
| docs/errors.md | 框架文件 | 通知/RUN_REPORT 錨點連結 | CI 防漏測試 | 否 |
| INTERVIEW.md | `loop init`（樣板代入） | dashboard 精靈顯示對應啟動指令 | 使用者的 agent CLI 於訪談時讀取 | 僅訪談 session |
| lessons.md（未來 H1.3） | 人審入庫 | dashboard | 任務卡命中注入 ≤5 條 | 命中時 |

## C. 跨計畫增補帳（Amendments Ledger）

散落在各計畫書內文的「需要改到別本計畫書」事項，集中列帳；執行對應計畫書時**必須連本帳一起消**：

| # | 提出處 | 要改的計畫書 | 內容 | 狀態 |
|---|--------|-------------|------|------|
| L1 | dashboard#1 T5/驗收 | docs#4 M2.2 | 任務卡另存 `.loop_state/cards/R{n}.md`（dashboard 單輪詳情的 prompt 來源） | 待納入 docs#4 實作 |
| L2 | dashboard#4 T1 | docs#5 T1 | registry.json schema 增 `owner` 欄位 | 待納入 docs#5 實作 |
| L3 | docs#5 T1 | docs#4 M2.3 | round_finished 補 `task/action/verify_kind/model` 欄位（任務級歸因） | 已寫入兩書，實作時對齊欄位名 |
| L4 | dashboard#2 T3 | —（僅引用） | dashboard 代跑 acceptance-standards §6 機械核對（不改該檔） | 無需動作 |
| L5 | 本表 | docs#4 M5 | plan/plan_gate prompt 檔名引用同步 + CI 參照完整性測試 | 已補進 docs#4 M5 第 8 點 |
| L6 | 本表 | docs#4 M4 | L1 review prompt 帶本輪上下文摘要 | 已補進 docs#4 M4 |
| L7 | dashboard#1 T1 | docs#2 T2 | `loop dashboard` 子命令插槽（參數透傳） | 已補進 docs#2 T2 表 |
| L8 | 收官重審 | docs#1 T13b | loop.py stop_requested 誤標 broken_control_file（B11） | 已補進 docs#1 |
| L9 | dashboard#2 T6-b | docs#2 T2/T3 | init 生成 INTERVIEW.md + 印訪談指令；profile 增 `interactive_cmd` 欄位（dashboard 與 CLI 共用同一組裝函式） | 已補進 docs#2 |

## D. 執行 agent 的自查（每本計畫書收 PR 前）

```
□ 本 PR 有沒有新增/變更任何「注入 prompt 的內容」或「產出物」？有 → 更新本表 A/B。
□ 本 PR 有沒有引用其他計畫書的欄位/檔案？有 → 核對 C 帳（沒列 → 補列）。
□ prompts.yaml / 任務卡 builder / generators 的檔案與錨點引用，CI 參照完整性測試綠。
```
