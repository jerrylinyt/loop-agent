# 🏗️ 計畫書 4 — Engine v3：引擎主導編排（任務卡 + verify 契約 + schema v3）

> **狀態**：待執行
> **依賴**：計畫書 1、2、3 全部完成
> **產出 branch**：`refactor/4-engine-v3`（工程量大，建議依里程碑 M1–M6 分 PR）
> **對應 review**：§5 全節、§6
> **授權**：使用者已明確同意**不需向後相容**——可重切資料結構、刪除舊路徑，既有 workspace 直接重新 init。

## 0. 目標與核心思想

把三層重複執法（rules 散文 / LLM review / state.py 守衛）收斂成一層：**凡可機器判讀的決策，一律由引擎做**。agent 退化成純函式：「收到一張任務卡 → 做這一件事 → 交回報告 → 停機」。

**翻新後的每輪時序（目標狀態）**：
```
引擎：G0 自檢 → Review Gate（分層，見 M4）→ 停止/Phase Gate 判定 → 挑任務 →
      組任務卡（內嵌規格小節 + 動作指引）→ 喚醒 agent
agent：讀任務卡 → 做這一件事 → 寫產出 → `state_cli report` 交回報告 → commit → 停機
引擎：跑 verify.check（若有）→ 依 report + verify 結果推進狀態機 → 震盪偵測 → 下一輪
```

**成功指標**（用 trace 遙測驗證，計畫書 3 T6 已鋪好）：
- 每輪平均 prompt bytes 相對 v2 −40% 以上
- `verify.kind=command` 任務的平均收斂輪數 → ≤ 2（現況：1 初稿 + N 重驗 + gate 抽查）
- Review Gate LLM 呼叫次數 −50% 以上；機械類 REVERT（截斷/衝突標記/佔位符/計數灌水）→ 由 L0 100% 攔截
- agent 每輪固定必讀內容 ≤ 50 行（boot-sequence 瘦身後 + 任務卡）

---

## M1｜state.json schema v3 與 state.py 重寫

### M1.1 Schema 規格（完整欄位表）

```jsonc
{
  "schema_version": 3,

  "run": {                          // ★ 僅引擎可寫（agent CLI 無任何路徑寫到這裡）
    "current_phase": "2",
    "run_id": "", "round": 0,
    "run_branch": "", "base_branch": "",
    "stuck_level": 0, "rounds_since_progress": 0, "enhanced_rounds_used": 0,
    "current_model_tier": "fast",
    "human_required": null,          // null 或 {code, reason, since, source, suggested_action, run_id}
    "awaiting_acceptance": false, "accepted_by": "", "accepted_at": "",
    "last_safe_sha": "", "review_invalid_streak": 0,
    "human_note_inject_until_round": 0
  },

  "plan": {                          // plan_loop 專用（沿用 v2 欄位語意）
    "status": "converged", "stable_rounds": 2, "gate_last": "PASS", "gate_last_reason": "",
    "changed_last": false, "version": 1,
    "approved": true, "approved_by": "", "approved_at": "",
    "human_required": null, "stuck_level": 0, "rounds_since_progress": 0
  },

  "phases": [{
    "id": "2", "name": "實作",
    "spec": ".loop/<ws>/phases/PHASE2.md",
    "converge_threshold": 2,
    "gate": { "consecutive_pass": 3, "required": 10, "total_validations": 5, "last_result": "PASS" },
    "tasks": [{
      "id": "TASK-17", "title": "移植 GET /api/orders/:id",
      "order": 17, "depends_on": ["TASK-05"],
      "spec_ref": "phases/PHASE2.md#task-17",          // 任務卡擷取錨點（見 M2.3）
      "reads": ["src/legacy/orders.js:120-210"],       // 依賴讀取（plan 期宣告，注入任務卡）
      "output": "src/api/orders.ts",                    // 正式產出範圍（review L0 用）
      "verify": {                                       // ★ 驗證契約（見 M3）
        "kind": "command",                              // command | reverify | enumerate | none
        "check": "npm test -- orders.spec.ts",          // kind=command 必填
        "threshold": 2                                  // kind=reverify/enumerate 用；command 固定 1
      },
      "tier_hint": "fast",                              // fast | normal（plan 期宣告，見 M6）
      "status": "DRAFTED", "conv": 1,
      "evidence": ["…/.reverify/TASK-17-R083.md"],      // 引擎回填；壓實保留最新 threshold 筆
      "revert_history": []                              // 引擎回填最近 REVERT 原因（≤3 筆），任務卡帶入
    }]
  }],

  "issues": [ { "id": "ISSUE-04", "level": "BLOCKING", "status": "OPEN",
                "title": "…", "phase": "2", "task": "TASK-17", "file": "issues/issue-04.md" } ],

  "requirements_map": { "R001": ["TASK-03", "TASK-17"] },

  "agent_report": {                  // ★ agent 唯一可寫區（整包提交，見 M1.3）
    "round": 87, "task": "TASK-17", "action": "DRAFT",
    "summary": "…", "wrote_files": ["src/api/orders.ts"],
    "evidence_file": "", "opened_issues": [], "needs_freeze": false,
    "self_result": "DONE"            // DONE | BLOCKED（BLOCKED 必附 opened_issues）
  }
}
```

