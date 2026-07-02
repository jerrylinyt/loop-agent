# 🌙 計畫書 2 — Overnight 工作流（下班放置跑、隔天驗收）

> **狀態**：待執行
> **依賴**：計畫書 1（RUN_REPORT / notify / finish 流程、duration 欄位）
> **產出 branch**：`refactor/2-overnight-workflow`
> **對應 review**：§2 診斷 C、§4 全節

## 0. 目標

把「同事下班前 5 分鐘放下去、隔天早上 10 分鐘驗收」變成框架的一等公民流程：

1. **隔離分支模式**：loop 的所有 commit 落在自己的分支，人的分支永遠乾淨（採用意願關鍵）。
2. **統一 CLI `loop`**：一個入口取代 init-project.py / run.py / parallel.py 的散裝體驗。
3. **doctor / smoke**：下班前能在 2 分鐘內確認「今晚跑得起來」。
4. **需求確認 / plan 核可 / 完工驗收** 三個人類 gate 都有明確的蓋章指令與產出物。
5. **人類回饋通道**：驗收的人能「留話給 loop」再繼續跑。

**不在本計畫範圍**：state schema / prompts / review gate 的改動（計畫書 4）。

---

## T1｜隔離分支模式（預設開啟）

**變更規格**：
1. config 新增 `workspace.run_branch: "auto"`（`auto` | `off`）。**預設 auto**（不需相容舊行為）。
2. 新函式 `git_utils.ensure_run_branch(cfg, control, log) -> str`，在 `_run_plan_locked` / `_run_execute_locked` 進迴圈前（sync_framework_docs 之前）呼叫：
   ```
   off → 什麼都不做，回傳當前 branch。
   auto:
     a. state.json 讀 control.run_branch：
        - 已設且該 branch 存在 → git switch <run_branch>（可能是 gated 流程的第二段，接續同一分支）。
        - 未設 → 記下當前 branch 為 base_branch → git switch -c loop/<workspace>/<YYYYMMDD-HHMM>
          → state 寫入 control.run_branch / control.base_branch（經 state.py 白名單，新增這兩鍵，僅引擎可寫）。
     b. 若當前已在 control.run_branch 上 → no-op。
     c. git switch 失敗（例如 dirty tree 擋 switch）→ preflight 級錯誤，停止不進迴圈。
   ```
3. **dirty tree 防呆**：preflight 新增檢查 `working_tree_clean`（`git status --porcelain` 為空；`.loop/` 底下的變更豁免）。不乾淨 → error，提示「請先 commit/stash，或 `--allow-dirty` 略過」。`run.py` 新增 `--allow-dirty` flag（環境變數 `LOOP_ALLOW_DIRTY=1` 傳遞給子程序）。
4. reset-plan / reset-execute-state 不動分支（在哪個分支就重置哪個）。
5. RUN_REPORT（計畫書 1 T12）的「diff 摘要」節改為：`git diff --stat <base_branch>...HEAD` + 「驗收指令提示：`git diff <base_branch>...<run_branch>`」。

**驗收**：
- 新測試 `test_ensure_run_branch_creates_and_persists`、`test_ensure_run_branch_reuses_existing`、`test_dirty_tree_blocks_run`。
- 手動：gated 全流程（plan → execute）兩段都落在同一 `loop/<ws>/<ts>` 分支；base branch 上零新 commit。

## T2｜統一 CLI：`loop` 指令

