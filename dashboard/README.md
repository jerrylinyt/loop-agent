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
`fastapi`、`uvicorn`、`pyyaml`、`psutil`（見 repo 根目錄 `requirements.txt`）。前端用 Tailwind CDN，**沒有建置步驟**。

---

## 它是怎麼運作的

Dashboard 本身**不存任何狀態**，所有資訊都即時讀自檔案系統：

| 資料 | 來源檔 |
|------|--------|
| 專案總覽（哪些 repo/workspace） | `~/.loop/index.md`（Markdown 表格） |
| 每個 workspace 的即時狀態 | `<repo>/.loop/<ws>/CONTROL.md` |
| 是否執行中 / PID | `<repo>/.loop/<ws>/.loop_state/run.lock` |
| 即時 log | `<repo>/.loop/<ws>/loop.log`、`plan.log` |
| 設定 | `<repo>/.loop/<ws>/loop.config.yaml` |
| 規劃樹 | `<repo>/.loop/<ws>/TREE.md` |

「啟動專案」其實是在該 repo 目錄下 spawn 一個 `engine/run.py` 子程序；「停止」是用 `psutil` 依 `run.lock` 的 PID 把程序樹 kill 掉。狀態欄位（phase / stuck / status）會以 CONTROL.md 的即時值覆寫 index.md 的快照。

---

## 介面總覽

### 左側：Projects & Workspaces
- 列出 `~/.loop/index.md` 裡所有專案，每張卡片顯示 repo 名、workspace、狀態 badge、phase、stuck。
- 每 5 秒自動刷新。
- 右上兩顆按鈕：
  - **+ Init** — 對一個尚未初始化的 repo 跑 `init-project.py` 建立新 workspace，並寫進 index.md。
  - **+ Track** — 把一個**已經初始化過**的 workspace 加進 dashboard 追蹤（只寫 index.md，不動 repo）。

### 右側：選定專案的詳情
頂部顯示 repo/workspace 標題、狀態 badge、路徑，以及 **Start (Auto)** / **Force Stop** 按鈕，下方三格摘要：**Phase / Stuck Level / Status**。

底下是三個分頁：

- **Live Logs** — SSE 即時串流 `loop.log` 或 `plan.log`（可切換）。
- **loop.config.yaml** — 線上編輯設定，存檔時會做 YAML 合法性驗證，不合法會擋下並提示。
- **Planning Tree** — 僅在該 workspace 的 `TREE.md` 啟用樹模式時出現。左側畫出節點樹（依狀態上色），點節點在右側看詳情，並可對子樹按 **Reject & Replan**（把該子樹退回重新規劃；需先停止執行）。

---

## 功能一覽

| 功能 | 說明 | 對應 API |
|------|------|----------|
| 列出專案 | 讀 index.md + CONTROL.md 即時覆寫 | `GET /api/projects` |
| 啟動引擎 | 在 repo 下 spawn `engine/run.py`（目前固定 auto / 全階段） | `POST /api/projects/{id}/start` |
| 強制停止 | 依 run.lock 的 PID kill 程序樹並清 lock | `POST /api/projects/{id}/stop` |
| 初始化新 workspace | 跑 `init-project.py` 並登錄 index.md | `POST /api/projects/init` |
| 追蹤既有 workspace | 把現成 workspace 加進 index.md | `POST /api/projects/add` |
| 讀 / 存設定 | loop.config.yaml（存檔含 YAML 驗證） | `GET`/`POST /api/projects/{id}/config` |
| 規劃樹 | 解析 TREE.md 成節點圖 | `GET /api/projects/{id}/tree` |
| Reject 子樹 | 退回子樹並重新規劃 | `POST /api/projects/{id}/reject` |
| 即時 log | SSE 串流 loop / plan log | `GET /api/projects/{id}/logs/{type}` |

### 規劃樹節點狀態色
`PENDING`（灰）、`IN_PROGRESS`（藍，跳動）、`CONVERGED`（綠）、`NEEDS_REVISION`（黃）、`FROZEN`（紅）、`DECOMPOSED`（靛）。

---

## 常見問題

**Q：列表一直是空的？**
A：`~/.loop/index.md` 還沒有任何專案。用 **+ Init** 初始化一個 repo，或 **+ Track** 把既有 workspace 加進來。

**Q：Live Logs 打開是空白？**
A：目前的串流只接「之後」的新行，專案沒在跑時不會顯示歷史內容（已知限制）。先 Start 起來就會有輸出。

**Q：badge 一直卡在 Running、按 Start 沒反應？**
A：可能是殘留的 `run.lock`（已知限制，見 improvements A2）。手動刪除 `<repo>/.loop/<ws>/.loop_state/run.lock` 後重試。

**Q：能改 port 或對外開放嗎？**
A：改 port 用上面的 uvicorn 指令。**不建議對外開放**——沒有任何驗證，且能在你機器上啟動子程序與改設定。

---

## 檔案結構

```
dashboard/
├── app.py            # FastAPI 應用：所有 API 端點與檔案解析邏輯
├── main.py           # 啟動器：起 uvicorn + 開瀏覽器
├── templates/
│   └── index.html    # 單頁前端（Tailwind CDN + 原生 JS，無建置）
└── README.md         # 本檔
```

> 已知缺口：log 補歷史、清殘留 lock、human_required 處理、桌面通知、活動時間軸、diff 檢視等。