派生值（**不落檔、引擎即時計算**，消滅 v2 的鏡射欄位漂移）：`blocking_issues`、`stop_condition_met`、`last_round_*`（由 verify 結果與 report 推導，寫進 rounds.jsonl 而非 state）。

### M1.2 state.py 重寫範圍

- **刪除**：扁平字串鍵路由（`get_val/set_val` 的 `p{n}_*` 解析）、白名單表、md 遷移碼（`migrate_to_json`、`_get_val_from_md_content`）、`render_all` 空殼。引擎內部一律 `load_state_json` 後以路徑存取，包一層薄 helper（`state3.py` 或重寫 `state.py`，實作者擇一，命名一致即可）。
- **保留並簡化**：原子寫入、`state_events.jsonl` 稽核、guarded transition（規則少一半：agent 不再直寫任務狀態，單步轉移/配額/門檻檢查改為**引擎狀態機的內部斷言**）、dry-run。
- `schema_version` 檢查：讀到非 3 → 明確報錯「請重新 init workspace（v3 不相容舊 state）」。

### M1.3 agent 介面縮減為單一 `report` 子命令

```
{state_cli} report --task TASK-17 --action DRAFT \
    --summary "…" --wrote src/api/orders.ts --evidence <path> \
    [--open-issue "ISSUE-05|BLOCKING|標題"]... [--result DONE|BLOCKED] [--needs-freeze]
```
- 寫入 `agent_report` 區（整包覆寫）+ state_events 稽核。**不直接改任務狀態**。
- 校驗：task/action 必須與本輪任務卡一致（引擎啟動 agent 前把 expected task/action 寫入 `.loop_state/expected_action.json`，report 時比對，不符 → exit 1 + 錯誤訊息教它照卡做）。同輪重複 report → 覆寫並記事件（最後一次為準）。
- `task-status` / `task-conv` / `incr` / `set` 等子命令**從 agent 可用面移除**（保留 `--source engine|dashboard|human` 的內部路徑供引擎/工具用）。`rules/state-cli-guide.md` 整檔刪除，report 用法三行寫進任務卡。

### M1 驗收
- [ ] 新 schema 的 JSON Schema 檔（`engine/schema/state-v3.schema.json`）+ `test_state_v3_schema_validates`
- [ ] `test_report_writes_only_agent_report`（report 前後 diff 僅 agent_report + events）
- [ ] `test_report_rejects_wrong_task`
- [ ] `grep -rn "migrate_to_json\|p1_consecutive_pass" engine/`（字串鍵路由殘留）零筆
- [ ] init-project.py 產出 v3 骨架；`is_done` / phase gate 全改讀 v3 結構且測試覆蓋

---

## M2｜引擎編排器：挑任務 + 任務卡

### M2.1 挑任務演算法（`engine/orchestrator.py::select_action(state, cfg) -> Action`）

純函式，輸入 state+cfg、輸出本輪動作，**必須有完整單元測試**：