**變更規格**：
1. 新檔 `cli.py`（repo 根）+ `pyproject.toml` 定義 console script `loop = cli:main`（`pip install -e <framework>` 即可用；未安裝時 `python3 <fw>/cli.py …` 等效）。
2. 子命令表（全部是對既有功能的薄包裝，**不得複製邏輯**，import 對應模組呼叫）：

   | 子命令 | 委派對象 | 備註 |
   |--------|----------|------|
   | `loop init [repo] [--name] [--profile]` | init-project.py 邏輯（搬進 `cli_init.py` 模組，init-project.py 改為 shim 呼叫它） | `--profile` 見 T3 |
   | `loop plan / run / execute` | run.py `--stage plan / all / execute` | 透傳 `--workspace/--quiet/--mode/--allow-dirty` |
   | `loop status [--json]` | 新實作：讀 state.json + run.lock，輸出一屏摘要（phase、任務計數、stuck、human_required、run_branch、是否運行中） | |
   | `loop report` | engine/report.py | |
   | `loop resume [--note "…"]` | 見 T7 | |
   | `loop reset-plan / reset-execute` | run.py 對應 stage | |
   | `loop doctor` | 見 T4 | |
   | `loop smoke` | 見 T5 | |
   | `loop confirm-requirements` | 見 T6 | |
   | `loop approve-plan` | 見 T6 | |
   | `loop accept / reject [--note]` | 見 T8 | |
   | `loop worktree add/remove/list` | parallel.py | |
3. 所有子命令共用 `--workspace/-w`；在非 code-repo 目錄執行時給出明確錯誤（找不到 `.loop/`）。
4. 文件全面改版：README 的指令範例改用 `loop …`（`python3 run.py` 寫法移到「進階/無安裝」附註）；`generators/bootstrap.md` STEP 1/5 的指令同步改。

**驗收**：`loop --help` 列出全部子命令；每個子命令 `--help` 可用；新測試 `test_cli_dispatch`（mock 委派、驗證參數透傳）；README/bootstrap 無殘留舊入口為主要指引。

## T3｜CLI/模型 profile 預設組

**變更規格**：
1. 新目錄 `profiles/`，每檔一個 YAML，至少四份：`claude-code.yaml`、`codex.yaml`、`opencode.yaml`、`gemini-cli.yaml`。格式：
   ```yaml
   # profiles/claude-code.yaml
   label: "Claude Code CLI"
   agent:
     build_cmd: "claude -p {prompt} --model {model} --permission-mode acceptEdits"
     models: { fast: "claude-haiku-4-5", normal: "claude-sonnet-5", thinking: "claude-opus-4-8" }
   notes: "需先 claude login；模型名請依 `claude models` 實際輸出校正。"
   ```
   （各檔的 build_cmd/模型名以該 CLI 當前實際語法為準，執行本計畫的 agent 需逐一查證後填寫，並在 notes 註明查證日期。）
2. `loop init --profile <name>`：把 profile 的 `agent:` 區塊合併進生成的 `loop.config.yaml`（取代佔位值）；不帶 `--profile` 時互動列出可選 profile（含 `custom` = 保留佔位值）。
3. profile 只是初始化時的**拷貝來源**，不參與 runtime cascade（避免又多一層設定來源）。

**驗收**：`loop init /tmp/x --profile opencode` 後 config 無 `<佔位>` 字樣、preflight models 檢查綠；新測試 `test_init_profile_merge`。

## T4｜`loop doctor`：含真實 smoke 呼叫的健檢

**變更規格**：
1. 執行順序：
   - 先跑 `structured_preflight`（stage 依 state 現況自動判：無 state.json → plan，有 → execute），逐項印出。
   - 追加動態檢查：
     - **agent CLI 冒煙**：用 `build_cmd` + `models.fast` 組指令，prompt 固定為 `Reply with exactly: OK`，timeout 120s。判定：rc==0 → pass；rc≠0 或逾時 → fail，印出 stderr 尾 20 行（**這是抓「token 過期/未登入/模型名錯」的唯一可靠手段**）。加 `--no-llm` 可跳過（CI 用）。
     - 磁碟剩餘空間 ≥ 2GB（`shutil.disk_usage`）。
     - `notify_cmd` 若有設：以 status=doctor 觸發一次，讓使用者確認通知收得到。
2. 輸出末行固定：`DOCTOR OK（今晚可跑）` 或 `DOCTOR FAILED（N 項）`；exit code 0/1。

