# Loop Engineering Dashboard

Loop 引擎的本機 Web 控制台：在一個瀏覽器頁面管理多個專案/workspace，啟動或停止引擎、看即時 log、編輯設定、檢視規劃樹。

> 這是一個**本機工具**，預設只綁 `127.0.0.1`，無帳號驗證——不要把它對外開放。

---

## 快速開始

```bash
# 在 repo 根目錄，使用專案的 venv
python -m dashboard.main
# 或
python dashboard/main.py
```

啟動後會：
1. 用 `uvicorn` 在 `http://127.0.0.1:8000` 起一個 FastAPI server；
2. 自動開啟瀏覽器；
3. 按 `Ctrl+C` 關閉。

也可以自己跑 server（例如要改 port / 開 reload）：

```bash
python -m uvicorn dashboard.app:app --host 127.0.0.1 --port 8000 --reload
```

### 需要的套件
- **後端 Python 套件**：`fastapi`、`uvicorn`、`pyyaml`、`psutil`（見 repo 根目錄 `requirements.txt`）。
- **前端開發套件**：前端已改用 React + Vite + TypeScript + Tailwind CSS。
- **免 Node.js 執行**：專案已將前端編譯後的靜態檔案 `dashboard/frontend/dist` 納入 Git 追蹤。一般使用者**不需要**安裝 Node.js 或執行任何建置步驟，即可直接啟動後端並使用新版 Dashboard。
- **前端開發與建置**（僅在需要修改前端 UI 時）：
  ```bash
  cd dashboard/frontend
  npm install
  npm run dev   # 啟動 Vite 開發伺服器（預設為 http://localhost:5173）
  npm run build # 建置並輸出到 dist/ 供 FastAPI 託管
  ```

---

## 它是怎麼運作的

Dashboard 本身**不存任何狀態**，所有資訊都即時讀自檔案系統：

| 資料 | 來源檔 |
|------|--------|
| 專案總覽（哪些 repo/workspace） | `~/.loop/index.md`（Markdown 表格） |
| 每個 workspace 的即時狀態 | `<repo>/.loop/<ws>/state.json` |
| 是否執行中 / PID | `<repo>/.loop/<ws>/.loop_state/run.lock` |
| 即時 log | `<repo>/.loop/<ws>/loop.log`、`plan.log` |
| 設定 | `<repo>/.loop/<ws>/loop.config.yaml` |
| 規劃樹 | `<repo>/.loop/<ws>/TREE.md` 或 `state.json` 中的 tree 結構 |
| 歷史執行回合與進度 | `<repo>/.loop/<ws>/.loop_state/rounds.jsonl` |

「啟動專案」其實是在該 repo 目錄下 spawn 一個 `engine/run.py` 子程序；「停止」是用 `psutil` 依 `run.lock` 的 PID 把程序樹 kill 掉。狀態欄位（phase / stuck / status）會以 `state.json` 的即時值覆寫 index.md 的快照，進展趨勢（direction）則由後端基於執行歷史自動判斷。

---

## 介面總覽

### Global Home (全域工作區管理)
- **關注度分組**：依據各工作區目前所需的關注度進行分組展示（例如：`human_required` 需要人工介入、`running` 執行中、`stalled` 已停滯、`completed` 已完成、`idle` 閒置等）。
- **工作區卡片**：展示 Repository、Workspace 名稱、當前進展分支/階段、生理狀態指標（Phase、Stuck Level）、目前執行狀態以及**進度趨勢 (Progress Trend)**（分為 `forward` 前進、`backward` 退步、`stalled` 停滯、`neutral` 中立、`unknown` 未知）。
- **主要操作**：可直接在卡片上點擊 Open 開啟詳情、Start 啟動、Resume 恢復執行、Review Issue 檢視問題、或刪除追蹤。
- **右上操作按鈕**：
  - **+ Init** — 對一個尚未初始化的 repo 跑 `init-project.py` 建立新 workspace，並寫進 index.md。
  - **+ Parallel** — 對同一 repo 建立新的 git worktree + branch + workspace，成功後自動加入追蹤。
  - **+ Track** — 把一個**已經初始化過**的 workspace 加進 dashboard 追蹤（只寫 index.md，不動 repo）。

