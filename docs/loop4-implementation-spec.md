# 📐 Loop 4 實作規格（給實作 agent 的單一事實來源）

> **這份文件是什麼**：[loop4-harness-hill-climbing.md](loop4-harness-hill-climbing.md)（規劃書/為什麼）的**實作層**規格——把「做什麼、檔在哪、函式長怎樣、schema 是什麼、怎麼驗收」釘死，讓實作 agent **不需重新設計需求**、照做並驗證即可。
> **動的範圍**：**只動本框架 repo**（`engine/` 新增 `collect_traces.py`、`engine/loop.py`/`plan_loop.py` 補一個 `run_id` 欄位、`maintenance/` 新增分析 prompt）。**絕不動任何下游 code repo。**
> **批次**：0（前置）→ 1（收集器）→ 2（聚合指標）→ 3（分析 agent prompt）→ 4（人類 gate + 迴歸）。**逐批驗收,通過才進下一批。**

---

## 0. 共用硬性限制（違反即重做）

🚨 **強制約束**：
1. **對下游唯讀**：讀下游 `<repo>/.loop/<ws>/.loop_state/` 一律唯讀；下游缺檔/壞檔 → skip 該 ws 記 warning，**絕不寫入下游、絕不中斷**。產出只落本框架 repo。
2. **Propose-only**：批次 2/3 **絕不**自動改 `rules/` `prompts.yaml` `config.py`、**絕不** auto-commit/push 框架主幹。提案只寫進 `maintenance/proposals/`。❌ 嚴禁程式裡存在任何「自動套用提案」的路徑。
3. **留證據才算數**：任何「痛點」「候選」「提案」都**必須附出處**（`run_id` 清單 + 指紋/數值 + 次數）。無證據的項目不得出現在 `summary.json` 的 `cross_project_candidates` 或 proposals。
4. **跨專案重複才升級**：只有「≥ K 個**不同 repo**都出現」的痛點才標 `meets_K=true`（K 預設 2，可 `--k` 覆蓋）。單一 repo 的痛點保留但標 `meets_K=false`，**不得**成為改框架的提案依據。
5. **不新增相依**：純標準庫，沿用 [engine/state.py](../engine/state.py) 的讀檔風格與 [engine/config.py](../engine/config.py) 的 YAML 處理。前端/儀表板不在本期範圍。
6. **批次 0 零行為改動**：`rounds.jsonl` 寫入維持 best-effort（寫失敗照常跑），**不得改任何控制流程或回傳碼**。
7. **只有人明確要求才 commit/push**：先在工作區改、驗證、回報。

---

## 1. 共用資料契約（schema——收集器、分析 agent、未來 dashboard D3 都吃這份）

### 1.1 `rounds.jsonl` 每行（批次 0 之後；基礎欄位見 [engine-rounds-history.md](engine-rounds-history.md)）
本規格**只新增一個欄位**到既有 schema：

| 欄位 | 型別 | 來源 | 說明 |
|------|------|------|------|
| `run_id` | string | 見 §2 | **跨重啟唯一**的單次程序執行鍵。`round` 會隨重啟歸零、不可當鍵；聚合一律以 `run_id` 區分「一次執行」。 |

> 其餘欄位（`ts/round/loop_type/phase/leaf/result/mode/killed/stuck_level/rounds_since_progress/enhanced_rounds_used/no_activity/consecutive_pass/progressed/model_tier`）一字不改,語意以 [engine-rounds-history.md](engine-rounds-history.md) 為準。

### 1.2 `snapshot.jsonl` 每行（收集器產出 = rounds 行 + 注入來源）
```jsonc
{ ...rounds.jsonl 原行所有欄位...,
  "repo": "loop-fixture-a",      // 下游 repo basename（來自 index.md 解析）
  "ws":   "default",             // workspace 名
  "repo_path": "/abs/path/repo"  // 下游 repo 絕對路徑（稽核用,不含任何原始碼/需求內文）
}
```
> 🚨 snapshot **只含結構化欄位**（phase id / 計數 / 指紋 hash / 模型 tier / 路徑）——**不得**夾帶任何下游原始碼、需求內文、CONTROL 全文。天然適合跨專案聚合。

