# 🎚️ RULE — 狀態模型與流程控制（通用、N 階段、config 驅動）

> **唯讀框架規則**。引擎(loop.py/loop.sh)與 agent(CONTROL boot)**共同遵循這份定義**。
> 不出現任何字面階段數;一切以 `loop.config.yaml.phases`(N 筆,最後一筆=最終階段)表達。

## 1. 狀態控制（state — 活在 CONTROL.md，單一事實來源）

> 原則 2:文件即狀態。把現在的 agent 關掉換一個新的,新 agent 只靠 CONTROL 能不能接手?不能就是沒落地。

通用狀態欄位(每個專案的 CONTROL 都要有;`{id}` 對應 config.phases 的 id):
```yaml
# 階段
current_phase: <id>                  # 指向 config.phases 之一

# 每階段一組計數器（id 由 config.phases 給）
p{id}_consecutive_pass: 0            # 連續通過全量驗證次數
p{id}_total_validations: 0
p{id}_last_result: ""                # PASS / FAIL

# 共用
blocking_issues: 0
stop_condition_met: false            # true = 全部完成,agent 應立即停止
plan_version: 1                      # 規劃書版本(§版本規劃)
framework_ref: ""                    # 本輪跑在哪個框架 commit(快照,供追溯)

# 每輪 agent 回填（震盪偵測用,務必每輪更新）
last_round_mode: ""                  # 推進 / 驗證
last_round_result: ""                # PASS / FAIL / NA（NA=非驗證輪）
last_round_fail_tasks: ""            # 本輪驗證失敗被打回的任務,逗號分隔;PASS 留空

# 震盪/升級（多由外部 loop 維護,agent 只在升級到人類時動 stuck_level/凍結）
rounds_since_progress: 0
stuck_level: 0                       # 0=正常(預設模型) / 1=增強模型 / 2=人類
current_model_tier: default         # default / enhanced
enhanced_rounds_used: 0
human_required: false               # true = 卡死已凍結互卡任務,需人類裁決
```

### 設定 vs 狀態（最重要的一刀）
- **門檻 / 階段定義 / 停止條件**(converge_threshold、phases、stall_threshold…)= **設定** → `loop.config.yaml`,**不放 CONTROL**。
- **活計數器**(current_phase、p{id}_*、stuck_level…)= **狀態** → CONTROL.md。
- 同一門檻只在 config 出現一次,避免兩處 drift(也避免 CONTROL 變胖,見 context-budget.md)。

### 任務生命週期狀態（各 phase 狀態表內）
`TODO / DRAFTED / CONVERGED / NEEDS_REVISION / FROZEN`(定義見 convergence.md、oscillation-escalation.md)。

## 2. 流程控制（flow — 引擎 + boot 共同驅動，全 config 化）

| 機制 | 通用判準（config 驅動） | 由誰執行 |
|------|------------------------|---------|
| **BOOT SEQUENCE** | STEP G→10;階段數/產出位置/停止條件「依 config」 | agent |
| **Phase Gate** | 相鄰階段 i→i+1:`phase i 全 CONVERGED 且 p{i}_pass>=門檻 且 blocking==0` → 進 i+1 | agent |
| **停止(正常)** | `current_phase==最後階段 且 p{last}_pass>=final_phase_pass_gte 且 blocking==0`,或 `stop_condition_met==true` | 引擎 + agent |
| **停止(交人類)** | `human_required==true` | 引擎 |
| **震盪偵測** | 失敗指紋環狀歷史 + 視窗(門檻全 config) | 引擎(最客觀) |
| **三層升級** | 預設→增強→人類(門檻/模型全 config) | 引擎切 tier,agent 凍結/開 Issue |
| **Git 守護** | 一輪一 commit + 開機自檢 + 整檔空白兜底還原(只在 code repo) | agent(G0 語意) + 引擎(兜底) |

### N 階段關鍵
- `is_done`、Phase Gate、計數器全部以「config.phases 的最後一個 / 任意相鄰兩個」表達,**不出現字面階段數**。
- 「最後階段 = config.phases 的最後一筆」;每階段的收斂門檻可在 config 各自指定(`phases[i].converge_threshold`)。

## 3. 引擎讀寫 CONTROL 的方式（context 友善）
- 引擎用單行 `grep`/正則讀寫 CONTROL 的 `key: value`(不載入 LLM context)。
- 引擎**只 parse CONTROL 計數器**,**不 parse log**;log 是給人 `tail -f` 的(見 context-budget.md)。