```
1. human_required 非 null → Action(HALT_HUMAN)
2. 停止條件（沿用 is_done 語意：最後 phase 全 CONVERGED ∧ gate.pass≥required ∧ blocking==0）→ Action(COMPLETE)
3. Phase Gate：current_phase 的任務全 CONVERGED ∧ gate.pass≥required ∧ blocking==0 ∧ 非最後 phase
   → Action(ADVANCE_PHASE)   # 引擎直接執行：current_phase+1、寫日誌、commit——【不再花一輪 agent】
   （執行後回到步驟 1 重新評估，同一次迴圈內完成，省掉 v2「過 gate 燒一輪」的開銷）
4. 掃 current_phase 任務（order 排序）取第一個「可做」者：
   status ∉ {CONVERGED, FROZEN} ∧ depends_on 全 CONVERGED
   ├ TODO            → Action(DRAFT, task)
   ├ NEEDS_REVISION  → Action(FIX, task)          # conv 已被引擎歸零
   └ DRAFTED:
       verify.kind == command   → Action(RUN_CHECK, task)    # 不喚醒 agent，引擎自跑（M3）
       verify.kind == reverify  → Action(REVERIFY, task)
       verify.kind == enumerate → Action(ENUMERATE, task)
       verify.kind == none      → 引擎直接標 CONVERGED（Init 類），continue
5. 無可做任務：
   ├ 存在 FROZEN → Action(HALT_HUMAN, code=frozen_blocked)   # v2 boot STEP 4 的 FROZEN 鐵則，機制化
   └ 全 CONVERGED → Action(PHASE_VALIDATE)                    # 全量驗證輪
```

v2 靠散文防的整類漏洞（挑軟柿子/一輪多任務/跳依賴/FROZEN 刷分/gate 當輪順做）在此**物理消滅**——對應的 rules 條款與 review 紅線於 M5 刪除。

### M2.2 任務卡（prompt 即卡片）

`orchestrator.build_task_card(action, state, cfg) -> str`，取代 v2 的 `base` prompt。版型：

```
# 本輪任務卡（round {round} / run {run_id}）
任務：{task.id}「{task.title}」   動作：{DRAFT|FIX|REVERIFY|ENUMERATE|PHASE_VALIDATE}
{若 FIX：被退回原因（revert_history 最新一筆 / NEEDS_REVISION 來源）}
{若 REVERIFY：第 {conv+1}/{threshold} 次獨立重驗}
{若有 HUMAN_NOTES 注入窗口：📌 人類裁決附註…}

## 規格（自 {spec_ref} 擷取，你不需要再讀 phase 檔）
{錨點小節全文}

## 依賴讀取（只准讀這些；大檔分段讀）
{task.reads 逐行}

## 知識索引（規格外疑問先查這裡，只讀命中的小節；索引沒有 → 開 Issue，不准腦補）
{docs/INDEX.md 全文或命中過濾後內容，見 M2.4}
{repo 佈局與指令：依 runtime.repomap_inject 注入 pointer 一行或內嵌 .loop/REPO_MAP.md（計畫書 2 T10，CLI 中立管道）}

## 本輪動作指引
{按 action 類型內嵌對應 rules 摘錄：DRAFT→寫檔守則；REVERIFY→convergence.md 重驗程序；
 ENUMERATE→completeness.md 列舉程序；PHASE_VALIDATE→驗證證據檔要求}

## 收尾（三步，做完立即結束 process）
1. {state_cli} report --task {id} --action {action} --summary "…" --wrote … [--evidence …]
2. git add -A && git commit -m "R{round} | phase{n} | {id} | {action} | <一句摘要>"
3. 立即停止輸出並結束本 process。❌ 嚴禁繼續做第二件事或自行開下一輪。
```

- 規格小節擷取：`spec_ref = 檔案#錨點`，錨點 = phase 檔中 `## {TASK-ID}` 標題到下一個 `## ` 之間全文。`PHASE.template.md` 改版為此格式（每任務一個 `## TASK-xx` 小節，內含 title/做什麼/驗證標準）。plan generator（`1-plan-generator.md`）同步要求產出符合錨點格式，plan gate 加一條機械檢查（引擎在 plan 收斂時驗證每個 spec_ref 可解析，解析失敗 → gate FAIL 理由回填）。
- 動作指引摘錄：rules 檔用 HTML 註解錨點標記可嵌區（`<!-- CARD:reverify-start/end -->`），build 時擷取——rules 仍是單一事實來源，任務卡是機械投影，不會漂移。
- 任務卡總長預算：`runtime.task_card_max_bytes`（預設 24000），超限 → 啟動前報錯（代表 plan 把規格小節寫太肥，錯誤訊息指向該 task 的 spec 小節）。

### M2.3 agent 停機後的引擎收尾