### 1.3 `summary.json`（收集器產出 = 機械式指標 + 跨專案候選）
```jsonc
{
  "generated_at": "2026-06-27 23:10:00",
  "snapshot": "maintenance/trace-snapshots/2026-06-27/snapshot.jsonl",
  "k": 2,
  "totals": { "repos": 2, "workspaces": 3, "runs": 5, "rounds": 412 },
  "metrics": {
    "escalation_rate":      { "overall": 0.18, "by_phase": {"1": 0.05, "2": 0.31}, "evidence_runs": ["..."] },
    "watchdog_kill_rate":   { "overall": 0.07, "by_reason": {"idle": 0.06, "timeout": 0.01}, "evidence_runs": ["..."] },
    "oscillation_hotspots": [ { "fingerprint": "ab12…", "count": 9, "repos": ["a","b"], "runs": ["..."] } ],
    "non_converging_streaks": { "max": 14, "p95": 8, "evidence_runs": ["..."] },
    "enhanced_ineffective":  [ { "run_id": "…", "repo": "a", "phase": "2", "enhanced_rounds_used": 6, "still_stuck": true } ],
    "pass_reset_rate":       { "overall": 0.22, "by_phase": {"2": 0.4}, "evidence_runs": ["..."] }
  },
  "cross_project_candidates": [
    { "signal_key": "oscillation:ab12…", "kind": "oscillation_hotspot",
      "distinct_repos": 2, "count": 9, "meets_K": true,
      "prelabel": "HARNESS_DEFECT_CANDIDATE",          // 或 SPEC_CONFLICT_SUSPECT
      "evidence": { "repos": ["a","b"], "runs": ["…","…"], "fingerprint": "ab12…" } }
  ]
}
```
> `cross_project_candidates` 是批次 2 的**核心產出**：批次 3 的分析 agent 只信這份的 `meets_K=true` 項目當「可改框架」的起點。

---

## 2. 批次 0（前置）：`rounds.jsonl` 補 `run_id`

> 依賴：本批讓批次 1+ 有「跨執行唯一鍵」可聚合。**先做完批次 0,讓 fixture 能產出帶 `run_id` 的 rounds.jsonl,才驗得了批次 1。**

### 0-1　每次程序啟動生成 `run_id` 並寫進每一行
- **現況**：[engine-rounds-history.md](engine-rounds-history.md) 的 `round` 隨重啟從 1 重來,無跨執行唯一鍵。`rounds.jsonl` 寫入本身**也尚未實作**（須先依該 spec 落地）。
- **需求**：
  - 在 `loop.py` / `plan_loop.py` 的迴圈**啟動處生成一次** `run_id`,格式 `"{repo_basename}:{ws}:{start_epoch}"`（`start_epoch` = `int(time.time())`）。同一次程序執行內固定不變,寫進該執行每一行 rounds。
  - 重啟（新程序）= 新 `run_id`（語意上即「另一次執行」,正確）。
  - 寫 rounds 行的工具函式（依 engine-rounds-history.md §1,落在 [engine/state.py](../engine/state.py) 旁,如 `append_round(cfg, run_id, **fields)`）統一補上 `run_id`。
- **驗收**：跑 fixture 兩次(中途中斷重啟一次),`rounds.jsonl` 內 `run_id` 出現兩個不同值,各自的 `round` 都從小數重新起算;同一執行內 `run_id` 全相同。

### 0-2　`loop_type:"plan"` 不可省略
- **現況**：規劃迴圈的卡死/震盪同樣是 harness 痛點來源。
- **需求**：`plan_loop.py` 的每輪也 append rounds 行,`loop_type="plan"`（執行線性 = `"execute"`、樹 = `"tree"`）。plan 沒有的欄位（如 `leaf`）填 `null`。
- **驗收**：跑一次 `--stage plan` 的 fixture,`rounds.jsonl` 出現 `loop_type:"plan"` 的行,且含 `run_id`。

---

## 3. 批次 1：收集器 `engine/collect_traces.py`（純 Python,唯讀,離線）

> 一次交付一支 CLI。**全程唯讀下游**,產出只落框架 repo。回傳碼恆為 0（best-effort;發現問題印 warning 不 raise）。

