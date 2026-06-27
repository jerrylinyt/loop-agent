# 施工進入點 Prompt（給實作 agent）

> 把下面 `=== PROMPT 開始 ===` 到 `=== PROMPT 結束 ===` 之間的內容整段貼給實作 agent 即可。
> 它是 cold-start 自足的：包含任務、規格位置、硬性限制、**驗證環境的建置**與**逐批驗收方法**。

---

`=== PROMPT 開始 ===`

你是這個 repo（Loop Engineering，路徑 `/Users/linyuting/IdeaProjects/loop-agent`）的實作工程師。任務：依規格完善 `dashboard/`。**不要重新設計需求**——需求已定稿在兩份規格，照做並驗證即可。

## 0. 先讀（單一事實來源）
1. [`docs/dashboard-improvements.md`](dashboard-improvements.md) — dashboard 端全部需求（批次 A/B/C/D，每項都有「現況／需求／驗收標準」）。
2. [`docs/engine-rounds-history.md`](engine-rounds-history.md) — 引擎端 `rounds.jsonl` 需求（**獨立 track**，見 §5）。
3. [`dashboard/README.md`](../dashboard/README.md) — 目前 dashboard 的功能與運作方式。

讀完先用 2–3 句話回報你理解的範圍與打算的施工順序，再動工。

## 1. 範圍與順序（嚴格照批次，逐批驗收）
- **第一批：A（修 bug）** — A1 log 補歷史、A2 殭屍 lock 可清、A3 用 `sys.executable` 並保留錯誤輸出。
- **第二批：B（補工作流）** — B1 human_required 原因+Resume、B2 啟動模式選擇、B3 CONTROL 狀態總覽、B4 untrack。
- **第三批：C（體驗）** — C1 增量更新、C2 log 搜尋/下載/上限、C3 全域總覽列。
- **D（新功能）/ 引擎 rounds.jsonl** — **先不要做**，除非完成 A+B+C 且我另行指示。D3 依賴引擎 track。

**每完成一批，停下來做 §4 的驗收，貼出證據（指令輸出／截圖／curl 回應），通過才進下一批。** 不要一次把全部寫完才驗。

## 2. 硬性限制（違反即重做）
- **前端不可引入建置工具**：維持單一 `dashboard/templates/index.html` + Tailwind CDN + 原生 JS，無 npm/bundler。
- **檔案格式是與引擎共用的契約**：`index.md` / `CONTROL.md` / `TREE.md` / `run.lock` 既有欄位語意不可改。B1 的 Resume 改寫 CONTROL.md 時**只能改目標 key**（用 `engine/state.py` 既有 `set_val` 的同款逐行替換邏輯），不可重排或破壞其他行。
- **新端點要有意義的錯誤**：找不到專案回 404、非法 `mode/stage/log_type` 回 400，`HTTPException(detail=...)`，前端要顯示，不可靜默吞錯。
- **路徑安全**：任何讀檔端點（如 D7，本期不做）若吃使用者輸入路徑，必須 `os.path.realpath` 限制在該 workspace 內。
- **Pydantic model 要同步**：`ProjectStatus` 新增欄位（如 `stale_lock`）務必加進 model，否則 `response_model` 會濾掉。
- **不要改引擎行為**：本任務只動 `dashboard/`。引擎 `rounds.jsonl` 是另一份 spec、另一個 track。
- 只有我明確要求才 commit / push。先在工作區改、驗證、回報。

## 3. 怎麼跑起來
本機工具，無資料庫，純讀檔。用 repo 的 venv：
```bash
# 背景啟動 server（開發用 reload）
python -m uvicorn dashboard.app:app --host 127.0.0.1 --port 8000 --reload
# 健康檢查
curl -s http://127.0.0.1:8000/api/projects | python -m json.tool
```

## 4. 驗證（重要：先建測試環境，再逐項驗收）

### 4.0 建測試 fixture（**必做**——本 repo 的 `default` 條目沒有實際 workspace 檔案，無法驗）
`~/.loop/index.md` 雖列了 `loop-agent / default`，但 `.loop/default/` 並不存在（沒有 CONTROL.md/config/log）。請自建一個可控的測試 workspace：

```bash
# 1) 建一個臨時 git repo 當測試對象
mkdir -p /tmp/loop-fixture && cd /tmp/loop-fixture && git init -q && git commit -q --allow-empty -m init

# 2) 用框架建出合法 workspace（會產生 loop.config.yaml；非互動）
python /Users/linyuting/IdeaProjects/loop-agent/init-project.py /tmp/loop-fixture --name default
```

