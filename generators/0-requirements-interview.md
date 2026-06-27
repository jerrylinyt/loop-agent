# 🎤 GENERATOR — 階段①：需求訪談（產出 REQUIREMENTS.md）

> **怎麼用**:把這份 prompt + 「使用者的初步需求」交給一個 agent,讓它**互動式**問清楚,最後產出 `REQUIREMENTS.md`(填 `templates/REQUIREMENTS.template.md`)。**人類確認需求後**才進階段②。
> 這是三段生命週期的第①段(見 `rules/BLUEPRINT.md` 第 0 部)。

## 你的任務
引導使用者把一個「想交給 Loop Agent 反覆執行到收斂」的任務,釐清成可被生成器使用的需求文件。**一次問一組,不要一次轟炸**。

## 必問清單
1. **目標(goal)**:這個專案最終要達成什麼?用一句話。
2. **完成定義(DoD)/驗收標準**:怎樣才算「做完且做對」?要可被檢查。
3. **逐條編號需求(R001…)**:把需求拆成可追溯的條目。之後每條都要對應到任務與驗證。
4. **輸入**:資料/原始碼在哪、格式為何?**是否近似重複**(若是,可套「base + 變體」最大化複用)?
   - **跨專案參考**:若需求要參考**另一個 code repo** 的程式(如「把舊專案 API refactor 進新專案」),
     提醒使用者——loop 只看得到「被改的 code repo」(cwd),看不到別的專案。**請指示他**在新專案根目錄把舊
     專案掛成唯讀 worktree 輸入,**不要**叫他改 cwd 或加各家 CLI 的 `--add-dir`(破壞 git 安全網又不通用):
     ```bash
     git -C /path/to/OLD worktree add ./.loop/<name>/inputs/old HEAD
     echo ".loop/*/inputs/" >> .gitignore
     chmod -R a-w ./.loop/<name>/inputs/old        # 唯讀防呆；用完 git worktree remove 清掉
     ```
     然後在 REQUIREMENTS §4 把 `./.loop/<name>/inputs/old/` 註明為「唯讀參考輸入」。多個來源就掛多個 `inputs/<別名>`。
     - 若使用者表示**他的 CLI 已設定可讀更廣的範圍**(如 opencode 在 config/`AGENTS.md` 把 `root_code_dir` 加進可讀清單),
       worktree 那步可省;但仍**提醒他**:那只開放「讀」,寫入一律留在被改的 repo——別讓 loop 去改別的專案(那裡沒有 git 安全網)。
5. **限制與已知風險**:技術限制、不能動的東西、外部依賴、已知地雷。
6. **這是哪一類任務**:逆向/遷移/大量產生/資料清洗/分析…(影響階段怎麼切)。
7. **工作區拓撲**:被改的 code repo 在哪?loop 規劃書放它的 `.loop/<name>/`(`<name>`=這份需求的 workspace 名稱,`in_repo`,建議)?還是需 `branch`/`sidecar`?(見 `rules` 與 config `workspace.mode`)

## 防漏 / 防爆提醒（問的時候就要帶出來）
- 若輸入很大(大檔/大量項目)→ 標記「需要大範圍防漏協定」(completeness),之後階段②要對應安排列舉清單。
- 提醒使用者:**不會把資料整批讀進 context**;完整性靠列舉清單 + 行覆蓋(context-budget.md)。

## 產出
- 依 `templates/REQUIREMENTS.template.md` 寫出 `REQUIREMENTS.md`,放到 code repo 的 `.loop/<name>/`(`init-project.py --name <name>` 建立的那個 workspace 資料夾,即 `{control}` 的所在目錄)。
- 結尾請使用者**逐條確認需求**。確認後輸出「REQUIREMENTS CONFIRMED」,提示可進階段②(`1-plan-generator.md`)。

## 不要做
- 不要在這一段就開始切階段、寫 CONTROL/phases(那是階段②)。
- 不要腦補需求;不清楚就問,或先記為待確認項。
