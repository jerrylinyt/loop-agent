# 🗺️ 全流程詳細流程圖（init → plan → gate → execute → 收斂）

> 對照原始碼逐一畫出的**完整邏輯判斷圖**：`init-project.py` → `run.py` → `plan_loop.py` → 人類 gate → `loop.py` → 終止狀態。
> 拆成 6 張圖（總覽 + 5 張細節圖），因為單一巨圖會擠爆版面；每張圖的節點文字盡量對齊程式碼裡的變數名，方便對照原始碼。
> 所有門檻數字（`stall_threshold=6` 等）皆為 [`engine/config.py`](../engine/config.py) `DEFAULTS` 的預設值，實際專案可在 `loop.config.yaml` 覆寫。
> 用 GitHub / VS Code（Markdown Preview Mermaid Support 外掛）/ [Mermaid Live Editor](https://mermaid.live) 皆可直接渲染。

---

## 圖 1／6：總覽（init → 兩個人類 gate → 終止）

```mermaid
flowchart TD
    A["人類想用框架做一個大任務"] --> B["python init-project.py &lt;repo&gt; --name &lt;ws&gt;<br/>建立 .loop/&lt;ws&gt;/ 骨架<br/>(REQUIREMENTS 樣板 + loop.config.yaml + framework_path)"]
    B --> C{"REQUIREMENTS.md 怎麼填？"}
    C -->|人類自填樣板| D["人類直接編輯 REQUIREMENTS.md"]
    C -->|agent 互動訪談| E["generators/0-requirements-interview.md<br/>agent 訪談產出草稿"]
    D --> F(("🧑 Gate #1<br/>人類確認需求"))
    E --> F
    F --> G["python run.py<br/>(--mode 預設取 config.generation.mode)"]
    G --> H{"--stage?"}
    H -->|"plan"| I1["只跑 run_plan('gated')，不接執行"]
    H -->|"execute"| I2["只跑 run_exec()<br/>(gated 模式人類 review 完用這個)"]
    H -->|"reset-plan"| I3["清空 state.json 的 plan/phases、<br/>刪 phases/*.md、補一個還原點 commit，<br/>立即重跑規劃迴圈(gated)"]
    H -->|"reset-execute-state"| I4["保留規劃書，只把執行進度<br/>重置回指定 phase/task"]
    H -->|"all（預設）"| J{"mode?"}
    J -->|"gated（預設）"| K["run_plan('gated')"]
    J -->|"auto"| K
    K --> L[["進入 Plan Loop<br/>（見圖 2）"]]
    L --> M{"Plan Loop 結果？"}
    M -->|"human_required"| M1(("🧑 停下<br/>人類裁決規劃書"))
    M -->|"未在 max_rounds(30) 內收斂"| M1
    M -->|"converged"| N{"mode?"}
    N -->|"gated"| O(("🧑 Gate #2<br/>人類 review<br/>loop.config.yaml / state.json / phases/"))
    O --> P["人類手動執行：<br/>run.py --stage execute"]
    N -->|"auto"| Q["run.py 自動接：run_exec()"]
    P --> R[["進入 Execute Loop<br/>（見圖 3）"]]
    Q --> R
    R --> S{"Execute Loop 結果？"}
    S -->|"complete"| T(("✅ LOOP COMPLETE"))
    S -->|"human_required（多種原因，見圖 3/5）"| U(("🧑 停下交人裁決"))
    S -->|"max_rounds(600) 用盡"| U
```

**讀圖重點**：兩個人類 gate 之間全部自動；`--stage` 是逃生/重跑用的旁路指令，正常首跑走 `all`。

---

## 圖 2／6：Plan Loop 內部（`plan_loop.py`，Round A 生成 + Round B 獨立審查）

```mermaid
flowchart TD
    PA[["Plan Cycle i 開始"]] --> PB{"外部停止旗標被觸發，<br/>或 plan_status==converged？"}
    PB -->|"converged"| PZ["break → 對圖1回報 converged"]
    PB -->|"停止旗標"| PSTOP(("stopped"))
    PB -->|否| PC0{"plan_human_required==true？"}
    PC0 -->|是| PH(("🧑 human_required<br/>停止交人"))
    PC0 -->|否| PC["select_model('plan', plan_stuck_level)<br/>依卡住階梯選模型"]
    PC --> PD["Round A 生成：全新 context agent<br/>讀 REQUIREMENTS，(重)推導<br/>loop.config.yaml / CONTROL.md / phases/*.md"]
    PD --> PE{"Round A 被 watchdog kill？"}
    PE -->|是| PE1["視為無進展：rounds_since+1<br/>記錄 result=NA，直接進下一個 cycle"]
    PE1 --> PA
    PE -->|否| PF["git_guard：補 autocommit"]
    PF --> PG["changed = plan_files_changed()<br/>（.loop/ 下規劃書檔本次是否被實質改動，<br/>排除 state.json / log）"]
    PG --> PI["Round B 審查：另一個全新 context agent<br/>（review 模型）唯讀跑 Plan Gate，<br/>禁止修改規劃書檔"]
    PI --> PJ{"Round B 被 watchdog kill？"}
    PJ -->|是| PJ1["gate = None（視為無進展）"]
    PJ -->|否| PK["gate = plan_gate_last（PASS / FAIL）"]
    PJ1 --> PL
    PK --> PL{"stable =<br/>(規劃書本輪未變動) AND (gate==PASS)？"}
    PL -->|是| PM["plan_stable_rounds += 1<br/>plan_rounds_since_progress = 0<br/>若原本卡住 → 解除、換回角色預設模型"]
    PL -->|否| PN["plan_stable_rounds = 0<br/>plan_rounds_since_progress += 1"]
    PM --> PO{"plan_stable_rounds >=<br/>plan_converge_threshold（預設 2）？"}
    PO -->|是| PZ2["plan_status = converged<br/>✅ PLAN CONVERGED"]
    PO -->|否| PS["sleep(interval_seconds) → 下個 cycle"]
    PZ2 --> PZ
    PN --> PQ{"plan_stuck_level==0 AND<br/>rounds_since >= stall_threshold（6）？"}
    PQ -->|是| PQ1["⬆ plan_stuck_level=1<br/>升級模型（decompose tier1）"]
    PQ -->|否| PR{"plan_stuck_level>=1 AND<br/>rounds_since >= stall_threshold+enhanced_max_rounds<br/>（6+8=14）？"}
    PR -->|是| PR1["plan_human_required=true<br/>plan_status=stuck_human<br/>⛔ 停止交人"]
    PR -->|否| PS
    PQ1 --> PS
    PR1 --> PH
    PS --> PA
```

**讀圖重點**：Round A（生成）與 Round B（審查）永遠是**兩個不同 context 的 agent**——生成的人不能自己審自己；「規劃書沒改 + Gate PASS」連續 2 次才算收斂，任何一次改動或 FAIL 都讓穩定計數歸零重數。

---

## 圖 3／6：Execute Loop 內部（`loop.py`，單一一輪的完整生命週期）

```mermaid
flowchart TD
    EA[["Round i 開始"]] --> EB{"check_stop_requested？<br/>（外部人類請求停止旗標）"}
    EB -->|是| EB1(("broken_control_file<br/>停止"))
    EB -->|否| EC["rotate_log_if_needed"]
    EC --> ED{"STEP G：inspect_and_fix_blank<br/>主控檔健康？（非空、有標題）"}
    ED -->|"壞了且無法自動修復"| ED1["set human_required=true<br/>code=broken_control_file"]
    ED1 --> ZH
    ED -->|"OK，或已用 git checkout 自動還原"| EE["touch_run_lock（鎖心跳）<br/>sync_framework_docs（同步框架文件快照）"]
    EE --> EF[["Git Review Gate<br/>（見圖 4）"]]
    EF --> EG{"Gate 回傳？"}
    EG -->|"halt_reason 非空<br/>（FATAL_STATE 或連續產不出合法判決）"| EG1["set human_required=true"]
    EG1 --> ZH
    EG -->|"passed=false<br/>（本輪已 REVERT）"| EG2["跳過本輪執行，<br/>下一輪先提醒剛剛被自動 revert"]
    EG2 --> EA
    EG -->|"passed=true"| EH{"is_done(state)？<br/>current_phase==最後階段 AND<br/>p{last}_consecutive_pass>=門檻 AND<br/>blocking_issues==0 AND<br/>（平模式）最後階段全任務 CONVERGED"}
    EH -->|是| EH1(("✅ complete<br/>LOOP COMPLETE"))
    EH -->|否| EI{"human_needed(state)？<br/>（human_required==true）"}
    EI -->|是| EI1["回填 human_required_code<br/>（若 agent 沒填，補 agent_requested）"]
    EI1 --> ZH
    EI -->|否| EJ["stuck_level = control.stuck_level<br/>select_model('execute', stuck_level)<br/>→ fast(0) / normal(1) / thinking(2)"]
    EJ --> EK["組 prompt = base_prompt<br/>+（若 stuck_level>=1）escalation_prompt<br/>渲染 run_id + round（給一輪一任務配額用）"]
    EK --> EL["啟動全新無狀態 agent subprocess<br/>watchdog：round_timeout=3600s / idle_timeout=1800s"]
    EL --> EM[["agent 內部 Boot Sequence STEP 0~10<br/>（見圖 6）"]]
    EM --> EN{"被 watchdog kill？"}
    EN -->|是| EN1["last_round_result=NA<br/>last_round_mode=中斷"]
    EN -->|否| EO["讀 agent 用 state.py 寫回的<br/>last_round_mode / last_round_result"]
    EN1 --> EP
    EO --> EP["git_guard：若 agent 忘記 commit，<br/>引擎補一個 autocommit"]
    EP --> EQ[["update_stuck_state：<br/>震盪 / 卡住偵測與三層升級<br/>（見圖 5）"]]
    EQ --> ER{"hard_stop？"}
    ER -->|是| ER1["set human_required=true<br/>code=stuck_level_2_hard_stop"]
    ER1 --> ZH
    ER -->|否| ES["append_round_record：<br/>把本輪結果落一筆到 rounds.jsonl<br/>（trace，供圖表與 Loop4 分析用）"]
    ES --> ET["sleep(interval_seconds)"]
    ET --> EU{"i >= max_rounds（600）？"}
    EU -->|是| EU1["set human_required=true<br/>code=max_rounds_reached"]
    EU1 --> ZH
    EU -->|否| EA
    ZH(("🧑 human_required<br/>停止交人，等待 resume"))
```

---

## 圖 4／6：Git Review Gate 細節（`run_git_review_gate`）

```mermaid
flowchart TD
    GA[["Git Review Gate 啟動"]] --> GB["current_head = git rev-parse HEAD"]
    GB --> GC{"last_safe_sha 是否為空？<br/>（本 workspace 第一次執行）"}
    GC -->|是| GC1["set last_safe_sha=current_head<br/>→ PASS（本輪略過審查）"]
    GC -->|否| GD{"last_safe_sha == current_head？<br/>（比對至少 4 碼）"}
    GD -->|是| GD1["→ PASS（自上次以來無新 commit）"]
    GD -->|否| GE["diff = git diff last_safe_sha current_head"]
    GE --> GF{"diff 是否為空？"}
    GF -->|是| GF1["set last_safe_sha=current_head<br/>→ PASS"]
    GF -->|否| GG["啟動獨立 review agent（review 模型）<br/>讀 diff + state.json + 控制檔內容，<br/>唯讀，只准輸出 JSON 判決"]
    GG --> GH{"JSON 判決格式合法？<br/>verdict ∈ {PASS,REVERT,FATAL_STATE}<br/>AND checklist 恰 13 項<br/>AND 每個 FLAG 項目都附 evidence"}
    GH -->|不合法| GI["review_invalid_streak += 1"]
    GI --> GJ{"streak >= enhanced_max_rounds（8）？"}
    GJ -->|是| GJ1["→ human_required<br/>（Git Review Gate 連續 8 次產不出合法判決）"]
    GJ -->|否| GJ2["本輪判定為『尚未判定』，<br/>不執行任務，下一輪重試"]
    GH -->|合法| GK["review_invalid_streak = 0"]
    GK --> GL{"verdict？"}
    GL -->|PASS| GL1["set last_safe_sha=current_head<br/>→ PASS，繼續本輪任務"]
    GL -->|FATAL_STATE| GL2["→ human_required<br/>（狀態被判定為不可逆毀損）"]
    GL -->|REVERT| GM["git revert --no-edit last_safe_sha..current_head"]
    GM --> GN{"revert 是否成功？"}
    GN -->|是| GN1["記錄 review_revert 事件<br/>→ 本輪不執行任務，下輪重試"]
    GN -->|否| GN2["revert --abort<br/>reset --hard last_safe_sha（回到已驗證過的還原點）<br/>clean -fd<br/>（框架唯一允許的重置場景：<br/>回退到自己認證過的 commit，不是任意丟棄）"]
    GN2 --> GN1
```

---

## 圖 5／6：震盪 / 卡住偵測與三層升級狀態機（`update_stuck_state`）

```mermaid
flowchart TD
    SA[["本輪結束，讀 last_round_mode / last_round_result"]] --> SB{"progressed？<br/>current_phase 是否推進，<br/>或 consecutive_pass 是否提升？"}
    SB -->|是| SC["rounds_since_progress=0<br/>清空失敗指紋歷史<br/>若 stuck_level≠0：換回角色預設模型<br/>stuck_level=0，enhanced_used=0<br/>human_required=false（resume）"]
    SB -->|否| SD{"is_fail_verify？<br/>（未被 kill AND mode 含「驗證」<br/>AND result==FAIL）"}
    SD -->|是| SE["rounds_since_progress += 1<br/>記錄失敗指紋 =<br/>hash(排序後失敗任務 + 排序後改動檔案)<br/>若 stuck_level==1：enhanced_used += 1"]
    SD -->|否| SF{"no_activity 且 stuck_level==1？<br/>no_activity=max(連續無新進度簽章輪數,<br/>連續被 watchdog kill 輪數)"}
    SF -->|是| SG["enhanced_used += 1<br/>（純推進但空轉，一樣算增強模型用量）"]
    SF -->|否| SH["NA 輪：純推進、本輪未做客觀驗收，<br/>不累計失敗指紋"]
    SC --> SI
    SE --> SI
    SG --> SI
    SH --> SI["彙總三個訊號：<br/>oscillating = 失敗指紋近 osc_window(8)輪內<br/>只落在 ≤osc_distinct_max(3) 種、且有重複<br/>idle_stalled = no_activity >= stall_threshold(6)<br/>fail_stalled = rounds_since_progress >= stall_threshold(6)"]
    SI --> SJ{"stuck_level==0 AND<br/>(oscillating OR fail_stalled OR idle_stalled)？"}
    SJ -->|是| SK["⬆ Lv0→Lv1：stuck_level=1<br/>升級模型（normal/thinking，依 config）<br/>enhanced_used 歸零重算<br/>prompt 注入『先判根因』"]
    SJ -->|否| SL{"stuck_level==1 AND<br/>enhanced_used >= enhanced_max_rounds（8）？"}
    SL -->|是| SM["⬆⬆ Lv1→Lv2：stuck_level=2<br/>升級到最終模型（thinking）<br/>下一輪 prompt 要求 agent<br/>開 BLOCKING Issue 並 FREEZE 互卡任務"]
    SL -->|否| SN{"stuck_level==2 AND<br/>max(rounds_since_progress, no_activity)<br/>>= stall_threshold+human_stop_after（6+4=10）？"}
    SN -->|是| SO["⛔ 硬性保險觸發：<br/>hard_stop=true<br/>（升到人類等級的模型後仍卡，不再等）"]
    SN -->|否| SP["維持現有 stuck_level，<br/>寫回 control 的所有計數器欄位"]
    SK --> SP
    SM --> SP
    SO --> SQ(("回傳 hard_stop=true<br/>→ loop.py 觸發 human_required 停機"))
    SP --> SR(("回傳給 loop.py，<br/>本輪正常結束，進入下一輪"))
```

> **角色維 vs 升級維（同一組模型的二維調度）**：`select_model` 順風時按角色給模型（拆解用 thinking／review 用 normal／執行用 fast），
> 卡住時則沿 `stuck_level` 這把梯子往上爬（fast→normal→thinking→人類），兩套邏輯共用同一份模型清單。

---

## 圖 6／6：Agent 內部 Boot Sequence（每輪被喚醒後，agent 自己要走的步驟）

> 這段跑在圖 3 的 `EM`（agent 內部 STEP 0~10）節點裡，由 agent 自己的 prompt 規定，`loop.py` 只負責啟動/監看/收尾。

```mermaid
flowchart TD
    BG["STEP G：Git 完整性自檢<br/>主控檔是否被寫壞（空白/缺標題）？<br/>→ git checkout HEAD -- 該檔 還原"] --> B0["STEP 0：只讀 state.json 全文<br/>（不先讀分檔或原始資料）"]
    B0 --> B1["STEP 1：讀計數器與當前階段"]
    B1 --> B2{"STEP 2：停止條件成立？<br/>（含 human_required）"}
    B2 -->|是| B2E["輸出完成/求救信號，結束"]
    B2 -->|否| B3{"STEP 3：階段門條件滿足？<br/>（前一階段全 CONVERGED 且<br/>consecutive_pass>=門檻 且 blocking==0）"}
    B3 -->|是| B3A["用 state.py 推進 current_phase+1<br/>（只能 +1，不可跳級或倒退）"]
    B3 -->|否| B4
    B3A --> B4["STEP 4：從狀態表挑<br/>『第一個未完成且非 FROZEN』的<br/>唯一一個任務<br/>🚨 一輪一任務：挑到第一個就停止挑選"]
    B4 --> B5["STEP 5：只開對應分檔的那一節，<br/>讀本輪任務規格"]
    B5 --> B6["STEP 6：只讀該任務宣告依賴的少數檔"]
    B6 --> B7{"STEP 7：執行<br/>局部編輯優先、寫完讀回確認"}
    B7 -->|"意外把檔案寫壞且未 commit"| B7X["git checkout -- 該檔 還原，重做"]
    B7X --> B7
    B7 -->|正常完成| B8["STEP 8：產出落地；<br/>若發現前人錯誤 → 修正 + 寫修正記錄"]
    B8 --> B9["STEP 9：用 state.py CLI 更新 state.json<br/>（狀態轉移合法性由 CLI 校驗把關，<br/>見前一份簡報的『狀態不准自己改』章節）<br/>並回填 last_round_mode / last_round_result /<br/>last_round_fail_tasks（供圖 5 震盪偵測用）"]
    B9 --> BC["STEP C：git add -A && git commit<br/>（本輪還原點）"]
    BC --> B10["STEP 10：寫一筆執行日誌；<br/>🚨 立即停止輸出、結束 process（Stop/Exit）<br/>控制權交還外部迴圈<br/>❌ 嚴禁自行續跑下一輪或多輸出總結"]
```

---

## 名詞對照表（圖裡縮寫 ↔ 白話）

| 圖裡出現的詞 | 白話 |
|---|---|
| `stuck_level` | 卡住等級：0=正常、1=已升級模型、2=已升到最終模型仍卡 |
| `rounds_since_progress` | 連續幾輪沒有「階段推進」或「驗證通過次數提升」 |
| `no_activity` | 連續幾輪「進度簽章」完全沒變（含被 watchdog kill 的次數） |
| `fail_fingerprint` | 本輪失敗任務 + 改動檔案的 hash，用來認出「同一種卡法反覆出現」 |
| `oscillating` | 失敗指紋在一個滑動視窗內反覆落在少數幾種上（改 A 壞 B 的訊號） |
| `enhanced_used` | 升級模型後，已經在這個等級試了幾輪 |
| `plan_stable_rounds` | 規劃書連續幾個 cycle「沒被改動 + Gate PASS」 |
| `last_safe_sha` | Git Review Gate 認證過、可以安全回退到的 commit |
| `human_required` / `plan_human_required` | 停機交人的旗標，一旦 true 只能靠人類的 resume 管道解除 |

---

> 對應原始碼：[`engine/run.py`](../engine/run.py) · [`engine/plan_loop.py`](../engine/plan_loop.py) · [`engine/loop.py`](../engine/loop.py) · [`engine/utils.py`](../engine/utils.py) · [`engine/state.py`](../engine/state.py) · [`rules/boot-sequence.md`](../rules/boot-sequence.md) · [`rules/BLUEPRINT.md`](../rules/BLUEPRINT.md)