### 1-1　從 `~/.loop/index.md` 發現所有 workspace
- **現況**：[engine/loop.py](../engine/loop.py) 結束時 upsert 一行到 `~/.loop/index.md`（key = `repo + workspace`）;目前無人消費。
- **需求**：解析 `~/.loop/index.md`（`--index` 可覆蓋路徑),取出每筆的 `repo 路徑 + workspace`,定位 `<repo>/.loop/<ws>/.loop_state/`。解析失敗的單行 skip + warning,不整批中止。
- **驗收**：兩個 fixture repo 都在 index.md 後,收集器 stdout 報「發現 2 repos / 3 workspaces」（數字依 fixture）。

### 1-2　讀每個 ws 的 trace（唯讀）
- **需求**：每個 ws 讀 `rounds.jsonl`（逐行 `json.loads`,壞行 skip+warning）;另讀 `fail_history`、`progress`（[engine/state.py](../engine/state.py) 既有格式）作為震盪/進度的補充訊號。**不讀** CONTROL 全文（只在需要時取個別計數器,且不寫進 snapshot 內文）。
- **驗收**：某 ws 的 `rounds.jsonl` 含一條壞行(非法 JSON),收集器 skip 該行、其餘照收,回傳碼仍 0,warning 印出壞行所在 ws+行號。

### 1-3　產出 `snapshot.jsonl`
- **需求**：把所有 ws 的 rounds 行合併,逐行注入 `repo / ws / repo_path`(§1.2),寫到 `maintenance/trace-snapshots/<YYYY-MM-DD>/snapshot.jsonl`(`--out` 可覆蓋目錄)。**不得**寫入任何下游原始碼/需求內文。
- **驗收**：snapshot.jsonl 行數 = 各 ws rounds 有效行數總和;每行都有 `run_id/repo/ws`;grep 不到任何下游原始碼片段。

### 1-4　CLI 與回傳碼
- **需求**：
  ```bash
  python engine/collect_traces.py \
      [--index ~/.loop/index.md] [--out maintenance/trace-snapshots/<date>/] \
      [--k 2] [--since YYYY-MM-DD]
  ```
  `--since` 依 `ts` 過濾(只收該日期起的輪)。stdout 印 totals 與每個 metric 的一行摘要。**回傳碼恆 0**(best-effort;真正致命如 `--out` 不可寫才回非 0)。
- **驗收**：`--since` 設未來日期 → snapshot 為空、summary `totals.rounds=0`、回傳碼 0、不報錯。

---

## 4. 批次 2：機械式聚合指標 → `summary.json`（純 Python,放在收集器內）

> 先算數、再讓模型解讀。批次 2 把 §1.3 的每個 metric 算出來,並產 `cross_project_candidates`。每個數字都要能回溯到 `run_id`。

### 2-1　六項痛點指標
- **需求**：依 §1.3 `metrics` 算出六項,每項附 `evidence_runs`：
  | 指標 | 算法 |
  |---|---|
  | `escalation_rate` | `stuck_level≥1` 輪數 / 總輪數,另按 `phase`(或 `leaf`)分群 |
  | `watchdog_kill_rate` | `killed in {timeout,idle}` 輪數 / 總輪數,按 reason 分群 |
  | `oscillation_hotspots` | 跨所有 ws 統計 `fail_history` 指紋的重複次數,列出 count≥2 的指紋及其 repos/runs |
  | `non_converging_streaks` | 每個 run 內 `progressed=false` 的最長連續長度;報 max 與 p95 |
  | `enhanced_ineffective` | `enhanced_rounds_used` 偏高(≥ config `oscillation.enhanced_max_rounds` 的一半)且其後仍 `progressed=false` 的 run/phase |
  | `pass_reset_rate` | `consecutive_pass` 由 >0 掉回 0 的次數 / phase 出現輪數 |
- **驗收**：用「已知答案」的 fixture(手工編造 rounds)驗算:每項指標數值與 evidence_runs 與手算一致。

### 2-2　跨專案候選 + 預標分類（🚨 核心,對映硬約束 §0.4 / §0.5）
- **需求**：把指標歸併成 `signal_key`(如 `oscillation:<fp>`、`kill_idle:phase2`),統計**不同 repo 數** `distinct_repos`：
  - `meets_K = distinct_repos >= k`。
  - **預標 `prelabel`**(供分析 agent 起步,非定論)：`enhanced_ineffective` 來源的 signal → `SPEC_CONFLICT_SUSPECT`(疑規格矛盾,不該改框架);其餘跨專案重複的 → `HARNESS_DEFECT_CANDIDATE`。
  - 每個候選附 `evidence`(repos/runs/指紋或數值)。
