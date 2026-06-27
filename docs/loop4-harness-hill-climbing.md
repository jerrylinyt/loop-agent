# 🧗 Loop 4 規劃書：Trace 驅動的 Harness 爬坡迴圈

> **這份文件是什麼**：把框架從「Loop 1（執行）+ Loop 2（驗證）」往上補一層 **Loop 4（自我改進）** 的工作說明書。
> 給**框架維護 agent / 人類維護者**看（動的是本框架 repo 的 `engine/` `maintenance/` `rules/`，**不是**任何下游 code repo）。
>
> **一句話**：把多個真實專案跑出來的逐輪 trace 收集起來，由一個分析 agent 找出「**跨專案重複出現的同型痛點**」，
> 對應到該硬化的 harness 元件（rule / prompt / config 門檻），**產出帶證據的修改提案（PR 形式）→ 人類 review 才合併**。
> 框架因此每收一批 trace 就硬一點，而**人類永遠握著合併那一刀**。

---

## 0. 定位：這是 Loop 4，且和現有 `maintenance/` 是互補不是取代

文章把四層迴圈定義為：Loop 1 讓工作被完成、Loop 2 確保品質、Loop 3 自動化觸發、**Loop 4 自動化「改進」本身**。
本框架在 1、2 已經很深（一輪一任務 + 三層收斂 + 獨立 Gate），Loop 4 的零件也散落各處，**缺的是把它們接成閉環**。

| 既有資產 | 在 Loop 4 裡的角色 | 缺口 |
|---|---|---|
| `rounds.jsonl`（[engine-rounds-history.md](engine-rounds-history.md)） | **trace 來源**（每輪結構化紀錄） | ⚠️ **尚未實作**，本規劃 Phase 0 先補 |
| `fail_history` / `progress`（[engine/state.py](../engine/state.py)） | 震盪指紋、進度簽章——痛點的原始訊號 | 只服務「單次執行內」，未被跨執行彙整 |
| `~/.loop/index.md`（跨專案總覽） | **收集器的入口**：列出機器上每個 repo+workspace | 未被任何分析消費 |
| `maintenance/rule-loophole-audit.md` | **想像驅動**的對抗式稽核（弱模型「會怎麼鑽」） | 不看真實數據，可能硬化沒人踩到的洞、漏掉天天踩的洞 |
| `maintenance/post-hardening-verification.md` | 硬化後的**獨立迴歸驗收** | 直接複用為 Loop 4 的合併後驗證 |

> **核心區隔**：現有稽核是「**想像**弱模型怎麼偷懶」；本規劃補的是「**看實際**哪裡反覆卡」。
> 兩者輸出同一種「建議硬化」格式、餵給同一個人類 gate——trace-driven 提供經驗證據，adversarial 提供想像力，**互為補集**。

---

## 1. 最高指導原則與硬約束（紅線，違背即設計失敗）

🚨 **強制約束**（這層迴圈本身也要守框架自己的原則）：

1. **框架對下游唯讀**：Loop 4 從下游 code repo 的 `.loop/<ws>/.loop_state/` **只讀** trace，**絕不寫**任何下游 repo。
   改的東西只落在**本框架 repo** 的分支上。
2. **Propose-only，人類握合併刀**：分析 agent **只產出提案（diff / PR）**，**絕不自動 merge** 到 `rules/` `prompts.yaml` `config.py`。
   ❌ **嚴禁**：分析 agent 直接改框架檔、或「跑完順手 commit 到主幹」。合併是價值判斷，保留給人類（對映 [BLUEPRINT 原則 9](../rules/BLUEPRINT.md)：一個能自己放寬的邊界不是邊界）。
3. **留證據才算提案**：每條硬化提案**必須附可稽核證據**——來自哪些 run、哪些輪、指紋為何、重複幾次。
   ❌ **嚴禁**：無證據的「我覺得這裡可以更嚴」提案（那是 adversarial 稽核的事，不是 trace-driven 的）。對映收斂鐵則「留下紀錄才算數」。
4. **跨專案重複才升級為 harness 候選**：單一專案的卡死**可能只是該案本質矛盾**（規格衝突），不該拿去改全域 rule。
   只有「**≥ K 個不同 repo/workspace 都出現同型痛點**」才升級成 harness 提案；否則只是該案的人類裁決。
   ❌ **嚴禁**：拿單一專案的痛，去改壞所有專案共用的框架。
5. **痛點 ≠ 規格矛盾**：分析要能區分「**harness 缺陷**（措辭縫、門檻錯、prompt 漂移）」與「**該案兩條需求本質衝突**」。
   後者程式判不出（[BLUEPRINT 原則 9](../rules/BLUEPRINT.md) 授權紅線），只能標示、不得拿來改 rule。