**驗收**：新測試 `test_doctor_smoke_pass/fail`（build_cmd 指向 `echo OK` / `false`）；`loop doctor --no-llm` 在 CI 可跑。

## T5｜`loop smoke`：3 輪封頂試跑

**變更規格**：
1. 等效於 `run.py --stage execute` 但：runtime.max_rounds 臨時覆寫為 3（環境變數 `LOOP_MAX_ROUNDS_OVERRIDE`，`load_config` 尾端讀取套用）、不觸發 notify、結束後印精簡三行結論：跑了幾輪 / 有沒有 commit / state 有沒有推進（比對起訖 `progress_signature`）。
2. 因 max_rounds 到頂會走 human_required 路徑（計畫書 1 語意），smoke 模式下改為中性 status `smoke_finished`（不設 human_required flag，避免污染正式 run 的 resume 流程）：實作為 loop.py 認得 `LOOP_SMOKE=1` 時，max_rounds 停止不呼叫 `set_human_required`。
3. plan 尚未收斂時 `loop smoke` 直接拒絕（提示先跑 plan）。

**驗收**：新測試 `test_smoke_caps_rounds_and_skips_human_flag`；手動：假 agent（`build_cmd: "git commit --allow-empty -m smoke"` 類）跑 smoke 正常結束、human_required 仍為 false。

## T6｜需求確認與 plan 核可：從君子協定變硬 gate

**變更規格**：
1. **需求確認**：
   - `structured_preflight` 的 `requirements_confirmed` 在 `stage=plan` 時 severity 從 warning 改 **error**。
   - `loop confirm-requirements`：在 REQUIREMENTS.md 末尾 append `\n---\nREQUIREMENTS CONFIRMED（<git user.name>，<YYYY-MM-DD HH:MM>）\n` 並 git commit。已有標記時 no-op 提示。
2. **plan 核可（gate#2 蓋章化）**：
   - plan_loop 收斂時（`plan_status=converged` 寫入處）順手產出 `.loop/<ws>/PLAN_SUMMARY.md`：純引擎端確定性生成（不叫 LLM）——各 phase 名稱/任務數/converge_threshold、任務表（id/title/depends_on/verify 類型）、依賴環檢查結果、輪數估算（Σ 任務數×(1+threshold) + final_pass_gte + 10% buffer，公式印出來）、OPEN issues。
   - state.json `plan` 物件新增 `plan_approved: false / plan_approved_by / plan_approved_at`（引擎與 approve 指令可寫）。
   - `loop approve-plan`：檢查 `plan_status == converged` → 設 `plan_approved=true` + by/at → git commit。
   - `run.py --stage execute` 的 preflight 新增檢查：gated 模式下 `plan_approved != true` → error「plan 尚未核可，請 review PLAN_SUMMARY.md 後執行 loop approve-plan」。auto 模式不要求（auto 的語意本來就是跳過 gate#2）。
   - reset-plan 時把 `plan_approved` 歸零。

**驗收**：新測試 `test_execute_blocked_without_plan_approval`、`test_confirm_requirements_appends_marker`、`test_plan_summary_generated_on_convergence`；PLAN_SUMMARY 對 fixture plan 的輪數估算數字正確。

## T7｜人類回饋通道：`loop resume --note`

**變更規格**：
1. `loop resume`：
   - 檢查 `human_required`（或 `plan_human_required`）為 true，經 `set_human_required(..., False, source="resume")` 既有管道清除；接著依 state 現況重新啟動對應 stage（plan 未收斂 → plan；否則 execute）。
   - `--note "<text>"`：寫入 `.loop/<ws>/HUMAN_NOTES.md`，格式為 append 區塊：`## <ts> by <git user.name>\n<text>\n`。**單則上限 4,000 字元**，超過拒絕（防 context 汙染，見計畫書 3）。
