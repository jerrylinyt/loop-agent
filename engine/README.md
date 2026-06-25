# engine — 通用 Loop Engineering 引擎（Python）

三支腳本（純 Python，不維護 bash 版）：

| 腳本 | 階段 | 做什麼 |
|------|------|--------|
| `plan_loop.py` | ② 生成 | 反覆觸發 agent 從 REQUIREMENTS 獨立(重)推導規劃書，直到「連續 N 輪無實質變更且 Plan Gate PASS」→ 規劃書收斂。狀態落 `.loop/PLAN.md`，log 落 `.loop/plan.log`。 |
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
- **震盪偵測 + 三層升級**：失敗指紋環狀歷史 → 偵測「改A壞B」/卡住 → 預設→增強→人類。
- **git 守護**：只作用於工作區（code repo）；整檔空白兜底還原 + 補漏 commit。**絕不寫 `framework_path`**。
- **watchdog**：單輪逾時 / 閒置中斷（連 subAgent 一起殺）。
- **log rotation**：`loop.log` 超過上限切檔；log 只給人看，agent 不讀（見 rules/context-budget.md）。

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

## 設定模型指令
`config.models.build_cmd` 是樣板字串，`{model}` / `{prompt}` 會被帶入（`{prompt}` 保持單一參數）。
例：`"codex e --model {model} {prompt}"`。建議放 `~/.loop/profile.yaml` 全機共用。

## 回傳碼
- `0` 正常完成（LOOP COMPLETE）
- `1` 達 max_rounds 仍未完成 / config 缺 phases
- `2` 交人類（human_required 或卡死硬性保險）