6. **best-effort、不擋路**：收集 / 分析的任何失敗，**絕不影響任何正在跑的下游 loop**（純離線、唯讀、吞例外記 warning）。

---

## 2. 整體資料流（端到端）

```
下游 code repo A ─┐
  .loop/wsX/.loop_state/{rounds.jsonl, fail_history, progress}
下游 code repo B ─┤        ┌─────────────┐     ┌──────────────────┐     ┌───────────────┐
  .loop/wsY/...    ├─(讀)─▶│ ① 收集器      │─▶ │ ② 分析 agent       │─▶ │ ③ 提案產出      │
下游 code repo C ─┘   ▲    │ collect_      │   │ aggregate→歸因→    │   │ proposals/*.md │
                      │    │ traces.py     │   │ 跨專案重複度過濾    │   │ + 草稿 diff    │
        ~/.loop/index.md   │ (純讀,離線)   │   │ (LLM,唯讀,留證據)  │   │ (改框架 repo)  │
        (發現所有 ws)       └─────────────┘    └──────────────────┘     └───────┬───────┘
                                                                                 │
                                                       ╔═════════════════════════▼═══════════╗
                                                       ║ 🧑 人類 gate：review 提案 + diff      ║
                                                       ║   合併？ → merge 到 rules/prompts/cfg ║
                                                       ╚═════════════════════════╤═══════════╝
                                                                                 │ 合併後
                                                       ┌─────────────────────────▼───────────┐
                                                       │ ④ 迴歸驗收(複用 maintenance/         │
                                                       │   post-hardening-verification.md)    │
                                                       │   下一批 trace 進來 → 回到 ①          │
                                                       └──────────────────────────────────────┘
```

**讀圖三重點**：
1. **①收集是純 Python、唯讀、離線**；**②分析是 LLM、唯讀、只產提案**；**③④之間夾一道人類合併 gate**。職責分離。
2. 收集器靠 **`~/.loop/index.md` 發現所有 workspace**，不需手動指定每個 repo 路徑。
3. 這是一個**外層慢迴圈**（週期 = 週/累積 M 個新 run），不是內層的每輪迴圈——它改的是「內層 agent 的設定」，正是 Loop 4 的定義。

---

## 3. Phase 0（前置依賴）：先把 `rounds.jsonl` 落地

🚨 **Loop 4 沒有 trace 就無從爬坡**。本 Phase 完整內容見 [engine-rounds-history.md](engine-rounds-history.md)，此處只列「為了 Loop 4 必須補強的兩點」：

- **每行加 `run_id`（跨重啟唯一鍵）**：原 spec 的 `round` 會隨程序重啟從 1 重來、不可當全域鍵。
  Loop 4 要跨「多次執行」聚合，需要一個穩定鍵。建議在 run 啟動時生成一次 `run_id`（如 `{repo_basename}:{ws}:{啟動 epoch}` 或 uuid4），寫進每行。
- **`plan` 迴圈也要記**：規劃迴圈（plan_loop.py）的卡死/震盪同樣是 harness 痛點來源，`loop_type:"plan"` 別省略。

> Phase 0 是 best-effort 寫檔（寫失敗照常跑），**不改任何控制流程或回傳碼**——維持其低風險定位。

---

## 4. Phase 1：Trace 收集器 `engine/collect_traces.py`（純 Python，唯讀）

**職責**：走訪機器上所有 workspace，把分散的 trace 聚合成一份**離線快照**，供分析 agent 讀。

| 項目 | 設計 |
|---|---|
| 入口 | 解析 `~/.loop/index.md`（可 `--index` 覆蓋）取得所有 `repo + workspace`；逐一定位 `<repo>/.loop/<ws>/.loop_state/` |
| 讀什麼 | 每個 ws 讀 `rounds.jsonl`（全部行）、`fail_history`（震盪指紋環）、`progress`、以及 `CONTROL.md` 的少數計數器快照（blocking issues / FROZEN 數 / 各 phase consecutive_pass / human_required） |
| 產出 | `maintenance/trace-snapshots/<日期>/snapshot.jsonl`（一行一輪、附 `run_id` `repo` `ws`）+ 一份 `summary.json`（見 §5 指標） |
| 紅線 | **只讀不寫下游**；下游缺檔/壞檔/無 `.loop_state` → skip 該 ws 記 warning，不中斷；**絕不寫框架以外的任何地方** |
| 隱私 | trace 只含結構化欄位（phase id / 計數 / 指紋 hash / 模型 tier），**不含原始程式碼或需求內文**——天然適合跨專案聚合 |

> 不引入新相依（純標準庫，沿用 state.py 的讀檔風格）。

---

## 5. Phase 2：分析 agent（LLM，唯讀，只產提案）

