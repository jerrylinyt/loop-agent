# 施工進入點 Prompt（Loop 4 — 給實作 agent）

> 把下面 `=== PROMPT 開始 ===` 到 `=== PROMPT 結束 ===` 之間的內容整段貼給實作 agent 即可。
> 它是 cold-start 自足的：包含任務、規格位置、硬性限制、**驗證環境的建置**與**逐批驗收方法**。

---

`=== PROMPT 開始 ===`

你是這個 repo（Loop Engineering，路徑 `/Users/linyuting/IdeaProjects/loop-agent`）的實作工程師。任務：依規格實作 **Loop 4（Trace 驅動的 harness 爬坡迴圈）**。**不要重新設計需求**——需求已定稿在規格,照做並驗證即可。

## 0. 先讀（單一事實來源,依序）
1. [`docs/loop4-implementation-spec.md`](loop4-implementation-spec.md) — **本任務的逐項規格**（批次 0/1/2/3/4，每項都有「現況／需求／驗收標準」與 schema）。這是你的主文件。
2. [`docs/loop4-harness-hill-climbing.md`](loop4-harness-hill-climbing.md) — 規劃書（為什麼這樣設計、6 條紅線、資料流圖）。先懂「為什麼」再動手。
3. [`docs/engine-rounds-history.md`](engine-rounds-history.md) — 批次 0 依賴的 `rounds.jsonl` 既有規格（你要在其上補 `run_id`）。
4. [`maintenance/rule-loophole-audit.md`](../maintenance/rule-loophole-audit.md) — 批次 3 的分析 prompt 要對齊的**既有風格**（「建議硬化」格式 + 末行判決）。

讀完先用 3–4 句話回報你理解的範圍、6 條硬約束、與打算的施工順序，再動工。

## 1. 範圍與順序（嚴格照批次,逐批驗收）
- **批次 0（前置,先做）**：`rounds.jsonl` 補 `run_id` + 確保 `loop_type:"plan"` 也記。沒有它,後面聚合沒有跨執行唯一鍵,**全部驗不了**。
- **批次 1**：`engine/collect_traces.py` — 從 `~/.loop/index.md` 發現所有 ws → 唯讀收 trace → 產 `snapshot.jsonl` + CLI。
- **批次 2**：同檔內機械式聚合六項痛點指標 → `summary.json` + `cross_project_candidates`（含 `meets_K` 與 `prelabel`）。
- **批次 3**：寫 `maintenance/trace-driven-analysis.md`（分析 agent 的 prompt,文字交付物,不寫程式）。
- **批次 4**：文件化人類 gate + 迴歸（輕量,複用既有 `post-hardening-verification.md`）。

**每完成一批,停下做 §4 驗收,貼出證據（指令輸出／`summary.json` 片段）,通過才進下一批。** 不要一次寫到底才驗。

## 2. 硬性限制（違反即重做——詳見 spec §0）
- **對下游唯讀**：讀下游 `<repo>/.loop/<ws>/.loop_state/` 一律唯讀;缺檔/壞檔 → skip + warning,**絕不寫下游、絕不中斷**。產出**只**落本框架 repo 的 `maintenance/trace-snapshots/` 與 `maintenance/proposals/`。
- **Propose-only**：批次 2/3 **絕不**自動改 `rules/` `prompts.yaml` `config.py`、**絕不** auto-commit/push 主幹。程式裡**不得存在**任何「自動套用提案」路徑。
- **留證據才算數**：`summary.json` 的候選與任何提案,每條都要附 `run_id` 清單 + 指紋/數值 + 次數 + repos。無證據不得出現。
- **跨專案才升級**：`meets_K` 看「**不同 repo 數 ≥ K**」(K 預設 2,`--k` 可調),**不是看次數**。單 repo 痛點保留但 `meets_K=false`,不得當改框架依據。
- **痛點 ≠ 規格矛盾**：`enhanced_ineffective` 來源預標 `SPEC_CONFLICT_SUSPECT`,只標示交人,**不提框架改動**。
- **批次 0 零行為改動**：`rounds.jsonl` 寫入維持 best-effort(寫失敗照常跑),**不改任何控制流程或回傳碼**。
- **不新增相依**：純標準庫,沿用 [`engine/state.py`](../engine/state.py) 讀檔風格、[`engine/config.py`](../engine/config.py) 的 YAML 處理。
- 只有我明確要求才 commit / push。先在工作區改、驗證、回報。