2. **注入機制**：`loop.py` 組 prompt 處（`base_prompt` 之前，與 `_pending_revert_notice` 同位置）：
   - state 新增欄位 `control.human_note_inject_until_round`（引擎寫）。resume 帶 note 時設為 `<下一輪起算 + runtime.human_note_rounds(預設 3)>`。
   - 輪次在注入窗口內 → prompt 前綴：`📌 人類裁決附註（優先於既有規劃衝突處，請先讀）：\n<HUMAN_NOTES.md 最後一則區塊>`。
   - 窗口過後自動停止注入（檔案保留作為歷史）。
3. HUMAN_NOTES.md 進版控（是裁決記錄）。

**驗收**：新測試 `test_resume_clears_flag_and_restarts`、`test_note_injected_for_n_rounds_then_stops`、`test_note_size_cap`。

## T8｜完工驗收 gate：`loop accept / reject`

**變更規格**：
1. `LOOP COMPLETE` 語意調整：loop.py 停止條件成立時，state 新增 `control.awaiting_acceptance=true`（引擎寫），RUN_REPORT 的「建議下一步」印出 accept/reject 指令。exit code 維持 0。
2. `loop accept`：
   - 檢查 `awaiting_acceptance` → 設 false、記 `accepted_by/at`。
   - 若在 run_branch 模式：印出合併指引（`git switch <base> && git merge <run_branch>`）；帶 `--merge` 時代為執行（僅 fast-forward 或普通 merge，衝突即中止交人，不自動解）。
3. `loop reject --note "<text>"`：設 `awaiting_acceptance=false`、寫 HUMAN_NOTES（T7 通道）、印出下一步選項（`resume`（帶 note 繼續修）/ `reset-execute --reset-to-phase …` / `reset-plan`），**不自動選**——這是價值判斷，留給人。
4. `is_done()` 不變（客觀停止條件照舊）；awaiting_acceptance 只是完成後的標記，不阻擋任何引擎路徑（避免死結）。

**驗收**：新測試 `test_complete_sets_awaiting_acceptance`、`test_accept_records_and_clears`、`test_reject_writes_note`。

## T9｜「下班前 checklist」文件

**變更規格**：新檔 `docs/checklist-before-leaving.md` 並在 README 頂部連結。內容（一頁）：
```
□ git status 乾淨、在預期的 repo/branch
□ loop doctor 綠（含 LLM 冒煙 = token 有效）
□ loop smoke 過（agent 真的會動、會 commit）
□ notify_cmd 設好且 doctor 測通（半夜停機你收得到）
□ runtime.max_wall_seconds 設了（例：36000 → 早上 7 點前一定收工）
□ 用 tmux / nohup / dashboard 掛著（SSH 斷線不殺 loop）
□ 隔天：讀 .loop/<ws>/RUN_REPORT.md → 看 diff → loop accept / reject --note / resume --note
```
並附「常見夜間死法對照表」：token 過期 → cli_failing 停機（doctor 冒煙可預防）；規格矛盾 → human_required + FROZEN；空轉 → idle watchdog。

**驗收**：文件存在、README 連結有效、內容與本計畫實作的指令一致。

## T10｜REPO_MAP：機械生成 repo 地圖（CLI 中立的知識管道）

**動機**：無狀態 agent 每輪重新摸路（grep 目錄結構、找 build 指令）浪費 token 與輪內時間。地圖層知識是機械可抽取的，**全程不呼叫 LLM**。
**設計原則（CLI 中立）**：框架**不假設**任何 CLI 會自動讀某個知識檔——保證線是框架自己的 prompt 管道；各家 CLI 的原生知識檔（Claude Code 的 `CLAUDE.md`、opencode/codex 的 `AGENTS.md`、gemini-cli 的 `GEMINI.md`…）只作為**鏡射優化**，有就餵、沒有也不影響功能。