分析分兩段：**(A) 機械式聚合（Python 先算指標）** + **(B) LLM 歸因與提案**。先算數、再讓模型解讀，避免模型對著原始 jsonl 腦補。

### 5.1 (A) 機械式聚合 → 痛點指標（Python，放進 `summary.json`）

從 snapshot 跨 run 聚合，每個指標都標**出處 run 清單**（證據）：

| 痛點訊號 | 怎麼算 | 指向的 harness 假設 |
|---|---|---|
| **升級頻率** | `stuck_level≥1` 的輪數 / 總輪數，按 `phase`/`leaf` 分群 | 某類任務反覆卡 → 任務粒度或該 phase 規格 |
| **watchdog 中斷率** | `killed in {timeout,idle}` 比例 | idle 多 → prompt 沒講清「一輪一任務即停」/ context 太大 |
| **震盪指紋熱點** | `fail_history` 中重複出現的指紋，跨 run 計數 | 「改 A 壞 B」型——對應 oscillation / 寫檔守則 |
| **不收斂段** | `progressed=false` 連續長度分布 | 收斂協定或驗證標準不清 |
| **增強無效** | `enhanced_rounds_used` 高但其後仍 `progressed=false` | **候選：規格矛盾**（→ 標示交人，**非** harness） |
| **Review Gate 反覆 FLAG** | （若 trace 含 gate 結果）同一條紅線反覆 FLAG | git-review-gate 規則或寫檔守則 |
| **計數器反覆歸零** | `consecutive_pass` 頻繁掉回 0 | 全量驗證標準/記錄存檔協定 |

### 5.2 (B) LLM 歸因與提案（新 prompt：`maintenance/trace-driven-analysis.md`）

交給**全新 context**的 agent，輸入 = `summary.json`（指標 + 證據）+ 框架現況（`rules/*.md` / `prompts.yaml` / `config.py` DEFAULTS）。要求它：

1. **歸因**：把每個達門檻的痛點，對應到**具體該改的 harness 檔:行**（哪條 rule 措辭縫、哪個 prompt 漂移、哪個 config 門檻）。
2. **跨專案重複度過濾**（🚨 硬約束 §1.4）：只保留「≥ K 個不同 repo/ws 都出現」的痛點為 harness 候選；其餘標 `SINGLE_PROJECT`（該案人類裁決，不改框架）。
3. **痛點分類**（🚨 硬約束 §1.5）：每個候選標 `HARNESS_DEFECT`（可硬化）或 `SPEC_CONFLICT_SUSPECT`（疑規格矛盾，只標示、不提框架改動）。
4. **產提案**：對每個 `HARNESS_DEFECT`，沿用 [rule-loophole-audit.md §5](../maintenance/rule-loophole-audit.md) 的「建議硬化」格式（`🚨 強制約束` + `❌ 嚴禁`），**每條附證據**（出處 run 清單 + 指紋 + 次數）。
5. **只產提案不改檔**：提案寫進 `maintenance/proposals/<日期>-<slug>.md`；附**可選的草稿 diff**（給人類起點，非自動套用）。

> 沿用既有稽核的「**獨立重審**」與「**說不出 agent 具體怎麼鑽/實際怎麼卡，就不算數，別湊數**」鐵則。

### 5.3 與 adversarial 稽核合流

分析 agent 跑完後，**同一道人類 gate** 同時收到兩種來源的提案：trace-driven（本規劃）+ adversarial（現有 `rule-loophole-audit.md`）。
人類在同一個 review 介面決定哪些合併——**經驗證據與想像力在此匯流**。

---

## 6. Phase 3：人類 gate + 合併

🚨 **這是 Loop 4 唯一的寫框架入口，且只能由人類觸發**：

1. 分析 agent 把提案 + 草稿 diff 推到框架 repo 的**一個分支 / PR**（`loop4/<日期>`）。
2. 人類 review：採納哪些、改寫哪些、駁回哪些（駁回理由回寫進該提案檔，供下輪分析避免重複提）。
3. 人類**手動 merge** 採納的 diff 進 `rules/` `prompts.yaml` `config.py`。
4. ❌ **嚴禁**任何自動 merge / 自動 push 主幹的路徑存在於程式裡。

> 對映文章「harness 改動要經過人類 review 才部署」與 [BLUEPRINT 第 9 部](../rules/BLUEPRINT.md) 人類介入點盤點。

---

## 7. Phase 4：合併後迴歸（複用既有資產）

合併後跑 [maintenance/post-hardening-verification.md](../maintenance/post-hardening-verification.md)：獨立冷啟動驗收「這批硬化是否成立、有無 rule↔engine 漂移、有無按下葫蘆浮起瓢」。
**新增一句驗收**：被本批硬化「宣稱修掉」的痛點，要在**下一批 trace** 裡量到下降（閉環的事後證明）——這是 trace-driven 相對 adversarial 的獨有優勢。

