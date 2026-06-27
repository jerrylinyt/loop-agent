# 🎛️ CONTROL — <專案名> 主控檔

> **唯一進入點,每輪唯一必讀的檔案。** 只放「決定要做什麼 + 記錄狀態 + 索引」的最小資訊(見 framework rules/context-budget.md)。
> 任務詳細規格在 `phases/PHASE*.md`(按需讀);通用方法論在 `<framework_path>/rules/*`(按需讀)。
> **plan_version**: 1   **framework_ref**: (引擎每輪回填)

---

# ⚡ 第一段：開機（依框架通用規則）
> 每輪第一件事:依 `<framework_path>/rules/boot-sequence.md` 執行 BOOT SEQUENCE(STEP G→10)。
> **本輪必讀** = 本檔 CONTROL.md + `<framework_path>/rules/boot-sequence.md`;其餘 rules 按需讀。
> 相關通用規則(按需開):
> - git-safety.md（STEP G 自檢/還原；git 只作用工作區，禁寫 framework_path）
> - state-model.md（計數器與流程定義）
> - convergence.md（單任務收斂）／ completeness.md（大範圍防漏）
> - oscillation-escalation.md（震盪/三層升級/FROZEN）／ issues.md（Issue 分級）
> - context-budget.md（每輪讀取預算；CONTROL 保持決策最小集）

---

# 📁 第二段：Repository 結構（工作區 = 這個 code repo）
```
<列出這個專案的輸入夾 / 各階段產出夾 / .loop/ 結構>
```
> 寫入白名單:只允許寫 `.loop/`（CONTROL/phases/config/log）與工作區產出；**禁止寫 framework_path**。

---

# 📊 第三段：變數與計數器（單一事實來源；定義見 rules/state-model.md）
> 只放「活計數器」（會變的數值）；門檻/階段定義在 loop.config.yaml，不在這裡。

```yaml
current_phase: 1
# 每個 phase 一組（id 對應 config.phases）
p1_consecutive_pass: 0
p1_total_validations: 0
p1_last_result: ""
# …（有幾個 phase 就有幾組 p{id}_*）

blocking_issues: 0
stop_condition_met: false
plan_version: 1
framework_ref: ""

last_round_mode: ""
last_round_result: ""
last_round_fail_tasks: ""

rounds_since_progress: 0
stuck_level: 0
current_model_tier: ""               # 引擎回填：fast / normal / thinking（升級鏈如 fast→normal）
enhanced_rounds_used: 0
human_required: false
```

---

# 🧩 第四段：各 Phase 狀態表 + Coverage
> 每個 phase 一張表。Status: TODO/DRAFTED/CONVERGED/NEEDS_REVISION/FROZEN；Conv = 連續一致次數/門檻。

## Phase 1（<名稱>）狀態表
| # | 任務 | 產出位置 | Status | Conv | Round |
|---|------|---------|--------|------|-------|
| 01 | <…> | <…> | TODO | 0/<門檻> | - |

## Coverage 定義與統計（每指標寫清楚分母來源）
| 指標 | 分母 | 分子 | % | 更新 Round |
|------|------|------|---|-----------|
| <…> | <…> | 0 | -% | - |

> （phase 數多時:每階段狀態表可移到各自 phase 檔的頭，CONTROL 只留當前階段那張 + 彙總，見 context-budget.md C）

---

# 🔗 第五段：需求 → 任務 追溯表
| 需求 ID | 對應任務 | 驗證 |
|---------|---------|------|
| R001 | TASK-01 | <…> |

---

# 🐛 第六段：Issue 索引（內文一檔一個，見 rules/issues.md）
| Issue ID | 等級 | 標題 | Phase/TASK | 狀態 | 建立 Round |
|----------|------|------|-----------|------|-----------|
| (無) | | | | | |

---

# 📝 第七段：最近執行摘要（只留最近 journal_in_control_keep 筆；完整日誌在 loop.log）
```
=== Round #--- ===
（最近一輪摘要）
```