### Workspace Overview (工作區駕駛艙)
- **狀態看板 (Headline Card)**：一句話總結目前的狀態、進展趨勢、具體原因 (Why) 以及建議人類採取的下一步行動 (Next)。
- **進展圖表 (Progress Chart)**：視覺化展示隨執行回合（Rounds）變化的測試通過/失敗狀態、Stuck 程度與所使用的模型等級，並清楚標示出 Regression (退步) 與 Stuck (停滯) 的標記。
- **原因與活動時間軸 (Activity Timeline)**：回溯解析 `rounds.jsonl` 與狀態變更，產生具體且有嚴重程度標記的活動事件流（如：啟動、成功、失敗、退步、模型調整、需人工介入、迴圈完成等）。
- **決策卡片 (Next Action Card)**：當引擎處於 `human_required` 狀態時，會以顯眼卡片提示需要人工介入的原因、證據（日誌片段或錯誤訊息），並提供恢復執行的 Resume 按鈕。
- **診斷抽屜 (Diagnostics Drawer / Tabs)**：
  - **Live Logs** — 即時 SSE 串流 `loop.log` 或 `plan.log`（可切換），支援載入最後 500 行歷史日誌，並可下載完整日誌檔。
  - **Git Diff** — 即時檢視當前工作區的 Git 變更。
  - **Config** — 編輯 `loop.config.yaml` 或使用精靈 (Setup Wizard) 設定模型與模式。
  - **Raw State** — 檢視原始的 `state.json` 內容。

### 規劃樹地圖 (Planning Tree)
- 若工作區啟用樹狀規劃模式，會視覺化各節點狀態、卡關節點、收斂節點以及重複規劃次數，並支援對特定子樹執行 **Reject & Replan**（需先停止執行）。

---

## 功能一覽

### 新版工作區 API 端點

