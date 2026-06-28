# 計畫書：同 repo 並行多工（git worktree）

> 給實作 agent 的自足規格。讀完此檔即可動工，不需回看對話。
> 目標讀者：冷啟動的實作 agent。所有檔案路徑相對於框架根目錄
> `C:\Users\yuting\IdeaProjects\loop-engineering`（= `init-project.py` 所在目錄，下稱 `$FW`）。

---

## 1. 背景與要解的問題

本框架的硬限制（已寫死在文件與程式註解）：**同一個 code repo 不能同時跑兩個 loop**，因為
執行迴圈會直接改 `src/`，兩個無狀態 agent 會邏輯互蓋。engine 只有「per-workspace 單一啟動鎖」
（`acquire_run_lock`，見 `engine/utils.py:27`），防的是「同一 workspace 被啟動兩次」，**並不防**
「同一 repo 兩個 workspace 同時跑」。

證據鏈（實作時請對齊這些既有敘述）：
- `README.md:33`：「一次只跑一個：同一個 code repo 不要同時跑兩個 loop（會直接改 `src/`，邏輯互蓋）」
- `init-project.py:11-12`（docstring）：同上，且明說「engine 只有單一啟動鎖防同一 workspace 被啟動兩次」
- `rules/git-safety.md:22-23`：還原點 / review-gate 只保護「本專案這一個 git 樹」；寫入一律留在 cwd 工作區

使用者需求：要能對同一個 repo「多工」（同時推進多條獨立任務）。

## 2. 已定方案：git worktree（不是複製整個 repo）

讓每條任務有**自己的工作目錄 + 自己的 branch**，即可繞過「互蓋 src/」限制，又各自落在獨立 git 樹
（符合 `git-safety.md` 的安全網前提）。worktree 勝過 `cp -r` / 重新 clone 的理由：

| 面向 | 複製多份 repo | git worktree（採用） |
|------|--------------|---------------------|
| 磁碟 | N 倍 `.git` | 共用同一 `.git` 物件庫 |
| branch 衝突 | 可能兩份同 branch | git 強制同 branch 不可被兩 worktree 同時 checkout（天然防呆） |
| 合併回主線 | 需 push/pull 或手搬 | 同 repo 內 `git merge` |
| 總覽 / 清理 | 散落、手動刪 | `git worktree list` / `git worktree remove` |
| 與框架契合 | — | 框架已用 worktree 掛唯讀輸入（`README.md:193`、`git-safety.md:22`），概念一致 |

**關鍵咬合**：engine 的啟動鎖是 per-workspace 的，且每個 worktree 是獨立工作目錄、各自有
`.loop/<ws>/.loop_state/run.lock`，所以兩個 worktree 各跑各的 loop 不會撞鎖、不會互蓋 `src/`。

> 概念區分（doc 與 help 都要講清楚）：
> **workspace（`--name`）= 同一個工作目錄裡的多份需求，輪流跑**；
> **worktree = 多個工作目錄，可真並行**。並行多工的正解是 worktree。

## 3. 交付物（4 項）

1. 新檔 `parallel.py`（放框架根目錄，與 `init-project.py` 同層）—— 見 §4。
2. 新檔 `docs/parallel-multitasking.md`（使用者指引）—— 見 §5。
3. 修改 `README.md`：在「## 其他你可能在意的」區塊加一段並行多工，連到 (2)。
4. 修正既有矛盾：`init-project.py:107` 目前印「兩個 workspace **可並行執行**」，與 `README.md:33`
   /本檔 docstring 的「一次只跑一個」直接衝突。改成導向 worktree —— 見 §6。

---

## 4. `parallel.py` 規格

### 4.1 通則
- 風格對齊 `init-project.py`：檔頭中文 docstring；開頭做 `sys.stdout/stderr.reconfigure(encoding="utf-8")`
  的 try/except（Windows cp950 主控台）；輸出用 emoji 前綴（`✅ + ~ ❌`）。
- Python 3.10+（既有程式已用 `list[dict]` / `str | None`）。
- `FRAMEWORK = os.path.dirname(os.path.abspath(__file__))`（= `$FW`）。
- **一律以 cwd 當「主 worktree / 目標 repo」**，與 engine「從 code repo 根目錄跑」一致。
  進入點先驗證 cwd 是 git 工作區（`git rev-parse --show-toplevel`；失敗就 `❌` 並 return 1）。
