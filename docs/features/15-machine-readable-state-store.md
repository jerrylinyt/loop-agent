# Feature 15：可程式化的結構狀態 Store（state.json，吃得下動態產生的 plan）

## Type

Engine + generator + rules + prompts。把「**所有會被用來做判斷的狀態**」從散落在 `CONTROL.md` 的 markdown（表格 / checkbox / yaml 區塊）搬進一個**單一、結構化、可程式化讀寫**的 store（`state.json`）。`CONTROL.md` 退化成由 store **渲染出來的人類視圖**。

> 與 Feature 14 的關係：14 把「扁平 scalar 的寫入路徑」改成 CLI（`set/incr/get`）。**15 修訂 14 的儲存決定**——把 backing store 從「yaml-in-markdown」換成 `state.json`，並把 14 的 CLI 原則延伸到**結構化資料**（任務清單、Issue、樹節點）。14 的「agent 只下指令、不手改檔」總則完全保留，scalar 一併收進 `state.json.control`。

## Goal

1. **凡是引擎/agent 拿來做決策的狀態，一律可程式化讀寫**：任務 status / conv / 依賴、phase 計數器、coverage、Issue 等級與狀態、樹節點——全部進 `state.json`，引擎用 `json.load` 直接判讀，不再 parse markdown、也不再只信 agent 自報的彙總計數器。
2. **吃得下「動態產生」的 plan**：plan 期生出幾個 phase、每個 phase 幾個任務、樹長成什麼形狀都不固定。Store 的 schema 必須**形狀固定、數量動態**（用陣列 + 文件化 schema 表達），而不是把結構壓平成一堆 `key: value`。
3. **agent 永不手寫結構化資料**：plan generator 與執行輪都只透過 `state.py` 的**型別化 CLI 指令**建構 / 變更 store；`CONTROL.md` 由 store 單向渲染（json→md），**絕不反向 parse**。

## Problem

### P1：決策狀態大半活在引擎讀不到的 markdown

`is_done`（`engine/utils.py:264`）只讀 scalar：`p{last}_consecutive_pass >= 門檻` 且 `blocking_issues == 0`。它**沒有驗證「最後 phase 全任務 CONVERGED」**——註解自承這個判斷「由 agent 在 boot STEP 2 做」。也就是說：

- 各 phase 的**任務狀態表**（`| 任務 | Status | Conv | Round |`）、**coverage 表**、**Issue 索引**都是 `1-plan-generator.md` 要求 agent **手寫的 markdown**，引擎完全不 parse。
- 引擎對「全任務是否 CONVERGED」「blocking 有幾個」**只能信 agent 寫進 scalar 的彙總值**。弱 agent 把 scalar 寫對、但底下任務表其實還有 FROZEN/TODO，引擎照樣判 done——這正是 boot-sequence/issues 規則要塞一堆「禁止用驗證刷分遮蔽卡死」防呆的根因：**因為引擎看不到真相，只能用文字規則叫 agent 自律。**

### P2：plan 是動態產生的，markdown 表格扛不動

phase 數、任務數、樹形狀都在 plan 期才生出來。把這種「N 個 phase、每個 M 個任務、每任務多個欄位」塞進 markdown 表格或扁平 `key: value`，造成：

- 引擎要 parse 動態表格 → 脆弱；
- agent 要手維護動態表格的每個 cell → 就是前面幾輪一直在談的「弱 agent 改 cell 改壞」（1/5 變 2/5、+1 變 +2）。

結構化資料就該用結構化格式（JSON 陣列 + schema），這是 dynamic、nested 資料唯一不彆扭的表達。

## 設計總則

> **單一事實來源 = `state.json`（機器決策狀態）。`CONTROL.md` 是它的渲染視圖。任務規格散文留在 `phases/PHASE*.md`。三者職責分離：**
> - `state.json`：引擎判讀 + 驅動所有決策的**結構化狀態**（canonical）。
> - `CONTROL.md`：由 `state.json` 單向渲染的**人類 dashboard**（read-only generated，給人 `tail`/掃、給 agent 開機看全景）。
> - `phases/PHASE*.md`：任務的**做什麼/驗收標準**散文（agent 執行時讀；非狀態）。
>
> **所有寫入只經 `state.py` 型別化 CLI；沒有任何 agent 手寫 `state.json` 或手改 `CONTROL.md` 的狀態。**

