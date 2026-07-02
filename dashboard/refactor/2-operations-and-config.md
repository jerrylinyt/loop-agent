# 🎛️ Dashboard 計畫書 2 — 操作層：生命週期、人類 Gate、Config 編輯

> **狀態**：待執行
> **依賴**：dashboard 計畫書 1；docs/refactor 計畫書 2（`loop` CLI 全套子命令——本計畫的所有寫入都是它的 UI 皮）
> **產出 branch**：`dashboard/2-operations`

## 0. 原則：dashboard 永遠不是第二個寫入者

所有動作 = 後端 subprocess 呼叫 `loop` CLI（帶 `--workspace`，cwd=repo 根）。好處：引擎守衛/稽核/git 紀錄天然覆蓋；CLI 行為變了 dashboard 不用跟著改語意；出事時 terminal 重現路徑一致（「dashboard 上按的」=「終端機打的」）。

## T1｜動作執行器（Action Runner）

**規格**：
1. `POST /api/ws/{id}/actions/{name}`，body 帶參數；後端組 CLI 指令執行。長任務（start/plan/execute）**detach 背景執行**（等效 nohup；引擎自身的 lock/心跳接手管理），API 立即回 `{job_id}`；短任務（resume/approve/…）同步等待，回 `{rc, stdout_tail}`。
2. **併發防護**：同 workspace 同時只允許一個進行中 action（後端層防抖）；start 類先打 `run.py --preflight --json`，不過就把結果原樣回給前端顯示，不啟動。
3. **稽核**：每個 action 寫一行 `~/.loop/dashboard-audit.jsonl`（ts、workspace、action、參數摘要、發起端 IP、rc）。
4. 動作白名單（逐一列舉，不做通用「執行任意指令」endpoint）：
   `plan / execute / stop / smoke / doctor / resume / reset-plan / reset-execute / confirm-requirements / approve-plan / accept / reject / unlock / fsck / repomap / upgrade-ack / track(登錄 workspace) / init(見 T7，全域動作：不綁既有 workspace，參數為 repo 路徑+名稱+profile)`。
5. `stop` 實作 = 寫入引擎既有的 `stop_requested` 檔（`check_stop_requested` 機制），**不是 kill**——當前輪跑完優雅停；UI 標示「停止中（本輪結束後生效）」。另提供 `force-stop`（kill 鎖檔 pid 的 process group）藏在二次確認之後。

**驗收**：`test_action_whitelist_only`（白名單外 404）、`test_concurrent_action_rejected`、`test_stop_writes_flag_not_kill`、audit 檔逐 action 落行。

## T2｜生命週期操作 UI

**規格**：
1. workspace 頂部狀態列的動作按鈕**依狀態機顯示**（永遠只出現「當下合法」的動作）：
   - idle + 無 plan → `開始規劃`；plan converged 未 approve → `Review Plan`（跳 Plan 籤）+ `核可 Plan`
   - approved 未跑 → `開始執行`、`Smoke 試跑`；running → `停止`、`即時 Log`
   - human_required → 紅色橫幅（code + reason + `docs/errors.md#code` 連結）+ `Resume`（開附註 modal，即 `--note`）+ `fsck` / `unlock` 快捷
   - complete/awaiting_acceptance → `查看 RUN_REPORT` + `Accept`（含 `--merge` 勾選）/ `Reject`（附註必填）
2. 破壞性動作（reset-*、force-stop、reject）一律二次確認 modal，內文寫清楚後果（照 CLI 文件文案）。
3. 每個動作完成後 toast 顯示 rc 與 stdout 尾 3 行；失敗展開完整輸出。

**驗收**：E2E 覆蓋四個狀態的按鈕組合正確性；human_required fixture 下 Resume 帶 note 流程走通（斷言 note 落入 HUMAN_NOTES.md——經 CLI）。

## T3｜人類 Gate 面板（把三個蓋章點變成好按的）