- 呼叫 git 用 `subprocess.run([... ], capture_output=True, text=True, encoding="utf-8")`；
  非零退出要把 stderr 印出來、return 1。不要用 shell=True。
- 🚨 **絕不自動跑 `engine/run.py` / `plan_loop.py` / `loop.py`**。啟動長迴圈是刻意保留給人類的決策點
  （`README.md:15-16`）。`parallel.py` 只「準備好 + 印出下一步指令」。

### 4.2 子指令：`add`
```
python3 $FW/parallel.py add <branch> [--name WS] [--path DIR] [--base REF]
```
行為（依序）：
1. 算 worktree 路徑：`--path` 優先；否則預設 sibling 目錄 `../<repo-basename>-<sanitized-branch>`，
   其中 `sanitized-branch` 把 `/` 換成 `-`（例：branch `loop/featA` → `myrepo-loop-featA`）。
2. 判斷 branch 是否已存在：`git rev-parse --verify --quiet refs/heads/<branch>`。
   - 不存在 → `git worktree add <path> -b <branch> [<base 或 HEAD>]`（從 base/HEAD 開新 branch）。
   - 已存在 → `git worktree add <path> <branch>`（checkout 既有 branch；若已被別的 worktree 佔用，
     git 會自己報錯，原樣轉達即可）。
3. workspace 名稱：`--name` 預設取 sanitized-branch（讓 worktree 與 workspace 名字對得起來）。
   在新 worktree 內建 workspace：`subprocess` 呼叫
   `[sys.executable, os.path.join(FRAMEWORK, "init-project.py"), <path>, "--name", <ws>]`
   （重用既有邏輯，不要複製 init-project 的程式碼）。
4. 印出下一步（**不執行**）：
   ```
   cd <path>
   python3 $FW/engine/run.py --workspace <ws>      # gated 預設
   ```
   並提醒：這是另一條獨立 loop，可與主 worktree 的 loop 同時跑。

邊界：worktree 路徑已存在且非空 → `❌` 擋下，不要硬上。

### 4.3 子指令：`list`
```
python3 $FW/parallel.py list
```
1. `git worktree list --porcelain` 解析（每段以空行分隔；欄位 `worktree <path>`、`HEAD <sha>`、
   `branch refs/heads/<name>` 或 `detached`）。
2. 對每個 worktree，掃 `<path>/.loop/*/`（只取目錄，每個目錄 = 一個 workspace）。對每個 workspace：
   - **執行中判斷**：看 `<path>/.loop/<ws>/.loop_state/run.lock` 是否存在且新鮮。
     新鮮 = `time.time() - os.path.getmtime(lock) < 3600`（engine 殘留鎖門檻下限是 3600s，
     正常跑有心跳 `touch_run_lock` 會持續更新 mtime，見 `engine/utils.py:21-24,55-59`）。
     - 存在且新鮮 → `🟢 running`
     - 存在但過期 → `⚠️ stale-lock`
     - 不存在 → `⏸ idle`
   - **phase / stuck**：若 `<path>/.loop/<ws>/CONTROL.md` 存在，讀單行 k:v 欄位
     `current_phase` 與 `stuck_level`（格式見 `rules/state-model.md`；可用簡單 regex
     `^current_phase:\s*(.+)$` 逐行抓，不必引 PyYAML）。沒有就顯示 `-`。
3. 以表格印出：`worktree 路徑 | branch | workspace | 狀態 | phase | stuck`。
   沒有任何 `.loop/<ws>` 的 worktree 也印一行（workspace 欄顯示 `-`），讓使用者看得到主 worktree。

> 註：`~/.loop/index.md`（`engine/utils.py:102 update_index`）是跨「所有專案」的總覽，欄位為
> `專案 | repo | workspace | phase | stuck | 狀態 | 更新`，key=`(repo, workspace)`。
> `parallel.py list` 聚焦「當前這個 repo 的各 worktree」，直接讀各 worktree 的 run.lock/CONTROL
> 即可，**不需**解析 index.md（避免與跨專案總覽職責重疊）。