1. 讀 `agent_report`，校驗 task/action 匹配（M1.3）。無 report / 不匹配 → 本輪視為無效輪（記 rounds.jsonl `invalid_report`，不推進任何狀態，走既有 no_activity 震盪累計）。
2. 依 action 推進狀態機（引擎斷言單步轉移）：
   - DRAFT/FIX + result=DONE → status=DRAFTED（FIX 時 conv 已歸零）。
   - REVERIFY/ENUMERATE → **引擎驗證證據檔存在且檔名含本輪 R###**（v2 review 紅線 12 的存在性檢查機制化）→ 依 report 判定：evidence 顯示一致 → conv+1（達 threshold → CONVERGED）；有實質差異（report summary 標記 `--result DIFF`，report 介面加此值）→ conv=0。**產出檔異動偵測**（v2 紅線 13）：本輪 commit diff 觸及 task.output 範圍 → 強制 conv=0，無視 report 宣稱。
   - PHASE_VALIDATE → 證據檔存在 + report DONE → gate.pass+1；report FAIL → gate.pass=0、fail 任務標 NEEDS_REVISION。
   - result=BLOCKED → 開 report 附帶的 issues（引擎代寫 issue 檔骨架 + state 索引）；needs_freeze 且引擎已判卡死（stuck_level==2）→ 標 FROZEN（**agent 無權自行凍結**，v2 oscillation 紅線機制化）。
3. `last_round_*` 概念改為 rounds.jsonl record 欄位（state 不再存）。

### M2.4 知識索引（INDEX）：run 內產出知識的可發現性

**動機**：任務卡只注入 plan 期宣告的 `reads`；計畫外的知識需求（別的任務已分析過的結論）目前只能靠 agent 瞎找、或更糟——重新推導一遍還推錯。解法是**目錄即查詢**：確定性、可稽核、零新依賴，明確**不引入 embedding/RAG**（抽取端雜訊、時效陳舊無感知、檢索靜默漏抓，皆與可稽核體質相沖；repo 靜態地圖層另由計畫書 2 T10 的 REPO_MAP 解決——以框架 prompt 管道為保證線、各 CLI 原生知識檔僅為鏡射優化，兩層不重疊）。

**規格**：
1. **plan generator 規則**（`1-plan-generator.md` 同步更新）：凡有分析型產出（落 `{{LOOP_DIR}}/docs/`）的 phase，必須包含一個「INDEX 維護」列舉型任務——維護 `{{LOOP_DIR}}/docs/INDEX.md`，**一行一份產出文件**：`主題關鍵詞 → 檔案#錨點`。以集合穩定收斂維護（completeness 協定現成適用，分母 = docs/ 下產出檔集合）。
2. **任務卡注入**：`build_task_card` 在「依賴讀取」節後注入「知識索引」節（見 M2.2 版型），內容為 INDEX 全文。
3. **注入預算**：INDEX 行數 > `runtime.index_inject_max_lines`（新鍵，預設 150）時，降級為過濾注入——只注入「與本任務 reads/output 路徑或標題關鍵詞命中的行」+ 提示「完整索引見 docs/INDEX.md」，並 log warning（INDEX 過大通常代表 plan 把文件切太碎）。INDEX 注入量計入 `task_card_max_bytes` 總預算。
4. **plan gate 機械檢查**（引擎代查，與 spec_ref 解析檢查同批）：存在 docs 產出的 phase 而無 INDEX 任務 → gate FAIL 理由回填；INDEX 行的錨點格式沿用 spec_ref 同款（`檔案#小節標題`），引擎抽查錨點可解析，壞行列入 FAIL 理由。

### M2 驗收
- [ ] `select_action` 單元測試 ≥ 15 個情境（含：依賴未齊跳過、FROZEN 擋 phase、gate 當步推進、全 CONVERGED 進驗證、frozen_blocked 停機）
- [ ] `test_task_card_embeds_spec_and_reads`、`test_task_card_size_budget`
- [ ] `test_engine_applies_report_single_step`（狀態推進全由引擎、非法轉移斷言擋下）
- [ ] `test_output_change_forces_conv_reset`（紅線 13 機制化）
- [ ] `test_task_card_injects_index` / `test_index_inject_filtered_when_large`（150 行預算降級路徑）
- [ ] `test_plan_gate_requires_index_task` / `test_index_anchor_resolvable`
- [ ] 整合測試：fake agent（腳本讀卡、寫檔、report、commit）跑通 DRAFT→REVERIFY×2→CONVERGED→PHASE_VALIDATE→COMPLETE 全鏈

---

## M3｜verify 契約：引擎親自跑客觀驗證

### 規格

