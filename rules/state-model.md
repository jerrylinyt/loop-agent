# 🎚️ RULE — 狀態模型與流程控制（通用、N 階段、config 驅動）

> **唯讀框架規則**。引擎(loop.py/loop.sh)與 agent(CONTROL boot)**共同遵循這份定義**。
> 不出現任何字面階段數；一切以 `loop.config.yaml.phases`(N 筆，最後一筆=最終階段)表達。

## 1. 狀態控制（state — 活在 CONTROL.md，單一事實來源）

> 原則 2:文件即狀態。把現在的 agent 關掉換一個新的，新 agent 只靠 CONTROL 能否接手？不能就是沒落地。

通用狀態欄位（每個專案的 CONTROL 都要有；`{id}` 對應 config.phases 的 id）：
```yaml
# 階段
current_phase: <id>                  # 指向 config.phases 之一

# 每階段一組計數器（id 由 config.phases 給）
p{id}_consecutive_pass: 0            # 連續通過全量驗證次數
p{id}_total_validations: 0
p{id}_last_result: ""                # PASS / FAIL

# 共用
blocking_issues: 0
stop_condition_met: false            # 註記欄,非觸發器:引擎只認客觀計數器路徑(見 utils.py is_done)
                                     # ❌ agent 自寫 true 不會讓引擎停,且嚴禁用它跳過計數器/blocking
plan_version: 1                      # 規劃書版本(§版本規劃)
framework_ref: ""                    # 本輪跑在哪個框架 commit(快照，供追溯)

# 每輪 agent 回填（震盪偵測用，務必每輪更新）
last_round_mode: ""                  # 推進 / 驗證
last_round_result: ""                # PASS / FAIL / NA（NA=非驗證輪）
last_round_fail_tasks: ""            # 本輪驗證失敗被打回的任務，逗號分隔；PASS 留空

# 震盪/升級（多由外部 loop 維護，agent 只在升級到人類時動 stuck_level/凍結）
rounds_since_progress: 0
stuck_level: 0                       # 0=角色預設 / 1=升一級 / 2=人類
                                     # ⚠️ 由引擎判定並回填;agent 不得自行抬到 2 來凍結/交人
                                     #    (凍結前提見 oscillation-escalation.md：須引擎已判卡死)
current_model_tier: ""               # 引擎回填：fast / normal / thinking（升級鏈如 fast→normal）
enhanced_rounds_used: 0
human_required: false               # true = 卡死已凍結互卡任務，需人類裁決

# ── 樹形模式通訊欄位（僅在啟用樹時使用） ──
tree_reflow_target: ""               # agent 填寫：需要退回修正的葉子節點 ID（逗號分隔）
tree_structure_error: ""             # 觸發旗標:執行期發現結構錯誤(缺葉子/需再拆)時設為 true，引擎據此觸發授權紅線停下交人
                                     # 🚨 引擎只認字面值 true(見 loop.py)，不解析說明文字——故觸發請填 true，
                                     #    證據另寫進一張 BLOCKING Issue(哪個整合驗證項失敗 / 缺哪個葉子 /
                                     #    對照哪條 REQUIREMENTS)。❌ 嚴禁無 Issue 佐證就設 true 來規避執行期苦工;
                                     #    無證據 Issue 的結構錯宣告視為無效。
                                     # 🚨 機械前提(比照 FROZEN,防自抬逃生閥,見 oscillation-escalation.md §E):
                                     #    設 true 前,所引用的整合驗證項【必須】在 last_round_result 歷史中
                                     #    實際出現過 FAIL(或該葉子 reflow_count>0)——光憑散文宣稱「需再拆」不算。
                                     #    ❌ 嚴禁把「這片葉子難做/我做不出來」當「結構缺漏」上報:難 → 繼續做或走
                                     #    升級階梯(換模型),不是設 tree_structure_error。結構錯僅限「客觀缺葉子/
                                     #    整合驗證證明現有葉子拼不出需求」,且須有上述機械 FAIL 訊號佐證。
```

### 設定 vs 狀態（最重要的一刀）
- **門檻 / 階段定義 / 停止條件**(converge_threshold、phases、stall_threshold…)= **設定** → `loop.config.yaml`，**不放 CONTROL**。
- **活計數器**(current_phase、p{id}_*、stuck_level…)= **狀態** → CONTROL.md。
- 同一門檻只在 config 出現一次，避免兩處 drift（也避免 CONTROL 變胖，見 context-budget.md）。