### 4.4 子指令：`remove`
```
python3 $FW/parallel.py remove <branch-or-path> [--force]
```
1. 把輸入解析成 worktree 路徑（可接受路徑，或 branch 名 → 從 `git worktree list --porcelain` 反查）。
2. **安全閘**：若該 worktree 內任一 workspace 有「新鮮 run.lock」（判定同 §4.3）→ 預設拒絕，
   提示「該 worktree 還有 loop 在跑，先停掉再移除，或加 --force」。
3. 執行 `git worktree remove <path>`（dirty working tree 時 git 本身會擋，需 `--force` 才強移）。
   把 `--force` 透傳給 git。成功印 `✅`，並提醒可用 `git branch -d <branch>` 自行刪 branch（不自動刪，
   避免誤刪未合併工作）。

### 4.5 argparse 結構
用 `add_subparsers(dest="cmd", required=True)`，三個子指令如上。`main(argv)` + `if __name__ == "__main__": sys.exit(main(sys.argv))`，回傳 int 當退出碼（對齊 `init-project.py`）。

---

## 5. `docs/parallel-multitasking.md` 內容大綱

1. **何時需要**：同 repo 想同時推進多條獨立任務。
2. **為什麼不能同 repo 跑兩個 loop**：互蓋 `src/`；引用 `README.md:33`、`git-safety.md`。
3. **worktree vs 複製 repo**：放 §2 的對比表。
4. **workspace vs worktree**：一句話區分（§2 末的框）。
5. **手動標準流程**（給想理解底層的人）：
   ```bash
   git worktree add ../myrepo-featA -b loop/featA
   cd ../myrepo-featA
   python3 $FW/init-project.py . --name featA
   python3 $FW/engine/run.py --workspace featA
   # 完工
   git worktree list
   git merge loop/featA          # 在主 worktree 合併回來
   git worktree remove ../myrepo-featA
   ```
6. **用 `parallel.py` 一鍵走**：對應 §4 的 `add` / `list` / `remove` 三段範例。
7. **注意事項**：① 各 worktree 各自 gate（gated 模式各自停下交 review）；② 合併回主線是普通 git merge，
   衝突自己解；③ 移除前先確認 loop 已停（`parallel.py list` 看狀態）。

## 6. `init-project.py:107` 修正

現況（誤導）：
```python
print(f"  同一 repo 想同時帶另一份需求 → 重跑本檔換個 --name，兩個 workspace 可並行執行。")
```
改成（與核心規則一致，並導向 worktree）：
```python
print(f"  同一 repo 想多帶一份需求（輪流跑）→ 重跑本檔換個 --name。")
print(f"  想『同時』並行多條任務 → 用 git worktree（見 docs/parallel-multitasking.md / parallel.py），")
print(f"  別在同一個工作目錄同時跑兩個 loop（會互蓋 src/）。")
```

---

## 7. 驗收標準

- [ ] `python3 $FW/parallel.py add testbranch` 在一個測試 git repo 的 cwd 執行：建出 sibling worktree、
      新 branch、worktree 內出現 `.loop/<ws>/`（REQUIREMENTS.md + loop.config.yaml），且**沒有**自動跑 run.py。
- [ ] `python3 $FW/parallel.py list` 列出主 worktree + 新 worktree，狀態欄正確顯示 `idle`
      （沒跑 loop 時），有 CONTROL 時能顯示 phase。
- [ ] 模擬新鮮 run.lock（touch 一個 `.loop/<ws>/.loop_state/run.lock`）後，`list` 顯示 `🟢 running`，
      且 `remove` 在無 `--force` 時被安全閘擋下。
- [ ] `python3 $FW/parallel.py remove testbranch` 能移除乾淨的 worktree。
- [ ] 在非 git 目錄執行任一子指令 → 友善 `❌` 訊息、退出碼非 0、不丟 traceback。
- [ ] Windows 主控台（cp950）執行不亂碼、不因 emoji 崩潰。
- [ ] `README.md` 新段落連得到 `docs/parallel-multitasking.md`；`init-project.py:107` 不再有「可並行執行」字樣。

## 8. 不在範圍

- 不改 engine（`loop.py` / `plan_loop.py` / `run.py` / 鎖機制）。worktree 方案靠既有 per-workspace 鎖
  +「各 worktree 獨立工作目錄」即足夠，無需新增跨 worktree 協調。
- 不自動合併 branch、不自動刪 branch、不自動啟動任何 loop。