---

## state.json Schema（形狀固定、數量動態）

```jsonc
{
  "schema_version": 1,
  "mode": "flat",                 // "flat" | "tree"
  "current_phase": "1",
  "plan_version": 3,
  "framework_ref": "abc123",

  "phases": [                     // 動態：plan 期決定幾個
    {
      "id": "1",
      "name": "需求分析",
      "converge_threshold": 5,
      "consecutive_pass": 2,
      "total_validations": 7,
      "last_result": "PASS",
      "tasks": [                  // 動態：plan 期決定幾個
        {
          "id": "TASK-01",
          "order": 1,             // plan 期定案的硬列序（防挑軟柿子，見 boot-sequence STEP 4）
          "spec_ref": "phases/PHASE1.md#task-01",
          "status": "DRAFTED",    // TODO|DRAFTED|CONVERGED|NEEDS_REVISION|FROZEN
          "conv": 1,
          "threshold": 5,
          "depends_on": ["TASK-00"],
          "verify_method": "re_derive",   // 選配：objective_check|re_enumerate|re_derive|adversarial_review
          "output": "outputs/req.md",
          "last_round": 12
        }
      ],
      "coverage": [
        { "metric": "需求覆蓋", "denominator": "R001..R040", "numerator": 38, "round": 12 }
      ]
    }
  ],

  "issues": [                     // 動態
    { "id": "ISS-01", "level": "BLOCKING", "title": "...", "phase": "1",
      "task": "TASK-03", "status": "OPEN", "round": 9 }
  ],

  "tree": {                       // 只在 mode=="tree" 時存在；動態節點圖
    "root": "root",
    "nodes": {
      "root": { "state": "DECOMPOSED", "children": ["c1","c2"], "parent": null,
                "depth": 0, "stable_rounds": 0, "reflow_count": 0 }
    }
  },

  "control": {                    // 扁平 scalar（Feature 14 的內容收進這裡）
    "last_round_mode": "驗證",
    "last_round_result": "PASS",
    "last_round_fail_tasks": "",
    "rounds_since_progress": 0,
    "stuck_level": 0,
    "current_model_tier": "fast",
    "enhanced_rounds_used": 0,
    "last_safe_sha": "def456",
    "review_invalid_streak": 0,
    "human_required": false,
    "human_required_reason": "",
    "human_required_msg": "",

    // ── 衍生欄位（DERIVED，引擎由上面 primitives 重算，僅作快取／給渲染用）──
    "blocking_issues": 1          // = count(issues[].level=="BLOCKING" && status=="OPEN")
  }
}
```

**Schema 三原則：**

1. **形狀固定、數量動態**：`phase` / `task` / `node` / `issue` 的欄位集合是固定 schema；有幾個由陣列長度表達。動態 plan 完全用「多塞幾筆陣列元素」表達，不需要動 schema。
2. **單一事實來源 + 衍生欄位**：能從 primitives 算出來的（`blocking_issues`、「phase 全 CONVERGED」、「stop 條件成立」）一律**由引擎重算**，不信 agent 寫的快取值（reconcile，見下）。primitive = 各 task.status / issue.level，是真相。
3. **scalar 不再是判斷主體**：`consecutive_pass` 等仍存，但「能不能 +1 / 能不能 done」由引擎對照 task 結構 + 證據檔重新判定，scalar 只是被引擎維護的數字。

---

## state.py 型別化 CLI（延伸 Feature 14）

backing store 改為 `state.json`；`state.py` 從「regex 改單行」升級為「load → 改 dict → 原子 dump」。所有指令帶 `--state <state.json>`（或由 config 解析）。

**scalar（沿用 14）**
```
state.py get   --state S control.<key>
state.py set   --state S control.<key> <value>
state.py incr  --state S control.<phase>.consecutive_pass [--by 1]
```