---

## 2. 樹狀模式狀態模型（TREE.md — 活在 `.loop/TREE.md`）
在樹形漸進拆解模式下，整棵樹的拓撲結構與狀態均活在 `.loop/TREE.md`（或 config 指定的 tree path）中。引擎與 agent 通過讀寫此文件來協調工作。

### 樹全局狀態
```yaml
tree_root: root                      # 樹的根節點 ID
```

### 節點欄位（每個節點 `{node_id}` 的獨立區塊）
```yaml
node_{node_id}_state: PENDING        # 節點狀態
node_{node_id}_children: c1,c2       # 子節點 ID（逗號分隔，葉子節點此處留空）
node_{node_id}_parent: root          # 父節點 ID（根節點此處為空）
node_{node_id}_depth: 1              # 節點在樹中的深度（根節點為 0）
node_{node_id}_stable_rounds: 0      # 規劃期子節點集合連續穩定的輪數
node_{node_id}_reflow_count: 0       # 執行期該葉子被退回修復的次數（Breaker 監控點）
```

### 節點生命週期狀態
- **`PENDING`**：待拆解。規劃期中，模型需要對此節點提議子項。
- **`DECOMPOSED`**：已拆解。該中間節點已有子節點，且子節點集合已收斂。
- **`LEAF`**：葉子節點。最小執行單位，自身可獨立執行與單元驗證。
- **`IN_PROGRESS`**：執行中。agent 正在實作該葉子節點。
- **`CONVERGED`**：已收斂/已完成。葉子已驗證通過；或中間節點的所有子節點均已 CONVERGED。
- **`NEEDS_REVISION`**：需要修正。整合驗證失敗被回流退回的葉子。
- **`FROZEN`**：凍結。因 Breaker 撞線或規格衝突被凍結，引擎跳過此節點。

---

## 3. 流程控制（flow — 引擎 + boot 共同驅動，全 config化）

| 機制 | 通用判準（config 驅動） | 由誰執行 |
|------|------------------------|---------|
| **BOOT SEQUENCE** | STEP G→10：一輪【只做一個任務/一次驗證】，STEP 10 後 agent **立即停止輸出並結束 process**（控制權交還引擎，不自行續跑下一輪）；階段數/產出位置/停止條件「依 config」 | agent |
| **Phase Gate (平模式)** | 相鄰階段 i→i+1：`phase i 全 CONVERGED 且 p{i}_pass>=門檻 且 blocking==0` → 進 i+1 | agent |
| **Phase Gate (樹模式)** | **規劃期 → 執行期**：全樹無 `PENDING` 節點且規劃完成 → 暫停進入 **人類 Gate**，人類 review 並批准後，始得進入執行期。 | 引擎 + 人類 |
| **向上解鎖 (樹模式)** | **自底向上解鎖**：中間/父節點在所有子節點皆為 `CONVERGED` 後，方可解鎖為 `CONVERGED`。當根節點為 `CONVERGED` 時，代表任務完成。 | 引擎 |
| **停止(正常)** | `current_phase==最後階段 且 最後階段全任務 CONVERGED 且 p{last}_pass>=final_phase_pass_gte 且 blocking==0`（引擎只認此客觀路徑；`stop_condition_met` 非觸發器） | 引擎 + agent |
| **停止(交人類)** | `human_required==true` 或任何硬 Breaker 撞線 | 引擎 |
| **震盪偵測** | 失敗指紋環狀歷史 + 視窗（門檻全 config） | 引擎（最客觀） |
| **三層升級** | 預設 → 增強 → 人類（門檻/模型全 config） | 引擎切 tier，agent 凍結/開 Issue |
| **Git 守護** | 一輪一 commit + 開機自檢 + 整檔空白兜底還原（只在 code repo） | agent（G0 語意） + 引擎（兜底） |

---

## 4. 引擎讀寫 CONTROL 的方式（context 友善）
- 引擎用單行 `grep`/正則讀寫 CONTROL 的 `key: value`（不載入 LLM context）。
- 引擎**只 parse CONTROL 計數器**，**不 parse log**；log 是給人 `tail -f` 的（見 context-budget.md）。
