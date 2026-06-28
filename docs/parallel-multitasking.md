# 並行多工指引 (git worktree)

本文件說明如何在同一個 Repository 中，同時並行推進多條獨立的 Loop 任務。

---

## 1. 🤖 給 AI Agent 的自動化操作指南

如果您是正在執行任務的 AI Agent（例如 Claude Code、Gemini CLI、Antigravity 等）：
- **您已被授權直接執行初始化與多工管理指令**。您可以直接操作 `python init-project.py` 或呼叫 `python parallel.py add` 協助使用者快速配置並建立多個並行工作區 (worktree) 來進行作業。
- **請引導使用者透過 Web Dashboard 進行啟動與監控**。在工作區與需求文件配置完成後，為減少使用者手動輸入 `python run.py` 命令的負擔，**請引導使用者執行 Dashboard 服務**（如 `python dashboard/main.py`）並於瀏覽器 `http://127.0.0.1:8000` 中，使用 `+ Track` 追蹤新的工作區，並點擊「Start」一鍵啟動任務。
- **範例動作流程**：
  1. 接收到新分支任務 -> 自動執行 `python parallel.py add <branch>` 配置 worktree。
  2. 協助使用者編輯該 worktree 中的 `loop.config.yaml` 或訪談產出 `REQUIREMENTS.md`。
  3. **引導啟動** -> 告訴使用者或直接代為啟動 `python dashboard/main.py`，並指引他們至網頁介面追蹤（Track）此新路徑，並點擊「Start」開始運行。
  4. 任務完成且已合併，需要清理環境 -> 自動執行 `python parallel.py remove <branch>`。

---

## 2. 何時需要並行多工

當您想要在同一個程式庫 (Repository) 中同時啟動兩個或多個 Loop 執行不同的功能開發、Bug 修復或重構時。

