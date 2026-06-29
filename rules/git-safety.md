# 🧷 RULE — Git 安全網（防止檔案被弄壞）

> **唯讀框架規則**。git 在這裡的首要任務是**還原點**:任何一輪把檔案改壞,都能退回上一輪的良好狀態。
> ⚠️ **作用範圍**:git 只作用於「**工作區(被 agent 操作的 code repo)**」。

## 1. 核心機制
- **一輪一 commit**(BOOT STEP C):每輪結束提交一次,訊息含 Round/Phase/Task。每個 commit 都是乾淨還原點。
- **Git Review Gate (獨立審查)**:由引擎在下一輪執行前，自動攔截並呼叫獨立的審查 Agent (參考 `git-review-gate.md`)。專門審查上一次的 Commit Diff 是否合理。發現破壞性改動即自動 Revert。
- **局部編輯優先**:改 `state.json` / 規格檔時用局部取代或經工具原子更新,不整檔重寫,從源頭降低「變白」機率。寫完讀回確認。

## 2. 安全紅線（絕不做）
- ❌ `git reset --hard`、`git clean -fd/-fdx`、`git checkout .`（無差別覆蓋,會吃掉本輪以外的好東西）
- ❌ `git push --force`
- ❌ **改寫已提交歷史**:`git commit --amend`、`git rebase`(含 `-i`)、`git reset --soft/--mixed` 退回前輪 commit、`git filter-branch`/`filter-repo`。
  > 為什麼:本框架靠「**一輪一 commit**」當還原點,且 Git Review Gate 以 `last_safe_sha → HEAD` 的 diff 審查上一輪。
  > 改寫/合併/抹除歷史會毀掉還原點、讓 `last_safe_sha` 失效、並可被用來「重設輪次、掩蓋上一輪的壞改」。
  > 🚨 強制約束:每一輪只能**新增**一個 commit(STEP C);❌ 嚴禁修改、合併、刪除、或重新排序任何**既有** commit。
  > 要修前幾輪的錯 → 用局部編輯做成「本輪的新 commit」(必要時 `git checkout <hash> -- <檔>` 取回舊版內容再改),不准動歷史本身。
- ❌ 刪除 `.git`、刪除輸入來源
- ✅ 只允許「逐檔還原」:`git checkout HEAD -- <指定檔>`

## 3. 寫檔守則（防變白）
1. 優先用「targeted edit / 局部取代」,避免整檔重寫。
2. 每次寫完立刻讀回確認:非空、結構完整。
3. 若發現自己把檔案寫壞且「尚未 commit」→ `git checkout -- <檔>` 還原後重做。
4. **寫入白名單**:只允許寫本專案 `.loop/` (`state.json` / phases / config / log) 與工作區的產出，嚴禁破壞既有輸入檔。
   - ❌ `.loop/*/inputs/` 是**唯讀參考輸入**(常是別的專案用 `git worktree` 掛進來的):嚴禁寫入/修改/刪除。它在工作區的 git 樹之外、又被 `.gitignore`,安全網救不回它——要的資訊用讀的,要改只能改本專案。
   - ❌ 嚴禁寫入工作區(cwd)以外的任何路徑(例如別的 code repo)。即使你的 CLI 被設定成「讀得到」更廣的範圍,那也只開放讀;**寫入一律留在本專案**,因為還原點 / review-gate 只保護本專案這一個 git 樹。

## 4. Execute Agent 復原指引
1. **本輪尚未 commit 的壞改** → 若你發現自己剛才把檔案寫壞了，立刻使用 `git checkout -- <檔>` 還原，然後重新思考並修改。
2. **發現跨輪度的邏輯損壞** → 雖然有 Review Gate 把關，但若你發現幾輪前的檔案邏輯有錯需要修復，請使用局部取代慢慢修，或者使用 `git checkout <hash> -- <檔>` 取回特定舊版本。**絕對不要無差別還原 (`checkout .`)**。

## 5. 分工：引擎自動防護與獨立審查
- **獨立審查層 (Git Review Gate)**: 引擎會在每輪自動擷取上一次的 Diff，交由獨立的 Review Agent 進行嚴格的語意審查。發現中斷殘留、排版破壞或幻覺，會立刻判定 REVERT。
- **引擎執行層 (Python loop)**: 接收到 Review Gate 的 REVERT 判決後，會自動執行 `git revert HEAD --no-edit`，並記錄震盪，阻斷錯誤蔓延。引擎也會做底層的「整檔空白」兜底防護。
- **兩層都救不回(極端)**: 若自動修復無效或發生衝突，引擎會判定為卡死，停下交給人類處理。

## 6. .gitignore（初始化任務建立，工作區用）
```
node_modules/      # 或對應語言的相依目錄
dist/  build/      # 建置產物
*.log              # loop.log 等不進版控
.loop/.loop_state/ # 震盪偵測狀態(引擎用,不進版控也不進 context)
.DS_Store
```
> 輸入、產出、`.loop/` 內的 `state.json` / phases / config 都要進版控。只有相依、建置產物、log、loop_state 忽略。

## 7. commit 訊息格式
```
R012 | phase1 | TASK-05 | 推進 | <一句摘要>
R045 | phase2 | TASK-B13 | 驗證 | build/test 全綠,p2_pass=7
```
