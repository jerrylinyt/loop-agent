# Feature 14：狀態寫入統一走 CLI ＋ Review Gate 改 JSON 輸出

## Type

Engine + rules + prompts。改變「agent 如何寫狀態」與「review gate 如何輸出判決」的**機制**，不改變執行策略（挑任務、收斂、停止條件一律不動）。

## Goal

1. **所有狀態寫入只走一條確定性路徑**：execute agent 與 review agent **都不得手改 `CONTROL.md` 的狀態欄位**，改為呼叫 `engine/state.py` 的 CLI（`set` / `incr` / `get`）。實際的檔案改動由已驗證的 Python（`set_val`）完成。
2. **Review Gate 只輸出 JSON、每次覆寫**：審查 agent 不再輸出散文式逐條清單 + `[REVIEW: ...]` 字串，改為**覆寫**一個結構化 JSON 判決檔，讓引擎用 `json.loads` 直接解析，移除目前脆弱的字串/正則啟發式判讀。

## Problem

### P1：agent 手改 YAML 狀態常常失敗

目前 `boot-sequence.md` STEP 9 要求 agent「回 CONTROL 更新計數器」，等於要弱模型用 in-place edit 同時做對兩件事：

- 算出新值（counter +1、`PASS`/`FAIL`）——這是它該做的事；
- **逐字元重現要被取代的原文**（含縮排、`# 註解`、相鄰相似行）——這是 edit/字串取代的硬性要求。

弱模型掛在第二步：記錯一個空白、把 `p1_last_result` 跟 `p2_last_result` 搞混、把帶註解的行重寫成不帶註解 → 結果是 **no-op（edit 失敗）或寫出壞掉的 YAML**。這與資料格式（YAML / JSON）無關，失敗發生在「外科手術式文字取代」，不在解析。

引擎自己讀寫 `CONTROL.md` 用的是 `engine/state.py` 的 `get_val` / `set_val`（確定性、單行 regex），本來就不會失敗。**問題只是 agent 沒被允許用同一條路徑，而是被要求手改檔案。**

### P2：Review Gate 判決靠字串/啟發式判讀，脆弱且難維護

目前審查 agent 把「逐條紅線清單（markdown）＋ 最後一行 `[REVIEW: PASS|REVERT|FATAL_STATE]`」覆寫進 `git_review_result`，引擎端（`engine/loop.py: run_git_review_gate`）的判讀方式是：

- 用 `in` 子字串比對 `[REVIEW: REVERT]` / `[REVIEW: FATAL_STATE]` / `[REVIEW: PASS]`；
- 用 `_review_has_checklist()` 的**寬鬆正則啟發式**（數 `PASS`/`FLAG` token ≥ 6）判斷有沒有逐條清單。

問題：

- `[REVIEW: PASS]` 若出現在散文佐證或被換行切斷，子字串比對會誤判；
- 「有幾條清單」靠數 token，真鑽空子的橡皮圖章與合規審查的界線模糊；
- 判決理由要再從文字裡 `split("\n")` 撈那一行，脆弱。

## 設計總則

> **狀態的唯一寫入路徑 = `engine/state.py`。任何 agent（execute / review）都不得手改 `CONTROL.md` 的狀態欄位。**
> agent 只負責「它唯一知道的事」——吐出一筆 `set`/`incr` 指令（execute），或吐出一份 JSON 判決（review）。檔案怎麼被精準改動，交給確定性的 Python。

這把 agent 的任務從「重寫這段 YAML 區塊」縮小成「選對 key 與 value、呼叫一行指令」，**exact-match 的失敗面整個消失**。

---

## Part A：狀態寫入統一走 `state.py` CLI

### A1. 為 `engine/state.py` 加 CLI 入口

在 `state.py` 末端新增 `if __name__ == "__main__":`，提供子指令（控制檔路徑用 `--control` 明確帶入，對齊既有 `get_val(control, key)` 介面）：

```text
python <framework>/engine/state.py get   --control <CONTROL.md> <key>
python <framework>/engine/state.py set   --control <CONTROL.md> <key> <value>
python <framework>/engine/state.py incr  --control <CONTROL.md> <key> [--by 1]
```

- `get`：印出值（沿用 `get_val`）。
- `set`：寫入單一 key（沿用 `set_val`）。
- `incr`：**由程式讀舊值 + delta 算新值再寫回**（預設 `--by 1`）。把「算錯新值」這一面也收掉；對齊框架「一輪一動作」，預設只 +1。

`set` / `incr` 成功印 `OK <key>=<new_value>` 並 `exit 0`；失敗（見 A2）印錯誤到 stderr 並 `exit 1`，讓失敗**可被觀測**，而不是默默寫壞。