**規格**：
1. **需求確認（gate#1）**：Reports 籤顯示 REQUIREMENTS.md 渲染 + 「逐條需求」checklist 視圖（parse R### 列表）；`確認需求` 按鈕 = `loop confirm-requirements`。未確認時 Plan 相關按鈕禁用並提示。
2. **Plan 核可（gate#2）**：`Review Plan` 視圖 = PLAN_SUMMARY 渲染 + 依賴圖 + 需求覆蓋矩陣 +（若有）驗收標準抽查提示（acceptance-standards §6 對照表的自動核對結果：每任務 verify.kind 是否符合任務型下限——**機械可查，dashboard 代跑**）；`核可` = `loop approve-plan`，記錄人與時間顯示於此。
3. **完工驗收（gate#3）**：RUN_REPORT 渲染 + diff 摘要連結 + `Accept / Reject`。
4. 三個 gate 的當前狀態在總覽卡片上有 chip（「等你核可 plan」）——**讓「輪到我了」主動浮上來**，而不是人去翻。

**驗收**：E2E 三 gate 全流程（fixture 驅動）；驗收標準自動核對對 fixture 中「API 任務無 integration test」給出警示。

## T4｜Config 編輯器

**規格**：
1. Config 籤兩種模式：
   - **表單模式（預設）**：只暴露白名單旋鈕，schema 驅動渲染（數字/enum/bool + 每欄位說明文案與框架預設值對照）：`generation.mode`、各 `oscillation.*`、`runtime.max_rounds / max_wall_seconds / interval_seconds / *_timeout_seconds / notify_cmd / notify_quiet_hours / heartbeat_url / parallel_slots(未來)`、`agent.models.*`。
     ⚠️ `phases[].converge_threshold` **不進可編輯表單**：執行期門檻的單一事實來源是 state 內的 per-task threshold（docs/refactor 計畫書 1 T8 的裁決），config 的該欄只是 plan 期預設——在 Plan 籤以唯讀顯示 per-task 門檻＋一行說明「要改門檻請走 reset-plan/replan」，避免使用者改了 config 卻靜默無效。
   - **原始 YAML 模式**：整檔編輯器（唯讀警示條：「進階；表單外欄位後果自負」）。
2. **存檔管線（三道欄）**：
   a. 後端以 `load_config` 實際載入合併結果做 schema/型別驗證 + 跑 `run.py --preflight --json`（不啟動），錯誤原樣顯示、拒存；
   b. 寫檔 + `git commit -m "config: edit via dashboard (<欄位摘要>)"`（可稽核可 revert）；
   c. UI 顯示**生效語意**：「引擎每次 run 啟動時讀取 config——目前 run 進行中，本次變更於下個 run 生效」（running 時顯著標示）。
3. diff 預覽：存檔前顯示 YAML diff，確認才寫。
4. 併發：以檔案 mtime 做樂觀鎖——開啟編輯後檔案被別人改過 → 拒存並提示重載。

**驗收**：`test_config_save_rejected_on_preflight_error`、`test_config_save_commits_git`、`test_config_optimistic_lock`；E2E：表單改 `stall_threshold` → diff 預覽 → 存檔 → git log 出現 commit。

## T5｜Issues 面板

**規格**：Issues 籤：OPEN 列表（BLOCKING 紅頂置）、每項展開 issue 檔內文（file API）、`標記 RESOLVED` 按鈕（= `state.py issue-set-status`，經 CLI 路徑、source=dashboard）；RESOLVED 摺疊區（讀 archive）。FROZEN 任務與其關聯 issue 互相連結（從任務抽屜一鍵跳到擋它的 issue）。為 roadmap H1.2 的 QUESTION 級預留 UI 插槽（等級 chip + 回答框，feature flag 關閉）。

**驗收**：E2E：resolve 一個 BLOCKING issue → blocking 計數歸零 → phase 紅框解除。

## T6-b｜New Workspace 精靈（把「從零開始」拉進 dashboard）

**動機**：track 只能登錄**已存在**的 workspace——「開新專案」仍得回終端機跑 `loop init` 或貼 bootstrap.md 給 agent。這是同事第一次接觸的斷點，體驗最生的一段反而沒有 UI。

