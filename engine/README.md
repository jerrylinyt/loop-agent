# engine — 通用 Loop Engineering 引擎（Python）

三支腳本（純 Python，不維護 bash 版）：

| 腳本 | 階段 | 做什麼 |
|------|------|--------|
| `plan_loop.py` | ② 生成 | 每個 cycle 兩輪：Round A 生成（獨立重推/精修規劃書）、Round B 審查（**獨立 context，只審不生**，跑 Plan Gate）。直到「連續 N 個 cycle 無實質變更且 Gate PASS」→ 收斂；卡死則升級【增強模型】→ 仍卡交人類。狀態落 `.loop/PLAN.md`，log 落 `.loop/plan.log`。 |
| `loop.py` | ③ 執行 | 反覆觸發 agent 依規劃書執行，直到最終結果收斂或交人類。狀態在 `.loop/CONTROL.md`，log 落 `.loop/loop.log`。 |
| `run.py` | 入口 | 串接 ②③，提供 `--mode gated\|auto`、`--stage all\|plan\|execute`。 |

> `plan_loop.py` / `run.py` 都 import `loop.py` 當共用函式庫（config cascade、run_agent、git 守護、log rotation 等單一事實來源）。
> **所有腳本從 code repo 根目錄執行**（產出落 repo 根、控制檔在 `.loop/`）。

## run.py（建議入口）
```bash
python3 <fw>/engine/run.py                 # 依 config.generation.mode（預設 gated）
python3 <fw>/engine/run.py --mode auto     # 生成收斂後自動接執行
python3 <fw>/engine/run.py --stage plan    # 只生成規劃書
python3 <fw>/engine/run.py --stage execute # 只執行（gated review 完用這個）
```

## loop.py（執行引擎）它做什麼
反覆觸發 coding agent 跑 `CONTROL.md`，並負責：
- **config cascade**：框架預設 < `~/.loop/profile.yaml` < 專案 `.loop/loop.config.yaml` < 環境變數。
- **N 階段流程控制**：停止條件、Phase Gate 全依 `config.phases`（最後一筆=最終階段），不寫死階段數。
- **震盪偵測 + 三層升級**：失敗指紋環狀歷史(**持久化於 `.loop/.loop_state/fail_history`，重啟接續不歸零**) → 偵測「改A壞B」/卡住 → 預設→增強→人類。
- **git 守護**：只作用於工作區（code repo）；整檔空白兜底還原 + 補漏 commit。**絕不寫 `framework_path`**（git 缺失/不在 PATH 也安全降級為警告，不會丟例外）。
- **watchdog**：單輪逾時 / 閒置中斷（連 subAgent 一起殺）。
- **log rotation**：`loop.log` 超過上限切檔；log 只給人看，agent 不讀（見 rules/context-budget.md）。
- **preflight 健檢**：啟動先跑 `preflight(cfg, stage)`，錯誤就擋下（見下）。
- **跨專案 index**：結束時 upsert 一行到 `~/.loop/index.md`（`config.index` 可覆蓋路徑）。

## plan_loop.py（生成引擎）額外負責
- **獨立 Plan Gate**：Round A（生成,模型依 `plan_model_tier`）與 Round B（審查,**永遠用 default 模型、不同 context、唯讀**）分開呼叫 agent,避免自己生、自己審。
- **卡死三層升級（與 loop.py 對稱）**：連續 `oscillation.stall_threshold` 個 cycle 無進展(有變更或 Gate FAIL) → Round A 換【增強模型】;再撐 `oscillation.enhanced_max_rounds` 個 cycle 仍無進展 → `plan_human_required=true`、停止(不會空轉到 `generation.max_rounds`)。
- 狀態欄位（`.loop/PLAN.md`）：`plan_status` `plan_stable_rounds` `plan_model_tier` `plan_rounds_since_progress` `plan_enhanced_rounds_used` `plan_human_required`。

## preflight 健檢（兩個引擎共用，啟動時自動跑）
檢查項：`agent.models.default/enhanced` 是否仍是 `<佔位>`、`framework_path` 是否存在且像框架、
`build_cmd` 的執行檔是否在 PATH、是否在 git repo 內、`stage=plan` 時 `.loop/REQUIREMENTS.md` 是否存在、
`stage=execute` 時 `.loop/CONTROL.md` 是否存在（`phases` 缺則視 stage 決定 error/warning）。
有 error 直接擋下（return 1），不會空轉到 max_rounds 才發現設定沒填對。

## 相依
- Python 3.8+（標準庫即可）。
- `pyyaml` **可選**：有就用它解析 config；沒有則用內建的輕量 YAML 子集解析器（已涵蓋本框架 config/profile 的結構）。
- `pty`（Unix/WSL）有就用，沒有（純 Windows）自動退化為 pipe 模式。

## 怎麼跑（在 code repo 的 .loop/ 內）
```bash
# 1) 確認 .loop/loop.config.yaml 已由階段② 生成、且 framework_path 指向共享框架 clone
# 2) 啟動引擎（預設讀 ./loop.config.yaml）
python3 <framework_path>/engine/loop.py
# 另一視窗看詳細輸出：
tail -f loop.log
```

可用環境變數覆蓋：`LOOP_CONFIG`（config 路徑）、`LOOP_PROFILE`、`MAX_ROUNDS`、`INTERVAL`、
`LOG_FILE`、`ROUND_TIMEOUT`、`IDLE_TIMEOUT`、`CONTROL`、`DEFAULT_MODEL`、`ENHANCED_MODEL`。

## 設定 agent 指令（全抽成 config，code 只讀設定）
全部在 `config.agent`（建議放 `~/.loop/profile.yaml` 全機共用）：
- `build_cmd`：指令樣板，`{model}` / `{prompt}` 帶入（`{prompt}` 保持單一參數），可選 `{args}` 佔位。
  例：`"codex e --model {model} {prompt}"`。
- `extra_args`：額外固定 CLI 參數（如 `["--yolo"]`）。template 有 `{args}` → 插在該處；否則接在 prompt 前；
  template 連 `{prompt}` 都沒寫 → prompt 與 extra_args 會補在最後（絕不遺漏 prompt）。
- `models.default` / `models.enhanced`：兩層模型（卡住時切 enhanced）。env `DEFAULT_MODEL`/`ENHANCED_MODEL` 可覆蓋。
- `prompts.base` / `prompts.escalation` / `prompts.plan` / `prompts.plan_gate`：提示樣板（省略用框架預設）。
  佔位：`{control}` `{framework}` `{plan_md}` `{requirements}`。`plan_gate` 是獨立審查輪用的（唯讀，不可生成/修改規劃書）。
- `index`：`~/.loop/index.md`（跨專案總覽路徑，可在 config 覆蓋）。

## 回傳碼
- `0` 正常完成（LOOP COMPLETE）
- `1` 達 max_rounds 仍未完成 / config 缺 phases
- `2` 交人類（human_required 或卡死硬性保險）