### A2. key 白名單 + 型別校驗（防 typo 變死 key）

`set` / `incr` 前先校驗 key 是否在合法集合內。合法集合 = 靜態通用欄位 ∪ 由 `loop.config.yaml.phases` 動態展開的 `p{id}_*`：

- 靜態：`current_phase`、`blocking_issues`、`plan_version`、`framework_ref`、`last_round_mode`、`last_round_result`、`last_round_fail_tasks`、`rounds_since_progress`、`stuck_level`、`current_model_tier`、`enhanced_rounds_used`、`human_required`、`stop_condition_met`、`last_safe_sha`、`review_invalid_streak`，以及樹模式欄位（`tree_*`、`node_*`）。
- 動態：對每個 `phases[].id` 展開 `p{id}_consecutive_pass`、`p{id}_total_validations`、`p{id}_last_result`。

未知 key → 報錯 `exit 1`（不再像 `set_val` 那樣默默把新 key 插進 yaml 區塊）。`incr` 僅允許數值欄位；對非數值 key 用 `incr` → 報錯。型別不符（例如把 `PASS` 寫進 `*_consecutive_pass`）→ 報錯。

> 註：`set_val` 既有的「key 不存在就插進 ```` ```yaml ```` 區塊」行為**保留給引擎內部用**（引擎自己呼叫 `set_val` 時可建欄位）；但**經 CLI 的 agent 寫入只允許白名單內既有 key**，避免弱模型造出無人讀的死 key。

### A3. 原子寫入

`set_val` 目前是 read → 組裝 → `open(w)` 覆寫。改為寫入暫存檔後 `os.replace()` 原子置換，避免極端情況（行程被 watchdog 中斷）留下半寫檔。此改動對引擎與 CLI 兩條呼叫路徑都受惠。

### A4. 範圍界定：YAML scalar vs 狀態表 cell

- **本 feature 的 CLI 覆蓋「YAML scalar 狀態欄位」**（`key: value`，即引擎據以決策的所有計數器）。這是 agent 最常改壞、且引擎唯一會 parse 的部分。
- **Phase 狀態表的 cell**（`| 任務 | Status | Conv |` 這種 markdown 表格）不是 `key: value`，CLI 不在本期覆蓋。狀態表仍由 agent 局部編輯，並由 Review Gate 的「排版/狀態破壞」紅線把關。
  - **後續（Phase 2，非本期）**：可加 `task-status --control <f> --phase <id> --task <id> --status CONVERGED --conv 3/5` 子指令，以確定性方式重寫單一表格列。本期先把高頻、會驅動引擎的 scalar 收掉。

### A5. 讓 agent「無腦照抄」指令（降低弱模型負擔）

不要讓 agent 自己拼路徑。在 prompt 用既有 `str.replace` 佔位符機制，把控制檔路徑**預先代入**，agent 只需填 `<key>`/`<value>`：

- `engine/config.py` 的 `fmt_prompt()` 新增可代入佔位符 `{state_cli}`（解析為 `python <framework>/engine/state.py --control <該專案 CONTROL 路徑>` 的前綴字串）。
- `prompts.yaml` 的 `base`（execute）改寫 STEP 9 對應指引：

  > 回填狀態請用：`{state_cli} set <key> <value>` 或 `{state_cli} incr <key>`。
  > ❌ 嚴禁手動 edit `CONTROL.md` 的 YAML 狀態欄位（會 edit 失敗或寫壞）。狀態表（markdown 表格）仍可局部編輯。

### A6. Review agent 也遵守同一條總則

Review agent 目前**不寫 CONTROL**（`review_invalid_streak`、`last_safe_sha` 由引擎在 `run_git_review_gate` 內用 `set_val` 寫）。本 feature 維持這個分工，並在規則中明文化：

> Review agent 對狀態檔**唯讀**；它唯一的輸出是 Part B 的 JSON 判決檔。若未來任何審查/維護輪需要寫狀態，**一律只能透過 `state.py` CLI**，不得手改 `CONTROL.md`。

如此「**沒有任何 agent 用手改的方式碰狀態**」這條總則在 execute 與 review 兩側都成立。

### A7. 需要改的檔案（Part A）

| 檔案 | 改動 |
|------|------|
| `engine/state.py` | 新增 `__main__` CLI（`get`/`set`/`incr`）、key 白名單校驗、`incr` 由程式算值；`set_val` 改原子寫入 |
| `engine/config.py` | `fmt_prompt()` 新增 `{state_cli}` 佔位符 |
| `engine/prompts.yaml` | `base` 加入「用 CLI 寫狀態、禁手改 YAML」指引 |
| `rules/boot-sequence.md` | STEP 9 改為「呼叫 `state.py` CLI 寫計數器」；明示禁手改 YAML 狀態欄位 |
| `rules/state-model.md` | §4「引擎讀寫 CONTROL 的方式」補一節：agent 端寫入唯一路徑 = CLI |
| `generators/templates/CONTROL.template.md` | 第三段註明「此 YAML 狀態區塊由 CLI 維護，勿手改」 |

---

## Part B：Review Gate 改「只輸出 JSON、每次覆寫」

### B1. 新判決檔格式（JSON）

審查 agent **覆寫**（非 append）`git_review_result`，**只寫一個 JSON 物件**（前後不得有散文）：

```json
{
  "verdict": "PASS",
  "checklist": [
    { "id": 1,  "name": "中斷與殘留防護",        "result": "PASS" },
    { "id": 2,  "name": "排版與狀態檔結構破壞",   "result": "FLAG", "evidence": "CONTROL.md:42 狀態表兩列被合併" },
    { "id": 3,  "name": "不合理狀態進展",         "result": "PASS" },
    { "id": 4,  "name": "中間區段被挖空",         "result": "PASS" },
    { "id": 5,  "name": "思考過程外洩",           "result": "PASS" },
    { "id": 6,  "name": "語意一致性",             "result": "PASS" },
    { "id": 7,  "name": "AI偷懶佔位符",           "result": "PASS" },
    { "id": 8,  "name": "無故刪檔與路徑幻覺",      "result": "PASS" },
    { "id": 9,  "name": "衝突標記與取代錯位",      "result": "PASS" },
    { "id": 10, "name": "基礎語法與格式全毀",      "result": "PASS" },
    { "id": 11, "name": "驗收證據缺失",           "result": "PASS" },
    { "id": 12, "name": "收斂計數防偽",           "result": "PASS" },
    { "id": 13, "name": "產出異動卻沒歸零收斂",    "result": "PASS" },
    { "id": 14, "name": "整合輪越界改葉子",        "result": "PASS" }
  ],
  "reason": ""
}
```

欄位約定：

- `verdict`：**列舉，三選一** `"PASS"` / `"REVERT"` / `"FATAL_STATE"`。
- `checklist`：對應 `git-review-gate.md §2` 的 14 條紅線，**每條一個物件**，`result` ∈ `{"PASS","FLAG"}`；`result=="FLAG"` 時 `evidence` **必填**（檔:行 或片段）。
- `reason`：`verdict` 為 `REVERT`/`FATAL_STATE` 時**必填**（人類可讀原因）；`PASS` 時留空字串。
- 不適用某條紅線的輪次（純分析輪等），該條 `result` 仍標 `"PASS"`（視為未觸線），維持 14 條齊全以利引擎做剛性校驗。

### B2. 引擎解析改寫（`engine/loop.py: run_git_review_gate`）

把目前的字串比對 + `_review_has_checklist` 啟發式換成**結構化解析 + 剛性校驗**：

1. 讀 `result_file` → `json.loads`。
2. **fail-closed 無效判決**（沿用現有 `review_invalid_streak` 有界升級交人邏輯）條件改為任一成立：
   - 檔案不存在 / 非合法 JSON；
   - `verdict` 不在 `{PASS,REVERT,FATAL_STATE}`；
   - `checklist` 不是長度 14 的陣列、或任一項 `result` 不在 `{PASS,FLAG}`；
   - 任一 `result=="FLAG"` 卻缺 `evidence`；
   - `verdict` 為 `REVERT`/`FATAL_STATE` 卻缺 `reason`。
3. 有效判決後依 `verdict` 分流，**後續分支邏輯完全不變**：
   - `FATAL_STATE` → 停機交人（`return False, True`）。
   - `REVERT` → 走既有 `has_human_commits` 檢查 → `git revert`（仍由**引擎**執行，保持確定性還原保證）；`reason` 直接取自 JSON 的 `reason` 欄位（不再 `split("\n")` 撈）。
   - `PASS` → 前進 `last_safe_sha`、清 streak、放行。
4. 刪除 `_review_has_checklist()`（被剛性的 `len==14 且 result 合法` 取代）。

> 退場記錄：`append_round_record` 的 `message` 改用 `reason` 欄位；可額外把 `FLAG` 的條目摘要寫進 trace，方便回放（並回饋進下一輪，見 B4）。

### B3. Prompt 與規則改寫

| 檔案 | 改動 |
|------|------|
| `engine/prompts.yaml` `git_review` | 輸出指示改為「**覆寫** `{result_file}`，只寫一個 JSON 物件（schema 見下），前後不得有任何散文」；附上 B1 的 schema 範例 |
| `rules/git-review-gate.md` §3「輸出格式」 | 由「逐條 markdown 清單 + 最後一行 `[REVIEW: ...]`」改為「輸出 B1 的 JSON」；保留「14 條逐條判定、FLAG 必附證據、判決本身不准橡皮圖章」的實質約束，只換**載體**（散文→JSON 欄位）；保留「寫完即停止、不 commit、不改其他檔」 |
| `rules/git-safety.md` §5 | 文字同步：Review Gate 產出描述由「判決檔」更精確為「JSON 判決檔」 |

> 相容性：判決檔路徑（`state_dir/git_review_result`）與「覆寫語意」不變；改的是**內容格式**。舊的 `[REVIEW: ...]` 字串協定一次性切換到 JSON，無需保留雙解析（單一框架、無外部消費者）。

### B4.（順帶，低成本）把 revert 原因回饋進下一輪

REVERT 的 `reason` 已寫入 `rounds.jsonl`。可在 execute prompt（被 revert 後的下一輪）開頭注入一句「上輪被 Review Gate 退回，原因：<reason>，請先避免重蹈」。這讓「同一產生線學到教訓」——但 **reviewer 仍是獨立 context**，不把 execute / review 角色合併（獨立審查是弱 agent 場景唯一靠得住的第二眼，不可拆）。此項可列為 B 的選配。

---

## 不在本期範圍（避免 scope 膨脹）

- 把扁平 CONTROL 狀態整體改存 JSON：對「扁平 scalar」效益小且犧牲 `CONTROL.md` 的人類可讀性；真正值得 JSON 化的是 `TREE.md` 的結構化節點資料，另案處理。
- 把 Review Gate 的「機械可判紅線」（衝突標記、`<think>` 殘留、0-byte、parse 失敗、counter 單輪 +2、status 跳級）下放成引擎端零-LLM 的 pre-lint：能大幅降低 LLM 審查頻率，但屬獨立優化，另案。
- Phase 狀態表 cell 的 CLI（A4 的 `task-status`）：Phase 2。

## Acceptance Criteria

- [ ] `state.py` CLI：`get`/`set`/`incr` 可用；未知 key、型別不符、對非數值 `incr` 皆 `exit 1` 並印錯誤；`incr` 由程式正確算值。
- [ ] `set_val` 改原子寫入（temp + `os.replace`），引擎既有讀寫行為不回歸。
- [ ] execute prompt / boot-sequence 指示 agent 用 `{state_cli}` 寫狀態並禁手改 YAML；`{state_cli}` 佔位符能正確代入該專案 CONTROL 路徑。
- [ ] Review agent 輸出**單一 JSON 物件**並覆寫判決檔；引擎以 `json.loads` 解析。
- [ ] 引擎剛性校驗生效：缺欄位 / `checklist` 非 14 / `FLAG` 缺 `evidence` / `verdict` 非法 → 判無效，沿用 `review_invalid_streak` 有界升級交人。
- [ ] `REVERT`/`FATAL_STATE`/`PASS` 三條分支與 `has_human_commits`、`git revert`（引擎執行）、`last_safe_sha` 前進邏輯不回歸。
- [ ] `_review_has_checklist` 字串啟發式被移除。

## Tests

- **Unit（state CLI）**：合法 `set`/`incr`/`get`；未知 key 拒絕；`incr` 連續呼叫值正確；型別校驗；原子寫入後檔案結構完整、非空。
- **Unit（review 解析）**：餵合法 JSON（三種 verdict）→ 正確分流；餵壞 JSON / 缺欄位 / `checklist` 長度錯 / `FLAG` 缺證據 → 判無效並累加 streak；streak 達上限 → `human_required`。
- **Integration**：mock repo 跑一輪 execute（agent 改用 CLI 寫計數器）→ CONTROL scalar 正確更新且格式不壞；mock 一筆 REVERT JSON → 引擎執行 `git revert` 且 `last_safe_sha` 不前進。
- **回歸**：既有 `get_val`/`set_val` 單測（若有）續綠；`last_safe_sha == HEAD`、無 diff、首次無基準等短路路徑不變。

## Rollout

1. 先落 Part A 的 `state.py` CLI + 校驗（純新增，不影響既有引擎呼叫）。
2. 切 prompt / boot-sequence 指示到 CLI，觀察一輪能否成功寫狀態。
3. 再落 Part B 的 JSON 切換（prompt + 規則 + 引擎解析同一次 PR，避免新舊協定錯配）。
4. B4 回饋句為選配，可最後加。