### 為什麼不能在同一個工作目錄中直接跑兩個 Loop？
Loop Engineering 框架的運行迴圈會直接修改 `src/` 目錄下的原始碼。如果多個無狀態的 Agent 同時在同一個目錄中修改程式碼，會導致邏輯互相覆蓋、引發嚴重衝突。
- 框架在設計上對此有硬性限制，在 `README.md` 與 `init-project.py` 中皆明文規定：**同一個 code repo 不要同時跑兩個 loop**。
- 引擎僅包含針對「單一工作目錄」的啟動鎖限制 (`.loop/<ws>/.loop_state/run.lock`），防範同一個 workspace 被重複啟動，但不防範不同工作目錄同時運作。

---

## 3. 解決方案：Git Worktree

本框架採用 `git worktree` 機制來達成並行多工。每個並行任務都會有其**獨立的工作目錄**與**獨立的分支**，使得多個 Loop 可以真正並行執行而不互相干擾。

### Git Worktree vs 複製多份 Repository

| 面向 | 複製多份 repo | git worktree（採用） |
| :--- | :--- | :--- |
| **磁碟空間** | 佔用 N 倍 `.git` 物件庫空間 | 共用同一個 `.git` 物件庫，空間極省 |
| **分支衝突** | 可能兩份目錄切換到相同分支 | Git 強制同一分支不可被兩個 worktree 同時 checkout（天然防呆） |
| **合併回主線** | 需要進行 push/pull 或手動搬移 | 同一個 repo 內直接進行本地 `git merge` |
| **總覽與清理** | 工作區散落各處、需手動逐一刪除 | 可使用 `git worktree list` / `git worktree remove` 統一管理 |
| **與框架契合度** | 無 | 與框架掛載唯讀輸入的設計概念一致 |

> [!NOTE]
> **概念區分：**
> - **Workspace (`--name`)**：代表同一個工作目錄內的不同需求，**僅能輪流跑**。
> - **Worktree**：代表多個獨立的工作目錄，**可以真正並行跑**。

---

## 4. 手動標準流程 (Under the Hood)

如果您或 Agent 想了解其底層運作方式，以下為手動建立並行工作區的標準流程：

```bash
# 1. 建立一個新 worktree 工作目錄並開新分支
git worktree add ../myrepo-featA -b loop/featA

# 2. 切換到新 worktree 目錄
cd ../myrepo-featA

# 3. 初始化對應的 workspace (指回原本的共享框架路徑 $FW)
python3 $FW/init-project.py . --name featA

# 4. 啟動規劃與執行 Loop (推薦使用 Web Dashboard 啟動，避免手動跑 python 命令)
#    A) 在框架根目錄執行：python dashboard/main.py 啟動控制台
#    B) 開啟 http://127.0.0.1:8000 點擊「+ Track」追蹤此 worktree 目錄與 workspace (featA)
#    C) 點擊「Start」按鈕一鍵啟動
#    (手動 CLI 啟動備案：python3 $FW/engine/run.py --workspace featA)

# 5. 任務完成後，切換回原本的主 worktree 目錄
cd -

# 6. 將分支合併回主線
git merge loop/featA

# 7. 移除 worktree 工作目錄
git worktree remove ../myrepo-featA
```

---

## 5. 使用 `parallel.py` 一鍵完成

我們提供了 `parallel.py` 輔助指令，將上述手動步驟簡化為單一指令，方便人類與 Agent 呼叫。

### 5.1 建立並行工作區 (`add`)
在您目前的工作目錄下，執行：
```bash
python3 $FW/parallel.py add <分支名稱> [--name 工作區名稱] [--path 目的路徑] [--base 基準分支/Commit]
```
- **預設路徑**：若未提供 `--path`，會自動在同層目錄建立名為 `../<當前repo名稱>-<分支名稱>` 的目錄。
- **自動初始化**：建立 worktree 後，會自動調用 `init-project.py` 初始化指定名稱的 workspace。

### 5.2 查詢所有並行任務狀態 (`list`)
```bash
python3 $FW/parallel.py list
```
該命令會掃描所有註冊的 worktree，並顯示類似下方的即時狀態表格：
```text
+----------------------+------------+-----------+------------+-------+-------+
| Worktree Path        | Branch     | Workspace | Status     | Phase | Stuck |
+----------------------+------------+-----------+------------+-------+-------+
| /path/to/main-repo   | main       | default   | ⏸ idle     | 1     | 0     |
| /path/to/repo-featA  | loop/featA | featA     | 🟢 running | 2     | 1     |
+----------------------+------------+-----------+------------+-------+-------+
```
- **Status 說明**：
  - `🟢 running`：該 worktree 的 loop 正在運作中（lock 存在且新鮮）。
  - `⚠️ stale-lock`：lock 存在但已過期（大於 3600 秒無更新）。
  - `⏸ idle`：當前無執行中的 loop。

### 5.3 移除並行工作區 (`remove`)
```bash
python3 $FW/parallel.py remove <分支名稱或路徑> [--force]
```
- **安全保護**：若目標工作區的 Status 為 `🟢 running`，命令預設會被攔截拒絕，以防意外中斷正在執行的 loop。
- **強制執行**：加上 `--force` 可以跳過安全檢測並移除含有未 Commit 變更的工作目錄。
- **分支處理**：出於安全考量，移除工作目錄**不會**自動刪除 Git 分支。您可以在確認合併後手動執行 `git branch -d <branch>` 刪除分支。

---

## 6. 注意事項

1. **獨立的 Review Gate**：每個 worktree 具有獨立的 `CONTROL.md` 和階段狀態。若是運行於 `gated` 模式，當規劃收斂時它會在各自的目錄停下，等待您或 Agent 進行 review。
2. **手動解決衝突**：在將分支合併回主線時，如遇程式碼衝突，請按照常規的 Git 衝突解決流程進行處理。
3. **清理殘留鎖**：若顯示為 `⚠️ stale-lock`，代表上次執行可能異常中斷。可在確認沒有執行中程序後，加上 `--force` 進行移除，或手動刪除該工作區 `.loop/<ws>/.loop_state/run.lock` 檔案。