## 3. 怎麼跑起來（純 Python,無服務,離線唯讀）
用 repo 的 venv。批次 1+ 的入口：
```bash
FW=/Users/linyuting/IdeaProjects/loop-agent
python $FW/engine/collect_traces.py --k 2            # 收集 + 聚合 → snapshot.jsonl + summary.json
python -m json.tool maintenance/trace-snapshots/$(date +%F)/summary.json | head -60
```

## 4. 驗證（重要:先建「多 repo」測試環境,跨專案才驗得出）

### 4.0 建測試 fixture（**必做**;單一 repo 驗不出跨專案聚合）
本 repo 的 `default` 條目沒有實際 workspace 檔案。請建**至少兩個** fixture repo,各含帶 `run_id` 的 `rounds.jsonl`,並**刻意造**三種訊號:
1. repo a、b **共用一個震盪指紋** → 應得 `meets_K=true`、`distinct_repos=2`。
2. repo a **單獨**一個指紋出現 9 次 → 應得 `meets_K=false`（證明看 repo 數,不看次數）。
3. repo b 一段 `enhanced_rounds_used` 高且其後 `progressed=false` → 應預標 `SPEC_CONFLICT_SUSPECT`。

```bash
FW=/Users/linyuting/IdeaProjects/loop-agent
for R in a b; do
  mkdir -p /tmp/loop-fx-$R && cd /tmp/loop-fx-$R && git init -q && git commit -q --allow-empty -m init
  python $FW/init-project.py /tmp/loop-fx-$R --name default
  mkdir -p /tmp/loop-fx-$R/.loop/default/.loop_state
done
# 依 spec §1.1 schema 手工編造兩個 rounds.jsonl（已知答案,供 §2 驗算）。
# fail_history 指紋格式須對齊 engine/state.py 與 BLUEPRINT §3.7.1：hash(排序(失敗任務)+排序(改動檔))。
# 確保兩個 ws 都在 ~/.loop/index.md（手動補或由 init/loop 寫）。
python $FW/engine/collect_traces.py --k 2
```

### 4.1 逐批驗收（對照 spec 的「驗收標準」）
- **批次 0**：跑 fixture 兩次(中途中斷重啟一次)→ `rounds.jsonl` 出現兩個不同 `run_id`,各自 `round` 重新起算;`--stage plan` 會產出 `loop_type:"plan"` 行。
- **批次 1**：收集器 stdout 報「2 repos / N workspaces」;`snapshot.jsonl` 行數 = 各 ws 有效行總和、每行有 `run_id/repo/ws`;塞一條壞 JSON 行 → 該行被 skip+warning、回傳碼仍 0;`grep` 不到任何下游原始碼片段。
- **批次 2**：`summary.json` 六項指標數值與手算一致;訊號①`meets_K=true`、訊號②`meets_K=false`、訊號③`prelabel=SPEC_CONFLICT_SUSPECT`。
- **批次 3**：把該 `summary.json` 餵給依新 prompt 跑的 agent → 對訊號①產 1 條帶證據提案、對訊號③只標示交人不改框架、末行 `[LOOP4: PROPOSALS 1]`;`maintenance/proposals/<date>-*.md` 落地且含「人類裁決」欄。
- **批次 4**：`grep` 全 repo 確認**無**自動 merge/auto-commit 提案的程式路徑;迴歸步驟(下一批 trace 比對痛點下降)已文件化。

**每批貼出證據(指令輸出 / `summary.json` 片段 / proposal 檔內容)再進下一批。**

## 5. 邊界與求助
- 規格有疑義、或 fixture 指紋對不上 `engine/state.py` 實際格式時,**先停下回報**,不要腦補硬幹(本框架原則:不猜測 → 開 Issue / 問人)。
- 你只動本框架 repo 的 `engine/`（`collect_traces.py` + `loop.py`/`plan_loop.py` 補 `run_id`）與 `maintenance/`（新 prompt + proposal 模板）。**不動任何下游 code repo,不動 `dashboard/`。**

`=== PROMPT 結束 ===`