- **驗收**：
  - 造「同一指紋出現在 2 個不同 repo」的 fixture → 該候選 `meets_K=true`、`distinct_repos=2`。
  - 造「同一指紋只在 1 個 repo 出現 9 次」→ `meets_K=false`(次數高也不升級,證明 §0.4 是「跨 repo」不是「次數」)。
  - 造 `enhanced_ineffective` 來源 → `prelabel=SPEC_CONFLICT_SUSPECT`。

---

## 5. 批次 3：分析 agent prompt → `maintenance/trace-driven-analysis.md`（新檔,文字交付物）

> 這是一份**冷啟動自足的 prompt**(風格對齊既有 [rule-loophole-audit.md](../maintenance/rule-loophole-audit.md))。實作 agent 依本節**把這份 prompt 寫出來**;它本身不寫程式,只規範「分析 agent 被呼叫時該做什麼」。

### 3-1　prompt 必含的段落（缺一不可）
- **現況**：既有 `rule-loophole-audit.md` 是「想像弱模型怎麼鑽」(無數據)。
- **需求**：新 prompt 須含以下段落,且明確標注**唯讀、只產提案、不改任何檔**：
  1. **身分與最高指導原則**：複用框架六條宗旨(同 rule-loophole-audit.md §1),外加「**這輪靠真實 trace 證據,不是想像**」。
  2. **輸入**：`maintenance/trace-snapshots/<date>/summary.json`(指標+候選)+ 框架現況(`rules/*.md`、`engine/prompts.yaml`、`engine/config.py` DEFAULTS)。**不必**讀整包 snapshot.jsonl(防 context 爆;§0.5 精神)。
  3. **歸因**：把每個 `meets_K=true` 候選,對應到**具體該改的 harness 檔:行**(哪條 rule 措辭縫 / 哪個 prompt 漂移 / 哪個 config 門檻)。
  4. **分類覆核**(🚨)：覆核 Python 的 `prelabel`,把每個候選定為 `HARNESS_DEFECT`(可硬化)或 `SPEC_CONFLICT_SUSPECT`(疑規格矛盾,**只標示、不提框架改動**,交人)。判斷依據要寫出來。
  5. **過濾**：`meets_K=false` 的一律**不提框架改動**(可在報告附「單專案觀察」一節,標明「該案人類裁決,非框架」)。
  6. **產提案**：對每個 `HARNESS_DEFECT`,沿用 [rule-loophole-audit.md §5](../maintenance/rule-loophole-audit.md) 的「建議硬化」格式(`🚨 強制約束` + `❌ 嚴禁`),**每條附證據**(出處 `run_id` 清單 + 指紋/數值 + 次數 + repos)。提案寫進 `maintenance/proposals/<date>-<slug>.md`,可附**草稿 diff**(人類起點,非自動套用)。
  7. **讀駁回歷史**:開工先掃 `maintenance/proposals/` 既有檔的「人類裁決」欄,**已被駁回且理由仍成立的提案不得重提**(防 gate 疲勞)。
  8. **獨立重審鐵則**：先自己從宗旨+數據推一遍「這裡該怎麼防」,再對照現狀;**說不出 agent 具體怎麼卡/怎麼鑽,就不算數,別湊數**。
  9. **輸出末行判決**(供腳本/人類判收斂)：
     - 無新的、跨專案達門檻的 `HARNESS_DEFECT`：`[LOOP4: CONVERGED] 本輪無新跨專案 harness 缺陷。`
     - 有 N 條提案：`[LOOP4: PROPOSALS <N>] 見 maintenance/proposals/<date>-*.md。`
- **驗收**：把 §4 fixture 產的 `summary.json`(含 1 個 `meets_K=true` 與 1 個 `SPEC_CONFLICT_SUSPECT`)餵給依此 prompt 跑的 agent → 它對前者產 1 條帶證據提案、對後者只標示交人不改框架、末行輸出 `[LOOP4: PROPOSALS 1]`。

### 3-2　與 adversarial 稽核合流
- **需求**：prompt 末尾註明「本檔產的 trace-driven 提案,與 `rule-loophole-audit.md` 的 adversarial 提案,**進同一個 `maintenance/proposals/` 與同一道人類 gate**;兩者衝突時安全方向(更嚴)優先呈現,但由人類定」。
- **驗收**：prompt 文中可見此段。