1. `orchestrator` 遇 `Action(RUN_CHECK)`：**不喚醒 agent**，直接：
   ```
   subprocess.run(shlex.split(task.verify.check), timeout=runtime.check_timeout_seconds(新鍵,預設 900),
                  capture_output → 寫 .loop_state/checks/R{round}-{task}.log（尾 200 行另存證據檔進版控：
                  <output_dir>/.validate/{task}-R{round}.md，含指令、rc、輸出尾段）)
   rc==0 → conv=threshold（=1）→ CONVERGED；rc!=0 → status=NEEDS_REVISION + evidence 附 log 路徑，
           下一輪 FIX 任務卡內嵌失敗輸出尾 50 行（弱模型需要具體錯誤才修得對）。
   ```
2. check 的執行也算「一輪」（占 round 序號、記 rounds.jsonl `loop_type: check`、參與震盪指紋——fail_tasks=該 task、files=commit diff）；interval 照睡。
3. **安全邊界**：check 指令來自 plan、經人類 `approve-plan` 核可（計畫書 2 T6）——PLAN_SUMMARY 必須完整列出所有 check 指令供人審。引擎不做沙箱（與 agent 同權限），但 preflight 靜態掃描 check 內容：含 `rm -rf`、`git push`、`curl|sh` 等 pattern → error。
4. phase 收尾全量驗證：phase 可宣告 `gate.check`（phase 級指令，如整包 test suite）。有宣告 → PHASE_VALIDATE 輪改為引擎跑 check（gate.pass 由 rc 驅動，required 可設低如 3）；未宣告 → 維持 agent 驗證輪。
5. plan generator / plan gate 更新：實作型任務**必須**宣告 `kind=command` 與可執行 check（寫不出 check = 切壞了，退回重拆）；純分析任務才允許 reverify/enumerate。plan gate 檢查表加此條（機械可查：掃 phases 任務的 verify 欄位）。verify 內容的**品質下限**依 `generators/acceptance-standards.md` §6 速查表（後端 = integration test、前端 = component/E2E、分析 = inventory+行覆蓋、遷移 = contract+parity 選型），該檔已存在、plan gate 已含對應抽查項。

### M3 驗收
- [ ] `test_run_check_pass_converges` / `test_run_check_fail_marks_needs_revision_with_log`
- [ ] `test_check_timeout_counts_as_fail`
- [ ] `test_preflight_blocks_dangerous_check`
- [ ] `test_phase_gate_check_drives_pass_counter`
- [ ] 整合測試：check=`pytest` 的迷你專案，故意壞一輪 → FIX 卡內嵌錯誤輸出 → 修好 → 收斂，全程 agent 零次自報 PASS

---

## M4｜Review Gate 分層（L0 機械 / L1 語意）

### L0（Python，每輪必跑，零成本）——新檔 `engine/review_l0.py`

對 `last_safe..HEAD` diff 逐項機械檢查，任一 FAIL → 直接 REVERT（沿用既有 revert 路徑），不叫 LLM：