**規格**：
1. 總覽頁 `＋ New Workspace` 按鈕 → 三步精靈：
   - **Step 1 初始化**：表單（repo 路徑（後端驗證是 git repo）、workspace 名稱、profile 下拉（讀 `profiles/*.yaml` 清單））→ 呼叫全域動作 `init`（= `loop init <repo> --name <ws> --profile <p>`，經動作執行器）→ 成功即入 registry、出現於總覽。init 同時生成**訪談開工檔** `.loop/<ws>/INTERVIEW.md`（規格見 docs/refactor 計畫書 2 T2 第 5 點——prompt 本體放檔案，不塞 shell 指令）。
   - **Step 2 需求訪談（主路徑：一鍵複製指令 → 貼到 terminal → 各自的 agent 完成訪談）**：
     - 精靈顯示一條**可直接執行的指令**（一鍵複製按鈕 + 大字碼區），由後端依 profile 的 `interactive_cmd` 樣板組成，形如：
       ```bash
       cd /path/to/repo && claude "請讀取 .loop/featureA/INTERVIEW.md 並完全依其指示進行"
       ```
       指令內的 prompt **只有一句**（指向開工檔）——訪談流程、產出要求、邊界規則全部在 INTERVIEW.md 裡，避免 shell 引號/跳脫地獄，也讓任何 CLI 都適用。
     - 畫面提示三行：「① 貼到你的 terminal 執行 ② 跟著你的 agent 完成訪談（它會把 REQUIREMENTS.md 寫好）③ 回到這頁按下一步」。精靈輪詢 REQUIREMENTS.md 的 mtime/內容變化，偵測到「已從樣板改寫」時自動亮起下一步按鈕。
     - **次要路徑（摺疊在「已有現成需求？」之下）**：REQUIREMENTS.md 編輯器直接貼上/手寫（載入樣板；側欄顯示 `acceptance-standards.md` §7 三必問與 DoD 模板句）。存檔比照 config 的直寫＋git commit 規則。
   - **Step 3 確認與下一步**：REQUIREMENTS 渲染 + `確認需求`（= confirm-requirements）→ 完成頁引導「跑 doctor → 開始規劃」按鈕。
2. 精靈可中途離開，狀態以檔案為準（回來時依「REQUIREMENTS 存在？已被改寫？已確認？」自動落在正確步驟——無另存精靈進度，鐵則 1）。dashboard **不代跑**訪談（互動式對話是 agent CLI 的主場；內嵌對話見計畫書 4 展望 O11）。

**驗收**：E2E：全新 tmp repo 走主路徑：init → 複製指令（斷言指令含 profile 的 CLI 與 INTERVIEW.md 路徑）→（測試以腳本模擬 agent 改寫 REQUIREMENTS.md）→ 下一步自動亮起 → 確認 → 總覽出現且 preflight 綠；次要路徑編輯器含 §7 文案；`test_init_action_validates_repo_path`（非 git repo 拒絕）；`test_interview_cmd_built_from_profile`（不同 profile 產出對應 CLI 的指令）；中途關頁重開落在正確步驟。

## T6｜安全基線

**規格**：預設僅綁 `127.0.0.1`；提供 `--token <secret>` 啟動參數（設定後所有 API 要求 `Authorization: Bearer`，前端登入頁輸入一次存 localStorage）——這是計畫書 4 團隊模式前的最低限度遠端存取方案；文件明確警告「不要裸奔綁 0.0.0.0」。

**驗收**：`test_token_required_when_enabled`。

---

## 最終驗收清單

- [ ] 全部寫入動作經 CLI（後端程式碼稽核：對 `.loop/` 的 `open(..., "w")` 僅存在於零處；audit jsonl 覆蓋每次動作）
- [ ] 四狀態按鈕矩陣、三 gate 流程、config 三道欄、issue resolve——E2E 全綠
- [ ] New Workspace 精靈 (a) 路徑從全新 repo 到「可開始規劃」全程不離開 dashboard；(b) 路徑的複製指引可直接貼進 agent CLI 使用
- [ ] 破壞性動作皆有二次確認；stop 為優雅停；force-stop 需確認
- [ ] `loop dashboard --token` 模式下未帶 token 的 API 全 401