**任務（新）**
```
state.py task-status --state S --phase 1 --task TASK-01 --to CONVERGED
state.py task-conv   --state S --phase 1 --task TASK-01 (--incr | --reset)
state.py task-add    --state S --phase 1 --id TASK-09 --order 9 --threshold 5 \
                     --depends TASK-08 --output outputs/x.md --spec phases/PHASE1.md#task-09
```

**Issue（新）**
```
state.py issue-add        --state S --id ISS-02 --level BLOCKING --task TASK-05 --title "..."
state.py issue-set-status --state S --id ISS-02 --to RESOLVED
```

**樹（新；取代 TREE.md 的扁平 `node_*` key）**
```
state.py node-set-state --state S --node c1 --to LEAF
state.py node-children  --state S --node root --set c1,c2
state.py node-reflow    --state S --node c1            # reflow_count += 1 + 設 NEEDS_REVISION
```

**渲染 / 查詢（引擎與 dashboard 用）**
```
state.py render-control --state S --out CONTROL.md     # json → md，單向；每次變更後跑
state.py derive         --state S blocking_issues|phase-converged:1|is-done
```

**型別校驗（每個寫指令都先驗）**：status/level 屬列舉、conv/counter 為非負整數、`task-conv --incr` 由程式 +1（弱 agent 灌不進 +2）、未知 phase/task/node id 報錯 `exit 1`、原子寫入（temp + `os.replace`）。**`task-status` 只允許合法單步轉移**（`TODO→DRAFTED`、`DRAFTED→CONVERGED` 且 conv 達門檻、`NEEDS_REVISION→DRAFTED`…；非法跳級 `exit 1`）——把 git-review-gate §2-3「禁狀態跳級」從「事後 LLM 審 + REVERT」**前移成寫入時就擋掉**。

---

## 引擎整合：決策改由 store 衍生（核心 win）

把現在「引擎信 agent 彙總值」的地方，改成「引擎讀結構自己算」：

| 決策 | 現在 | 改後 |
|------|------|------|
| `is_done`（停止） | 只看 `p{last}_consecutive_pass>=門檻 && blocking==0`，**不驗全任務 CONVERGED** | 加驗 `phases[last].tasks` **全 CONVERGED（無 TODO/FROZEN/PENDING/NEEDS_REVISION）**——真相而非自報 |
| Phase Gate | agent 自判後寫 `current_phase` | 引擎可獨立驗證 `phases[i]` 全 CONVERGED 才接受跨 phase |
| `blocking_issues` | 信 scalar | 引擎 = `count(issues OPEN && BLOCKING)`，scalar 只當快取 |
| 計數器 reconcile（Feature 14 後續/前一輪討論） | 無 | 引擎由 `task.status + 證據檔` 算「這輪該 +0/+1」，對不上→可機械修正或 REVERT |

> 效果：boot-sequence / issues / git-review-gate 裡一大堆「禁止用驗證刷分遮蔽 FROZEN 卡死」「禁狀態跳級」的**文字防呆，從此有引擎客觀把關兜底**——agent 自律失效時，引擎讀得到真相。

---

## plan generator 改動（動態建構，不手寫 JSON）

`1-plan-generator.md` 目前要 agent 手寫 CONTROL 的 markdown 表格。改為：

- generator **不手寫 `state.json`**，而是用 `task-add` / `node-children` / `issue-add` 等 CLI **逐筆建構** store（動態數量 = 多次呼叫）。每筆呼叫原子且型別校驗。
- 任務的**散文規格**仍寫進 `phases/PHASE*.md`（不變）；`state.json` 只存該任務的**結構欄位**（id/order/status/conv/threshold/depends/output/spec_ref）。
- diff 模式（需求變更回流）：用 `task-status --to NEEDS_REVISION` + `task-conv --reset` 改受影響任務，`plan_version++`，而非整碗重寫 markdown。
- 建構完跑 `render-control` 生出 `CONTROL.md` 視圖；**Plan Gate（下一輪獨立 context）改為對 `state.json` 做結構校驗**（DAG 無環、每條 R### 有對應 task、order 唯一、stop 條件可由 store 判讀），比審 markdown 更剛性。

---

## CONTROL.md：單向渲染，永不反向 parse