| 功能 | 說明 | 對應 API |
|------|------|----------|
| 列出工作區 | 讀取專案索引列表，整合 state.json 狀態與 Lock 檔案資訊 | `GET /api/workspaces` |
| 取得狀態摘要 | 返回 headline、趨勢、說明與下一步建議之結構化狀態 | `GET /api/workspaces/{id}/overview` |
| 啟動引擎 | 在工作區目錄 spawn `engine/run.py` 執行迴圈 | `POST /api/workspaces/{id}/start` |
| 強制停止 | 根據 run.lock 的 PID 終止程序樹並清理 Lock 檔 | `POST /api/workspaces/{id}/stop` |
| 恢復執行 | 人工確認後恢復執行處於 `human_required` 的工作區 | `POST /api/workspaces/{id}/resume` |
| 清理鎖檔案 | 手動清除殘留的 `run.lock` 狀態 | `POST /api/workspaces/{id}/clear-lock` |
| 啟動前檢查 | 檢查 requirements、設定檔、鎖檔案、Git 狀態等 | `GET /api/workspaces/{id}/preflight` |
| 讀取設定檔 | 載入 `loop.config.yaml` 內容 | `GET /api/workspaces/{id}/config` |
| 修改設定檔 | 覆寫並驗證 `loop.config.yaml`（含 YAML 語法驗證） | `POST /api/workspaces/{id}/config` |
| 設定精靈 | 快速設定 agent 指令、模型與執行模式 | `POST /api/workspaces/{id}/config-wizard` |
| 規劃樹地圖 | 樹模式下，解析 state.json 的規劃節點樹 | `GET /api/workspaces/{id}/tree` |
| 退回子樹重規劃 | 針對特定子樹節點發送 Reject，觸發引擎重新規劃 | `POST /api/workspaces/{id}/reject` |
| 重設規劃 | 清除 state.json 中的 plan/phases 與 phases/*.md 檔案，重啟規劃迴圈 | `POST /api/workspaces/{id}/reset-plan` |
| 取得活動時間軸 | 回傳解析 `rounds.jsonl` 與 state.json 後的 typed events | `GET /api/workspaces/{id}/timeline` |
| 取得圖表資料 | 取得歷史 Rounds 執行結果 (PASS/FAIL、模型等級、停滯度) | `GET /api/workspaces/{id}/progress` |
| 即時日誌串流 | SSE 即時串流 loop / plan log，支援載入最後 500 行歷史 | `GET /api/workspaces/{id}/logs/{log_type}` |
| 下載完整日誌 | 下載 `loop.log` 或 `plan.log` 檔案 | `GET /api/workspaces/{id}/logs/{log_type}/download` |
| 診斷資訊 | 取得原始 state.json 內容、Git diff、檔案路徑等 | `GET /api/workspaces/{id}/diagnostics` |
| 取得工作區文件 | 安全地讀取工作區的階段性文件（如 PHASE*.md） | `GET /api/workspaces/{id}/doc` |
| 取得 Git Diff | 取得工作區相對於 Base 點的 Git Diff | `GET /api/workspaces/{id}/diff` |
| 初始化工作區 | 執行 `init-project.py` 並自動加入追蹤 | `POST /api/workspaces/init` |
| 追蹤已有工作區 | 將既有的 workspace 目錄登錄到專案索引中 | `POST /api/workspaces/add` |
| 建立並行 worktree | 執行 `parallel.py add` 建立新工作區並追蹤 | `POST /api/parallel/add` |
| 取消追蹤工作區 | 從索引中移除該工作區（不刪除實體檔案） | `DELETE /api/workspaces/{id}` |

> **備註**：新版端點之 `{id}` 均使用 URL 安全的 MD5 Hash 值（例如 `repo_path` 與 `workspace_name` 的組合 Hash），以解決 Windows 下路徑包含 `:` 或 `\` 的傳輸與解析問題。同時後端仍保留舊版 `/api/projects/*` 路由的相容別名。

---

## 常見問題

**Q：列表一直是空的？**
A：`~/.loop/index.md` 還沒有任何專案。用 **+ Init** 初始化一個 repo，或 **+ Track** 把既有 workspace 加進來。

**Q：Live Logs 會顯示歷史日誌嗎？**
A：是的，現在開啟 Live Logs 時會預設讀取最後 500 行的歷史日誌，然後繼續即時串流後續的輸出。

**Q：badge 一直卡在 Running、按 Start 沒反應？**
A：可能是殘留的 `run.lock`。你可以直接在 UI 上點選 "Clear Lock"（清理鎖），或是等後端偵測到程序死亡後自動清除。如果仍然卡住，可點選 Force Stop 終止。

**Q：能改 port 或對外開放嗎？**
A：改 port 用上面的 uvicorn 指令。**不建議對外開放**——Dashboard 沒有驗證機制，且有權限在執行主機上啟動/終止程序、修改設定與讀取文件。

---

## 檔案結構

```
dashboard/
├── app.py            # FastAPI 應用：提供所有 API 端點（/api/workspaces/* 與舊版相容端點）
├── main.py           # 啟動器：啟動 uvicorn 並自動打開瀏覽器
├── test_app.py       # 後端 API 與解析邏輯之單元測試
├── README.md         # 本檔 (本文件)
└── frontend/         # 新版 React + Vite + TypeScript 前端專案
    ├── package.json  # 前端專案設定與套件依賴
    ├── vite.config.ts# Vite 設定檔
    ├── src/          # React 原始碼 (App.tsx, main.tsx, etc.)
    └── dist/         # 編譯產出的靜態檔案 (已納入 Git 追蹤，直接供 FastAPI 託管)
```