**變更規格**：
1. 新模組 `engine/repomap.py`：`generate_repo_map(repo_path) -> str`，純機械生成：
   - 目錄樹（深度 ≤ 3；排除 .gitignore 命中項；每目錄附檔數統計）；
   - 偵測到的指令：package.json scripts / Makefile targets / pyproject（test/lint 相關）→ 列成「可能的 build / test / lint 指令」表；
   - 語言組成（`git ls-files` 副檔名統計 top 5）；
   - loop 保留區一句話說明（`.loop/` 的角色、勿手動編輯 state.json）。
2. **正本（canonical）**：寫入 `.loop/REPO_MAP.md`（repo 級、跨 workspace 共享、進版控）。所有管道都以此檔為單一事實來源。
3. **主管道（保證線，CLI 中立）**：引擎 prompt 注入——
   - config 新增 `runtime.repomap_inject: pointer | embed | off`（預設 `pointer`）。
   - `pointer`：base prompt（v2 時代）/ 任務卡（計畫書 4 落地後）固定加一行：「repo 佈局與 build/test 指令見 `.loop/REPO_MAP.md`，需要時再讀，勿自行重新探索目錄結構」。
   - `embed`：直接內嵌正本全文（上限 8KB，超過自動退回 pointer 並 warning）——給「讀檔成本高／不擅長主動讀檔」的 CLI 用。
4. **鏡射管道（優化線，可選）**：
   - profile（T3）欄位改為**清單** `knowledge_files: ["CLAUDE.md"]`（可空；一個 repo 的同事可能用不同 CLI，`loop repomap --mirror AGENTS.md` 可追加鏡射目標，記錄於 config）。
   - 鏡射內容寫入各檔的 `<!-- LOOP:REPO_MAP:start -->` / `<!-- LOOP:REPO_MAP:end -->` 標記區塊；**檔案已存在時只替換標記區塊、絕不動人寫的其他內容**；不存在則建立。
   - 正本更新時所有鏡射一併刷新（單一事實來源，鏡射永不手改）。
5. 觸發時機：`loop init` 生成並提示人過目一次（機械生成也可能誤導，如殘留的過時 Makefile）；`loop repomap` 手動重生成；`loop doctor` 檢查陳舊度（生成時間點之後 repo 已新增 > 200 個 commit → warning 建議重生成）＋檢查鏡射與正本一致。
6. `generators/0-requirements-interview.md` 補一句：訪談收尾確認 REPO_MAP 已生成且使用者掃過一眼。

**驗收**：`test_repo_map_mechanical_content`（fixture repo 斷言含目錄樹/指令表/語言統計）、`test_repo_map_mirrors_multiple_files`（兩個鏡射目標同步更新且與正本一致）、`test_repo_map_managed_section_preserves_user_content`（既有知識檔的人寫內容在重生成後 byte-level 不變）、`test_prompt_repomap_pointer_and_embed_modes`（pointer/embed/off 三模式 + embed 超限退回 pointer）、`test_doctor_warns_stale_repomap`。

---

## 最終驗收清單

- [ ] 全新 repo 端到端手動演練一次完整劇本：`loop init --profile … → confirm-requirements → plan → approve-plan → doctor → smoke → run →（模擬完成）→ report → accept --merge`，每步輸出符合本計畫書描述
- [ ] base branch 全程零新 commit；所有 loop commit 在 `loop/<ws>/<ts>` 分支
- [ ] `pytest engine/` 全綠，本計畫新增測試 ≥ 14 個
- [ ] gated 模式下未 approve-plan 無法進 execute（preflight error 實測）
- [ ] `loop resume --note` 的附註確實出現在下一輪 agent prompt（log 可查），3 輪後消失
- [ ] README、engine/README.md、bootstrap.md、checklist 文件一致採用 `loop` CLI 為主要入口
- [ ] REPO_MAP：init 生成受管區塊、重生成不動人寫內容、doctor 陳舊警告，三者經 fixture 驗證