- `CONTROL.md` 全部由 `render-control` 從 `state.json` 生成（狀態表、coverage、Issue 索引、scalar 區、追溯表）。檔頭標 `<!-- GENERATED from state.json — 勿手改，改請用 state.py CLI -->`。
- boot-sequence「每輪必讀 CONTROL.md」維持——agent 讀的是渲染視圖拿全景；但**寫狀態一律走 CLI**，不准編輯 `CONTROL.md`。
- 「文件即狀態」哲學仍成立且更乾淨：新 agent 接手讀 `state.json`（無歧義）+ `CONTROL.md`（人類視圖）。
- Context 友善：引擎 `json.load(state.json)` 在引擎側，不進 LLM context；agent 進 context 的是精簡的渲染視圖，不是原始 json。

---

## 不在本期範圍

- `verify_method` 的對抗式審查機制本身（前面討論的 re_derive vs adversarial_review 路由）——本期只在 schema 預留欄位，行為另案。
- 機械 pre-lint / 統一回復預算（前面討論）——獨立 feature，但本 store 是它們的前提（reconcile、`is-done` 衍生都靠它）。

## Acceptance Criteria

- [ ] `state.json` 為 canonical store，schema 如上；形狀固定、phase/task/issue/node 數量由陣列動態表達。
- [ ] `state.py` 型別化 CLI：scalar + task + issue + node + render + derive 指令可用；列舉/型別/單步轉移/未知 id 校驗生效；`--incr` 由程式算；原子寫入。
- [ ] 引擎 `is_done` 加驗「最後 phase 全任務 CONVERGED」（讀 store，不只信 scalar）；`blocking_issues` 由引擎從 `issues[]` 重算。
- [ ] plan generator 改用 CLI 建構 store + `render-control` 生成 `CONTROL.md`；不手寫 json、不手寫狀態表。
- [ ] `CONTROL.md` 為單向渲染產物，標 GENERATED 警示；任何狀態寫入經 CLI。
- [ ] Plan Gate 改對 `state.json` 做結構校驗（DAG 無環 / R###→task 覆蓋 / order 唯一 / stop 可判讀）。
- [ ] 既有 markdown CONTROL 專案有一次性 `migrate` 路徑（見下）。

## Migration

- 新增 `state.py migrate --control CONTROL.md --out state.json`：best-effort 解析現有 markdown 狀態表/scalar/Issue 索引 → 生成 `state.json`，**結果交 Plan Gate 或人類確認**（一次性、可容錯，因為之後 markdown 不再是真相）。
- 切換後 `CONTROL.md` 由 `render-control` 重生，覆蓋舊手寫版。

## Tests

- **Unit（CLI）**：task-add/status/conv、issue-add/set、node-*、scalar set/incr 正確改 `state.json`；非法狀態轉移 / 未知 id / 型別錯 → `exit 1`；原子寫入後 json 合法非空。
- **Unit（衍生）**：`derive is-done` 在「scalar 達門檻但有 FROZEN/TODO 任務」時回 false（驗證 P1 修復）；`blocking_issues` 重算正確。
- **Unit（render）**：同一 `state.json` 渲染 `CONTROL.md` 為決定性、可重入（render 兩次結果一致）。
- **Integration**：mock 一個動態 plan（2 phase、不同任務數、樹模式各一）→ CLI 建構 → 引擎讀 store 跑 gate/stop 決策正確；markdown 視圖與 store 一致。
- **Migration**：拿現有範例 CONTROL.md → migrate → 結構等價。

## Rollout

1. 落 `state.json` schema + `state.py` 改 JSON backing + 型別化 CLI（含 render/derive）。先讓引擎能讀能渲染，行為與舊 scalar 等價。
2. 把 `is_done` / blocking / phase gate 切到 store 衍生（這步才拿到 P1 的真相把關）。
3. 改 plan generator 用 CLI 建構 + Plan Gate 改結構校驗。
4. 提供 `migrate`，切換既有專案；`CONTROL.md` 轉為渲染產物。
5. dashboard（`dashboard/app.py`）可改讀 `state.json`（結構化，比 parse markdown 更穩）——順帶受惠，另案。
