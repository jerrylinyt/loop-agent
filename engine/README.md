# engine — 通用 Loop Engineering 執行引擎（Python）

`loop.py` 是唯一的執行引擎（單一事實來源，不再維護 bash 版）。

## 它做什麼
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