`init-project.py` 不會建 CONTROL.md（那是規劃階段才生），所以**手動補一份最小 CONTROL.md** 供 B1/B3 驗證——在 `/tmp/loop-fixture/.loop/default/CONTROL.md` 寫入：
```
current_phase: 1
stuck_level: 0
human_required: false
stop_condition_met: false
last_round_mode: 驗證
last_round_result: PASS
last_round_fail_tasks:
rounds_since_progress: 0
current_model_tier: default
enhanced_rounds_used: 0
blocking_issues: 0
plan_version: 1
p1_consecutive_pass: 2
p1_total_validations: 4
p1_last_result: PASS
```
再造一個有內容的 log 供 A1/log 驗證：
```bash
seq 1 600 | sed 's/^/log line /' > /tmp/loop-fixture/.loop/default/loop.log
```
最後把這個 workspace 加進 dashboard 追蹤（server 啟動後）：
```bash
curl -s -X POST http://127.0.0.1:8000/api/projects/add \
  -H 'Content-Type: application/json' \
  -d '{"repo_path":"/tmp/loop-fixture","workspace_name":"default"}'
```
> 用完可刪 `/tmp/loop-fixture` 並從 `~/.loop/index.md` 移除該列（或用你做好的 B4 untrack）。**不要動到真正的 `loop-agent` 那列。**

### 4.1 逐項驗收（對照規格的「驗收標準」逐條做，並貼證據）
每項都有後端與前端兩面。後端用 `curl` 驗端點契約；前端用 `/run` 或 `/verify` 技能開實際畫面點過一遍（或用瀏覽器工具截圖）。重點檢查：

- **A1（log 歷史）**：對 `/tmp/loop-fixture` 開 Live Logs，應立刻看到 `loop.log` 最後數百行，之後 `echo "new line $(date)" >> .../loop.log` 會即時追加。
- **A2（stale lock）**：`mkdir -p /tmp/loop-fixture/.loop/default/.loop_state && printf 'pid=999999 started=2020-01-01 00:00:00' > .../run.lock`，刷新後該專案應標 `stale_lock=true` 並出現 Clear Lock；按下後 lock 檔消失、可正常 Start。驗 `GET /api/projects` 回傳含 `stale_lock` 欄位。
- **A3（sys.executable + 錯誤輸出）**：`grep -n '"python"' dashboard/app.py` 應無殘留（改用 `sys.executable`）。對 fixture 觸發 Start，確認 `.loop/default/.loop_state/spawn.log` 有輸出（成功或錯誤皆可，重點是不再吞掉）。
- **B1（human_required）**：把 fixture 的 CONTROL.md `human_required` 改 `true`，刷新後詳情頁出現黃色橫幅、`GET /api/projects/{id}/human-context` 回 reason/log_excerpt；按 Resume → CONTROL.md 該 key 變回 `false`（且其餘行原封不動，`git diff` 驗證無附帶破壞）。
- **B2（模式）**：UI 能觸發 gated / plan-only / execute-only；後端對非法 `mode/stage` 回 400。
- **B3（control 總覽）**：`GET /api/projects/{id}/control` 回結構化 JSON（含 `phases` 陣列，能從 `p1_*` 推出一筆）；UI Overview tab 正確呈現。
- **B4（untrack）**：untrack 後該列從 `~/.loop/index.md` 與列表消失，但 `/tmp/loop-fixture/.loop/` 檔案**原封不動**（`ls` 驗證）；對執行中的專案 untrack 回 400。

### 4.2 回歸（每批結束都跑）
```bash
cd /Users/linyuting/IdeaProjects/loop-agent && python -m pytest -q
```
確認既有測試全綠。**新增的後端解析邏輯（CONTROL 解析、stale lock 判定、human-context 抽取）請補對應 pytest**，至少覆蓋正常與檔案缺失兩種情況。

### 4.3 收尾自檢
- `git status` 不應出現非預期檔案（fixture 在 `/tmp`，不在 repo 內）。
- `git diff` 只應動到 `dashboard/`（與你補的測試）。確認沒有誤改 `engine/` 或規格文件。

## 5. 引擎 rounds.jsonl（獨立 track，預設先不做）
若我指派這條：依 [`docs/engine-rounds-history.md`](engine-rounds-history.md) 在 `engine/state.py` 加 `append_round_record`，並在 `engine/loop.py:430`、`engine/loop.py:642` 兩個 `save_progress(...)` 之後插入寫入。驗收照該 spec §5；特別確認 best-effort 不阻斷、`git check-ignore` 確認 `rounds.jsonl` 已被忽略。**這條不要和 dashboard 批次混在同一次改動。**

## 6. 完成定義（Definition of Done）
- 指派批次的每一項都通過 §4 對應驗收，且你貼出了證據。
- `pytest` 全綠、`git status`/`git diff` 乾淨且範圍正確。
- 用 2–3 句回報：做了什麼、怎麼驗的、有沒有偏離規格之處（如有，先說明再請示）。
- 若途中發現規格有矛盾或做不到，**停下來問**，不要自行擴大或臆測。

`=== PROMPT 結束 ===`