---

## 8. 檔案骨架（全部落在本框架 repo）

```
engine/
  collect_traces.py            ← Phase 1：唯讀收集器（純 Python）
maintenance/
  trace-driven-analysis.md     ← Phase 2(B)：分析 agent 的 prompt（新）
  rule-loophole-audit.md       ← 既有：adversarial 稽核（合流到同一 gate）
  post-hardening-verification.md ← 既有：Phase 4 迴歸驗收
  trace-snapshots/<日期>/       ← 收集器產出（snapshot.jsonl + summary.json）
  proposals/<日期>-<slug>.md    ← 分析 agent 產出（帶證據的提案 + 草稿 diff）
docs/
  engine-rounds-history.md     ← Phase 0 前置（rounds.jsonl 規格，需補 run_id）
  loop4-harness-hill-climbing.md ← 本文件
```

> `trace-snapshots/` 與 `proposals/` 是否進版控由維護者決定（建議 proposals 進版控留決策軌跡，snapshots `.gitignore`）。

---

## 9. 外層迴圈的觸發與收斂

- **觸發（Loop 3 味道，但保守）**：手動 / 排程（如每週）/ 累積 M 個新 `run_id` 後。**不做** webhook 即時觸發——這層慢、且每輪都要人類合併，沒必要即時。
- **這層迴圈自己的收斂**：連續 N 次分析「**無新的、跨專案達門檻的 `HARNESS_DEFECT` 候選**」→ 視為「框架對現有 trace 已夠硬」，停。等新 trace 累積再觸發。
- **停止語**：分析 agent 末行輸出 `[LOOP4: CONVERGED]`（無新候選）或 `[LOOP4: PROPOSALS <N>]`（見 proposals/）。

---

## 10. 反模式（本層專屬，踩過/可預期的坑）

| 反模式 | 後果 | 正解 |
|---|---|---|
| 分析 agent 直接改 rules 並 commit | 框架被無人 review 的改動侵蝕 | propose-only + 人類合併 gate（§1.2） |
| 拿單一專案的卡死改全域 rule | 為一個案的本質矛盾，犧牲所有專案 | 跨專案重複度門檻 K（§1.4） |
| 把「規格矛盾」當「harness 缺陷」硬化 | 改了 rule 也修不好，模型繼續繞 | 痛點分類 `SPEC_CONFLICT_SUSPECT` 只標不改（§1.5） |
| 無證據的「感覺可以更嚴」 | 提案灌水、gate 疲勞 | 每條附出處 run + 指紋 + 次數（§1.3） |
| 收集器寫進下游 repo | 違反框架對下游唯讀 | 純讀、產出只落框架 repo（§1.1） |
| 讓模型直接讀整包 jsonl 腦補 | context 爆 + 結論不可稽核 | 先 Python 算指標，模型只讀 summary（§5） |
| 駁回的提案下輪又被提一次 | 人類重複勞動 | 駁回理由回寫提案檔，分析時讀入避免重提（§6.2） |

---

## 11. 開放問題（留給人類拍板）

1. **跨專案重複度門檻 K**：預設取多少？（太低 → 拿單案痛改框架；太高 → 永遠湊不到、Loop 4 形同關閉。建議起步 K=2 並觀察。）
2. **trace 可攜性**：跨機器/多人協作時，trace 要不要集中匯流（如共享目錄）？還是各人本機跑？
3. **proposals 與 adversarial 稽核的優先序**：兩來源衝突時（trace 說鬆一點、稽核說緊一點）誰優先？建議：**安全方向（更嚴）優先，但仍由人類定**。
4. **Phase 0 的 `run_id` 生成策略**：epoch 夠用，還是要 uuid4 防同秒啟動碰撞？
5. **要不要做「重放」級驗證**：合併後重跑某個真實專案來量痛點下降，成本高；先靠「下一批 trace 自然量到」是否足夠？

---

## 12. 建議落地順序（最小可用 → 完整閉環）

1. **Phase 0**：補 `rounds.jsonl`（+`run_id`）——沒有它後面全做不了。先讓真實專案跑出幾批 trace。
2. **Phase 1**：`collect_traces.py` + snapshot/summary——先能「看見」聚合痛點，純 Python 好驗。
3. **Phase 2(A)**：機械式指標——人類先用眼睛讀 summary，驗證「指標真的指向痛點」。
4. **Phase 2(B) + 3**：接上分析 agent 與人類 gate——閉環成形。
5. **Phase 4**：接迴歸驗收 + 下批 trace 的痛點下降量測——閉環的事後證明。

> 每個 Phase 都可獨立交付、獨立有用：做到 Phase 1 你就有了「跨專案痛點儀表板」的資料底；做到 Phase 3 才是完整的 Loop 4。
```