| 檢查 | 實作要點 |
|------|----------|
| 檔案截斷/空白 | 改動檔非空、文字檔結尾完整（沿用 inspect_and_fix_blank 邏輯擴充到 diff 內全部檔案） |
| 衝突標記 | diff 新增行 grep `^(<{7}|={7}|>{7})` |
| 佔位符偷懶 | 新增行 pattern：`\.\.\. existing code|TODO: implement|此處省略`（pattern 表放 config 可擴充） |
| 思考外洩 | 新增行含 `<think>|以下是為您` 等 pattern 表 |
| Markdown/JSON/YAML 完整性 | 改動的 .json/.yaml 可 parse；.md 的 ``` 配對數為偶數 |
| 狀態合法性 | v3 下 agent 只能動 agent_report——diff 中 state.json 的變更若超出 agent_report/events 範圍 → REVERT（**整類狀態偽造檢查簡化為一條**） |
| 秘密外洩 | diff 新增行過 secret pattern 表（gitleaks 常見規則子集：雲端金鑰、私鑰 PEM header、bearer/API token、DB 連線字串含密碼…；pattern 表在 config 可擴充）→ REVERT。**agent 整晚自動 commit，token 一旦入 commit 就進歷史**——此檢查必須在 L0（每輪必跑、零成本），不等 H2.2 沙箱 |
| 產出越界 | 改動檔案 ∉（本輪任務 output ∪ reads 所在目錄 ∪ .loop 證據區）→ FLAG（預設 REVERT；config 可降 warning） |
| 框架寫入 | 改動觸及 framework_path → REVERT |

### L1（LLM，條件觸發）

- 觸發條件（or）：本輪宣稱收斂推進（conv+1 / gate.pass+1）∧ verify.kind≠command；diff 新增行 > `review_l1_diff_lines`（新鍵，預設 400）；隨機抽樣 `review_l1_sample_rate`（預設 0.2）；上一輪被 REVERT 後的重試輪。
- **`verify.kind=command` 且 check 綠的輪，預設不觸發 L1**（客觀驗證已把關）。
- 審查項縮減為 4 項：語意一致性（commit msg vs diff）、證據抽查（reverify/enumerate 的獨立性防偽——v2 紅線 12 的抽查部分，存在性已由引擎 M2.3 做）、中間區段挖空、規格外改動的合理性。verdict JSON checklist 對應改 4 項，`_review_checklist_valid` 同步。
- **L1 prompt 必帶「本輪上下文摘要」（引擎組裝，非 agent 自述）**：本輪 task id / action / output 與 reads 範圍 / 宣稱的推進（conv、pass 變化）——「語意一致性」與「規格外改動」的判斷前提是審查者知道**這輪本來該做什麼**；v2 的 review prompt 沒給這個，審查者只能瞎猜任務意圖。
- prompt 沿用計畫書 3 T3 的內嵌上限。

### M4 驗收
- [ ] L0 每項一個以上單元測試（fixture diff）；secret 掃描另加誤報測試（正常 code 中的 `token` 變數名不觸發）
- [ ] `test_l1_skipped_for_green_command_check` / `test_l1_triggered_on_subjective_conv`
- [ ] 整合統計：整合測試 20 輪中 LLM review 呼叫次數 < 10（抽樣率固定 seed）
- [ ] `rules/git-review-gate.md` 改版：13 項 → L0 表（註明引擎執法）+ L1 的 4 項；`pre-commit-checklist.md` 對應瘦身（只留 agent 自查有意義的 1/3/4 三項）

---

## M5｜rules / generators 全面瘦身

1. **boot-sequence.md**：142 行 → ≤ 50 行。刪除 STEP 0-4（引擎做）、STEP 9 的 CLI 教學（任務卡內嵌）；保留：寫檔守則（STEP 7）、留證鐵則、commit 格式、STEP 10 停機紀律。更名為 `agent-conduct.md`（它不再是「開機程序」而是「行為守則」）。
2. **刪除**：`state-cli-guide.md`（M1.3）；`state-model.md` 重寫為 v3 schema 說明（對人/引擎，不再是 agent 每輪讀物）。
3. **convergence.md / completeness.md**：加 `<!-- CARD:… -->` 錨點（M2.2）；刪除「嚴禁自判收斂類別」「嚴禁同輪雙重驗」等已機制化條款（引擎控制動作類型與次數）。
4. **每份 rule 開頭加執法標記**：`> enforced-by: engine | review-L0 | review-L1 | prompt`。盤點後仍為 `prompt`（純自律）的條款寫進 `maintenance/` 的待機制化清單，供爬坡迴圈追蹤。
5. **BLUEPRINT.md**：拆為 `rules/PHILOSOPHY.md`（九原則、反模式、生命週期——給人與 plan 期讀）；§3 的機制細節改為指向引擎實作與各 rule；§3.10 樹模式整節移到 `docs/future/`（引擎已不支援）；§9 盤點節刪除（被計畫書 2 的 gate 實作取代）。
6. **generators**：`1-plan-generator.md` / `2-plan-review-gate.md` 更新——產出物含 verify 契約、spec_ref 錨點格式、tier_hint；plan gate 檢查表加「實作任務皆有可執行 check」「spec_ref 可解析」（後者引擎機械代查）。
7. `prompts.yaml`：`base` 由任務卡取代（刪除）；保留 `escalation`（併入任務卡的升級注入段）、`git_review`（L1 用，改 4 項版）、`plan`、`plan_gate`。
8. **提示引用同步（防 B1 類腐爛重演）**：rules/generators 重組後，`plan` / `plan_gate` prompt 內文引用的檔名**必須**同步更新——`BLUEPRINT` → `PHILOSOPHY`、`boot-sequence` → `agent-conduct`、移除 `state-cli-guide` 引用、補 `acceptance-standards`。並新增 **CI 參照完整性測試**：掃描 `prompts.yaml` 全部 prompt 內文、任務卡 builder、`generators/*.md` 中引用的檔案路徑與 `<!-- CARD:… -->` 錨點，逐一斷言目標存在——任何 prompt 指向已刪/改名資源 → CI 紅。這是「agent 確定拿得到被指向的東西」的永久機械保證（B1 的教訓：靠人記引用一定爛）。

### M5 驗收
- [ ] `wc -l rules/agent-conduct.md` ≤ 50
- [ ] 每份 rule 首行有 `enforced-by` 標記；`grep -c "enforced-by: prompt" rules/*.md` 的清單與 maintenance 待機制化清單一致
- [ ] `grep -rn "state-cli-guide\|STEP 4\|挑軟柿子" rules/ engine/prompts.yaml` 零筆（已機制化條款不再出現）
- [ ] CI 參照完整性測試綠；故意把 prompts.yaml 一個引用改成不存在的檔名時 CI 轉紅（驗證防線後還原）
- [ ] fake-agent 整合測試在新 rules/prompts 下全綠（M2/M3 的整合測試重跑）

---

## M6｜模型調度優化

1. **tier_hint**：`select_model(cfg, "execute", stuck_level, tier_hint)`——stuck_level==0 時以 `task.tier_hint`（預設 fast）為基底；升級階梯從 hint 所在層往上爬。plan generator 指引：跨檔重構/複雜演算法/整合類任務標 `normal`。
2. **同指紋快升**：`detect_oscillation` 之外加一條：最近連續 3 輪 fail_fingerprint **完全相同** → 立即升級（不等 `stall_threshold=10`）。config 鍵 `oscillation.identical_fp_escalate: 3`。
3. **plan gate 快取**：plan cycle 中 `changed == False` 且上一 cycle `gate_last == PASS` → 本 cycle 跳過 Round B（直接沿用 PASS，`stable_rounds+1`），log 註明「gate cached」。安全性：無變更 = 審查對象相同，重審無資訊增量；首個 PASS 仍是真審。
4. **成本記帳**：rounds.jsonl 已有 model_tier + duration（計畫書 1/3）；RUN_REPORT 匯總各層輪數×總時長；`collect_traces` 聚合供門檻校準。

### M6 驗收
- [ ] `test_tier_hint_base_and_escalation`
- [ ] `test_identical_fingerprint_fast_escalation`
- [ ] `test_plan_gate_cached_when_unchanged`（含首輪不快取）

---

## 收尾：遷移與清理

- init-project.py 只產 v3；引擎讀到 `schema_version != 3` → 報錯建議重 init（**不寫遷移器**，經授權）。
- 刪除：`engine/state.py` 舊路由碼、`migrate` 子命令、`prompts.yaml` 的 `base`、`rules/state-cli-guide.md`、BLUEPRINT 樹節。
- **路由文件畢業**：把 `docs/refactor/ROUTING.md` 的 §A/§B 依實作後真實狀態校正，安裝為常駐架構文件 `docs/architecture/routing.md`（此後任何注入/產出物變更的 PR 必須同步維護它；M5 第 8 點的 CI 參照完整性測試以此檔＋prompts/builder 實體為稽核對象）；原 ROUTING.md 標記 superseded、§C 增補帳確認全數消帳後退役。README 的引用同步改指向新位置。
- README 全面改版對齊 v3 時序圖。
- 全里程碑完成後跑一次**真實 LLM 的端到端演練**（小型真專案 + 便宜模型），與 v2 對照組比對 §0 的四個成功指標，結果寫進 `docs/review/` 作為翻新驗收報告。

## 最終驗收清單

- [ ] M1–M6 各里程碑驗收全過；`pytest engine/` 全綠（含 fake-agent 整合鏈）
- [ ] 真實演練達成 §0 成功指標（prompt −40%、command 任務 ≤2 輪、review 呼叫 −50%、必讀 ≤50 行），數據落 docs/review/
- [ ] agent 可寫面只剩 `report`（稽核 state_events 證明無其他寫入路徑）
- [ ] `docs/architecture/routing.md` 已安裝且反映實作後狀態；ROUTING.md §C 增補帳全數消帳並標記 superseded
- [ ] v2 殘留掃描：`grep -rn "boot-sequence.md 的 BOOT SEQUENCE\|task-status --phase\|last_round_mode" engine/ rules/ generators/` 零筆