---

## 6. 批次 4：人類 gate + 迴歸（流程,輕量,複用既有資產）

### 4-1　提案以分支/PR 呈現,人類手動合併
- **需求**：文件化(寫進 [loop4-harness-hill-climbing.md](loop4-harness-hill-climbing.md) §6 已有,確認一致)：提案推到框架 repo 分支 `loop4/<date>`;人類 review→ 採納/改寫/駁回;駁回理由**回寫該 proposal 檔的「人類裁決」欄**(供 §3-1.7 下輪讀)。**程式內不得有自動 merge 路徑。**
- **驗收**：grep 全 repo 確認無「自動 commit 提案到主幹 / auto-merge」程式路徑;proposal 檔模板含「人類裁決」欄。

### 4-2　合併後迴歸 = 複用 `post-hardening-verification.md`
- **需求**：合併採納的硬化後,跑既有 [maintenance/post-hardening-verification.md](../maintenance/post-hardening-verification.md) 做獨立冷啟動驗收;**新增一句**:被本批「宣稱修掉」的痛點,須在**下一批 trace** 量到下降(閉環事後證明——於 `summary.json` 比對前後 metric)。
- **驗收**：`post-hardening-verification.md` 末尾(或本規格 §6)記載此「下一批 trace 比對」步驟。

---

## 7. 驗證環境（fixture——必做,且要「多 repo」才驗得了跨專案）

> 跨專案聚合(§4-2)是本功能的靈魂,**單一 repo 驗不出來**。請建**至少兩個** fixture repo,各含帶 `run_id` 的 `rounds.jsonl`,並刻意讓兩者**共用一個震盪指紋**(造出 `meets_K=true`)、另造一個**只在單 repo** 的指紋(造 `meets_K=false`)。

```bash
FW=/Users/linyuting/IdeaProjects/loop-agent
# 兩個 fixture repo + workspace
for R in a b; do
  mkdir -p /tmp/loop-fx-$R && cd /tmp/loop-fx-$R && git init -q && git commit -q --allow-empty -m init
  python $FW/init-project.py /tmp/loop-fx-$R --name default
  mkdir -p /tmp/loop-fx-$R/.loop/default/.loop_state
done
# 手工編造 rounds.jsonl(已知答案,供 §4 驗算):
#  - repo a、b 各放一條相同 fingerprint 的 FAIL 輪 → 跨專案候選 meets_K=true
#  - repo a 另放 9 條同一「單專案」fingerprint → meets_K=false(證明看 repo 數不看次數)
#  - repo b 放一段 enhanced_rounds_used 高且其後 progressed=false → SPEC_CONFLICT_SUSPECT
# (具體幾行由實作 agent 依 §1.1 schema 造;務必含 run_id/loop_type/phase/result/fail 指紋來源)
# 把兩個 ws 寫進 index.md(或讓 init/loop 寫),再跑收集器:
python $FW/engine/collect_traces.py --k 2
```

> fixture 的 `fail_history` 指紋格式須與 [engine/state.py](../engine/state.py) / [BLUEPRINT §3.7.1](../rules/BLUEPRINT.md)（`hash(排序(失敗任務)+排序(改動檔))`）一致,否則 §2-1 `oscillation_hotspots` 對不上。

---

## 8. 交付物清單（逐批對照）

| 批次 | 交付物 | 驗收門 |
|---|---|---|
| 0 | `loop.py`/`plan_loop.py` 補 `run_id`;`append_round` 寫入(依 engine-rounds-history.md) | 0-1 / 0-2 |
| 1 | `engine/collect_traces.py`(發現/讀取/snapshot/CLI) | 1-1～1-4 |
| 2 | 同檔內聚合指標 + `cross_project_candidates`(`summary.json`) | 2-1 / 2-2 |
| 3 | `maintenance/trace-driven-analysis.md`(分析 agent prompt) | 3-1 / 3-2 |
| 4 | 文件化人類 gate + 迴歸步驟;proposal 模板含「人類裁決」欄 | 4-1 / 4-2 |

**每批完成 → 停 → 貼驗收證據(指令輸出/summary.json 片段)→ 通過才進下一批。** 不要一次寫到底才驗。
