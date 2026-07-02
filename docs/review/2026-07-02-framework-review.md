# 🔍 Loop Engineering 框架全面體檢與翻新提案（2026-07-02）

> **審查範圍**：`engine/`、`rules/`、`generators/`、`maintenance/`、`init-project.py`、`parallel.py`、README（不含 dashboard/ 與 docs/ 既有文件）。
> **審查視角**：框架核心宗旨——「讓較弱、便宜、不在乎呼叫次數的模型，反覆執行直到收斂達標」——以及新目標：**讓同事下班前放下去跑、隔天上班驗收**。
> **前提**：使用者已明確表示接受大規模翻新、重寫資料結構，**不需要考慮向後相容**。

---

## 0. TL;DR — 建議總表（依影響力排序）

| # | 建議 | 類別 | 影響 | 工作量 |
|---|------|------|------|--------|
| 1 | **任務挑選權從 agent 收回引擎**（引擎算好「本輪做哪個任務」，agent 只收到一張任務卡） | 大翻新 | ★★★★★ | 中 |
| 2 | **客觀驗證引擎化**：任務宣告 `check` 指令，引擎自己跑、自己填 PASS/FAIL，agent 不再自報結果 | 大翻新 | ★★★★★ | 中 |
| 3 | **收工報告 + 通知**：終止時自動產出 RUN_REPORT.md（逐條需求對照、輪數成本、待裁決事項），並打 webhook 通知 | 流程 | ★★★★★ | 小 |
| 4 | **預設跑在獨立 branch、完成後以 PR diff 驗收**（不再直接 commit 到人的工作分支） | 流程 | ★★★★☆ | 小 |
| 5 | **修掉 preflight 殘留 bug**：仍檢查已移除的 `tree_decompose` prompts → 新專案根本啟動不了 | Bug | ★★★★★ | 極小 |
| 6 | **Review Gate 分層**：機械檢查（Python 免費做）→ 才叫 LLM 審；13 項清單砍半 | 成本 | ★★★★☆ | 中 |
| 7 | **統一 CLI 入口 `loop`** + CLI/模型 profile 預設組 + `loop doctor` 健檢 + `--smoke` 試跑 | 團隊導入 | ★★★★☆ | 中 |
| 8 | **快速失敗偵測**：agent process 秒退（CLI 掛掉/token 過期）連續 N 次 → 立刻停機通知，別空燒到天亮 | 流程 | ★★★★☆ | 小 |
| 9 | **state.json 資料結構翻新**：扁平字串鍵 → 顯式 schema + 版本欄；rules 從「散文執法」瘦身成「引擎執法」 | 大翻新 | ★★★★☆ | 大 |
| 10 | **人類回饋通道**：`HUMAN_NOTES.md` / resume 附註，讓隔天驗收的人能「留話給 loop」再繼續跑 | 流程 | ★★★☆☆ | 小 |

---

## 1. 現況盤點：值得保留的設計資產

先講清楚哪些東西是對的、翻新時**不要丟**：

1. **外部迴圈 + 無狀態 agent subprocess** 的基本拓撲。這是整個框架最有價值的決策：agent 是「被呼叫一次的函式」，狀態全部落在文件。任何翻新都應保留這個骨架。
2. **`state.py` 的剛性守衛**（白名單、單步狀態轉移、conv 配額、guarded transition、dry-run）。這是全 repo 最正確的方向——**把規則從散文搬進程式碼**。後面所有建議基本上都是「把這個方向做到底」。
3. **Git 一輪一 commit + Review Gate + revert** 的安全網分層。
4. **震盪偵測 / 三層模型升級 / human_required 逃生門** 的概念與授權紅線（程式不自我放寬）。
5. **Context 防爆紀律**（log 不進 context、一檔一主題、按需讀 rules）。
6. **rounds.jsonl typed records**（run_started / round_finished / artifacts）——這是做收工報告、成本統計、trace 分析的地基，已經存在，只差消費端。
7. **maintenance/ 的自我爬坡機制**（trace 驅動 + 對抗式稽核 + 人類 PR gate）——方法論成熟，保留。

---

## 2. 核心診斷：三個結構性問題

### 診斷 A：執法靠散文，弱模型讀不完也守不住

整個 rules/ 目錄合計約 1,200 行，其中大量篇幅是 🚨/❌ 式的告誡：「嚴禁挑軟柿子」「嚴禁一輪多任務」「嚴禁把 FAIL 寫成 NA」「嚴禁降級 BLOCKING」……這些規則存在的**唯一原因**，是引擎把決策權交給了 agent，然後再用散文去防它濫用。

這對「弱且便宜的模型」是雙重錯配：

- **弱模型是最需要短指令的**，卻要每輪讀 `boot-sequence.md`（142 行）+ `state-cli-guide.md`（167 行）+ 按需 rules，光合規成本就吃掉大半 context 與注意力。
- **弱模型也是最會鑽縫的**（不是惡意，是理解力不足），所以 review gate 得再開一個 LLM 去審 13 條紅線，其中一半在防「agent 沒照散文做」。

**觀察一個具體訊號**：`git-review-gate.md` 13 項紅線裡，第 3、11、12、13 項（狀態跳級、證據缺失、收斂防偽、產出異動未歸零）本質上都是「狀態機不變量」，而 `state.py` 已經擋掉其中大部分（單步轉移、conv 配額、門檻檢查）。散文、LLM 審查、程式守衛**三層在重複執法同一件事**，成本花在互相補洞。

> **結論**：凡是「可機器判讀」的規則，一律下沉到引擎/CLI 執法；rules/*.md 只留「怎麼把事做好」的方法論（怎麼獨立重推、怎麼列舉防漏）。詳見 §5 翻新藍圖。

### 診斷 B：驗證體系仍以「LLM 自報 + LLM 互審」為主，客觀驗證是配角

目前的信任鏈是：agent 自報 `last_round_result=PASS` → 要求留證據檔 → 另一個 LLM（review gate）抽查證據。這條鏈有三個弱點：

1. **自報環節在弱模型手上**。所有防灌水機制（證據檔、配額、抽查）都是在補「讓不可信的人自己填成績單」這個源頭設計。
2. **審查環節也是 LLM**，同樣會漏、會橡皮圖章，於是又要 checklist 格式校驗、invalid streak、13 項強制清單……複雜度螺旋上升。
3. **真正客觀的訊號（build/test/lint 的 exit code）引擎從頭到尾沒有親手碰過**——它只出現在「agent 貼在證據檔裡的輸出」，是二手轉述。

對於「不在乎次數、在乎正確」的定位，**最便宜且最不可偽造的驗證就是引擎自己跑指令**。一個 `pytest` exit code 比三層 LLM 互審都硬。

> **結論**：把「可執行的驗收」提升為一等公民——任務宣告 `check` 指令，引擎在 agent 停機後親自執行、親自回填結果。LLM 收斂重驗只保留給真正主觀的分析型任務。詳見 §5.2。

### 診斷 C：整套系統是為「操作它的工程師」設計的，不是為「隔天來驗收的同事」

「下班前放下去跑、隔天驗收」這個使用情境，目前缺的不是引擎能力，而是**頭尾兩端的人類介面**：

- **頭**：上手要讀 README + 貼 bootstrap.md 給 agent + 手填 build_cmd/models + 記得 `--workspace` ……同事第一次用的挫折點太多。
- **尾**：跑完（或半夜卡死）之後，同事面對的是 `state.json`、`rounds.jsonl`、50MB 的 loop.log。沒有「一頁看懂昨晚發生什麼、我現在要做什麼」的產出，也沒有任何通知機制——卡死在 23:40 的 loop，會沉默地閒置到早上被發現。
- **中**：跑在使用者當前分支上直接 commit（`in_repo` 預設），意味著同事早上驗收失敗時，自己的分支已經多了幾十個 commit——心理安全感很差，這會直接影響採用意願。

> **結論**：§4 專門處理這條「overnight 工作流」，這是讓同事願意用的關鍵，優先級不低於引擎翻新。

---

## 3. 具體發現：Bug 與不一致清單（可立即修）

審查過程中發現的實際缺陷，與翻新無關、建議先修：

| # | 位置 | 問題 | 影響 |
|---|------|------|------|
| B1 | `engine/utils.py:159-164`、`utils.py:264-268` | preflight 仍要求 `tree_decompose` / `tree_decompose_gate` prompts，但 tree 已移除、`prompts.yaml` 沒有這兩鍵 → **missing_prompts 恆非空、severity=error** | **所有新專案 plan/execute 一啟動就被 preflight 擋下**，框架目前應該是跑不起來的（除非專案 config 自己補了這兩個假 prompt）。最高優先修復 |
| B2 | `engine/utils.py:143-201` vs `321-330` | `preflight()` / `report_preflight()` 各被定義兩次，前者（tuple 版）是死碼且行為不同 | 混淆維護者；舊版訊息（含 REQUIREMENTS CONFIRMED 警告文案）實際永遠不會執行 |
| B3 | `engine/plan_loop.py:261-264, 275` | 卡住升級時用 `model_tier_label(cfg, "decompose", …)`——`roles` 裡沒有 `decompose`（tree 殘留），fallback 成 `normal`；但實際選模型用的是 `plan` 角色（`thinking`） | log 顯示的模型層與實際用的模型不一致；且 plan 角色預設已是 thinking，「升級」實際上是 no-op，log 卻宣稱升級了 |
| B4 | `engine/loop.py:216-220` | Review Gate REVERT 失敗時 fallback 到 `git reset --hard` + `git clean -fd` | 直接違反 `git-safety.md` 自己的紅線；`clean -fd` 會把使用者未追蹤的檔案（包含 .gitignore 外的個人筆記、其他 workspace 的產物）整批刪掉。至少要限縮範圍或改為停機交人 |
| B5 | `engine/utils.py:358-362` | 失敗指紋用 `changed_files()`（= 當下 working tree 的 dirty 檔案）。agent 正常在 STEP C commit 後 working tree 是乾淨的 → 指紋退化成只剩 fail_tasks | 震盪偵測解析度下降：「同一批任務、不同檔案的失敗」分不開。應改用 `changed_files_between(head_before, head_after)`（該輪 commit 的實際 diff，資料已經有了） |
| B6 | `rules/state-model.md:76`、`state-cli-guide.md:155` vs `convergence.md:69`、config template | conv 門檻文件寫「預設 5」，convergence.md 寫「典型 2~3」，template 說由 agent 逐階段自訂 | 三處說法不一。弱模型會被文件間矛盾直接搞死（它無法判斷哪份是準的）。單一事實來源原則自己先破功 |
| B7 | `engine/utils.py:332-354` `sync_framework_docs` | 每輪把 rules/generators 複製進 `.loop/` 並**自動 commit**，發生在 review gate 之前 | 框架文件更新會混進「上一輪未審 diff」被 review gate 一起審；且這個 commit 不是 agent 產的，污染「一輪一 commit」的還原點語意。建議只在 run 啟動時同步一次 |
| B8 | `engine/plan_loop.py:132-133, 206-207`、`run.py` | `cfg["run_id"] = run_id`、`git_head_before = git_head()` 重複行 | 無害但顯示缺 lint；建議加 ruff/pyflakes 進 CI |
| B9 | `engine/loop.py:243-246` | `run_git_review_gate` 在 verdict 有效但 decision 非三值時已擋，但函式尾端沒有顯式 return（decision==PASS 分支外）——防禦性缺口 | 加 fallthrough return 或 assert |
| B10 | `generators/2-plan-review-gate.md:20` | 引用 `config.min_unit.max_files`，但 `min_unit` config 已移除（`config.py:55` 註記 removed） | 審查 agent 會去找不存在的設定；tree 殘留清理不完整 |

> 另外建議：`engine/test_engine_features.py` 已有 652 行測試，但顯然沒有涵蓋 preflight（B1 能存活就是證據）。**把「跑一次 `run.py --preflight` 的煙霧測試」加進 CI** 是零成本高回報。

---

## 4. Overnight 工作流：讓「下班放下去跑、隔天驗收」成立

這一節是為同事設計的端到端流程，按時間軸列需求與提案。

### 4.1 下班前：啟動要一條命令、五分鐘內完成

**現況痛點**：init-project.py → 貼 bootstrap.md 給 agent → 手填 config → run.py，四段式、跨兩個工具（shell + agent CLI），且 `REQUIREMENTS CONFIRMED` 只是 warning、同事一定會漏。

**提案**：
1. **統一入口 `loop`**（單一 console script，取代 init-project.py / run.py / parallel.py 三個入口）：
   ```
   loop init [--profile claude-code|codex|opencode|gemini]   # 建 workspace + 互動選 CLI/模型 profile
   loop plan / loop run / loop status / loop report / loop resume / loop reset
   loop doctor                                               # 健檢（見下）
   ```
2. **CLI/模型 profile 預設組**：框架內建各家 CLI 的 `build_cmd` + 建議三層模型組合，同事選 profile 而不是手寫 `build_cmd`（這是目前最容易填錯、又要到 preflight 才發現的欄位）。
3. **`loop doctor`**：除了現有 preflight 靜態檢查，再做**一次真實的 1-token smoke 呼叫**（用 fast 模型跑「回覆 OK」）驗證：CLI 裝了、登入了、模型名合法、額度沒爆。**overnight 最常見的死法是 token 過期與模型名打錯，靜態檢查抓不到。**
4. **`loop run --smoke`**：正式放置前先跑 3 輪封頂的試跑，確認 agent 真的會動、會 commit、state 有推進，再放心下班。
5. **需求確認升級為硬檔**：`stage=plan` 時 `REQUIREMENTS CONFIRMED` 從 warning 改 error（可用 `loop confirm-requirements` 蓋章，記錄人與時間）。

### 4.2 夜間：跑在隔離分支、失敗要快、停止要通知

1. **預設 branch 模式**（不需相容舊版，直接改預設）：`loop run` 啟動時自動 `git switch -c loop/<workspace>/<date>`，整晚的幾百個 commit 全部落在 loop 分支。人的分支永遠乾淨，早上驗收 = 看一個 branch diff / PR。這一項對「同事敢不敢用」的影響超過任何引擎功能。
2. **快速失敗偵測（fail-fast breaker）**：現有 watchdog 抓「跑太久/沒輸出」，但抓不到「**秒退**」——CLI 未登入、token 半夜過期、模型名錯，agent process 幾秒內 rc≠0 退出，現行機制要靠 idle 簽章累積 `stall_threshold=10` 輪才升級，而升級模型對 auth 錯誤毫無幫助，會空燒到 max_rounds。**引擎加一條：process 存活 < 30s 且 rc≠0，連續 3 次 → 立即 `human_required=cli_failing` 停機 + 通知**。
3. **牆鐘預算 `max_wall_seconds`**：max_rounds 是輪數不是時間。加「跑到 07:00 / 最多 10 小時就收工」的時間上限，收工時一樣產報告，讓「隔天驗收」的時間點可預期。
4. **終止通知 `notify_cmd`**：config 加一個 hook（shell 指令樣板，帶入 status/workspace/report 路徑），在 `complete / human_required / max_rounds / cli_failing` 時執行——同事自己接 Slack webhook、Telegram、email 都行。半夜卡死至少早上第一眼就知道，而不是打開電腦才發現 0:12 就停了。

### 4.3 隔天早上：一頁報告 + 明確的下一步

**提案：終止時自動產出 `RUN_REPORT.md`**（資料源全部已存在於 rounds.jsonl + state.json，純消費端工作）：

```
# Run Report — <workspace> <date>
結果：🏁 COMPLETE / 🧑 HUMAN_REQUIRED(<code>) / ⛔ MAX_ROUNDS / ⏰ WALL_CLOCK
時間：22:31 → 06:12（7h41m）；輪數：execute 214 輪（fast 183 / normal 26 / thinking 5）
進度：phase 2/2；任務 37/41 CONVERGED、2 FROZEN、2 TODO
需求驗收：R001 ✅ R002 ✅ R003 ⚠️(ISSUE-04) …（逐條，來自 requirements_map）
本次 diff：loop/featureA/0701 分支，+4,213 / −1,882，121 commits → [查看 diff]
夜間事件：R087 Review Gate REVERT ×1（原因…）；R130 升級 normal（震盪指紋…）
待你裁決：ISSUE-04（BLOCKING，規格矛盾：…）；FROZEN：TASK-21, TASK-22
建議下一步：處理 ISSUE-04 後 `loop resume --note "..."`
```

配套：
1. **`loop resume --note "..."`（人類回饋通道）**：目前人解掉 human_required 之後，沒有正式管道「留話」給下一輪 agent（例如「兩條需求衝突，以 R003 為準，R007 改成…」）。提案：note 寫進 `.loop/<ws>/HUMAN_NOTES.md`，引擎在接下來 N 輪的 prompt 前綴注入（類似現有 `_pending_revert_notice` 的機制，已有先例，做法便宜）。需求本身有變更則走 reset-plan 的 diff 模式。
2. **最終驗收 gate 補上**（BLUEPRINT §9 缺口 B）：`LOOP COMPLETE` 不再是終點，而是產出報告 + 標記 `awaiting_human_acceptance`；人看完報告執行 `loop accept`（合 PR）或 `loop reject --note ...`（回流）。這正好把「隔天驗收」變成流程的一等公民而非框架外動作。
3. **Plan review（gate#2）也給人話版**：目前要人直接 review `state.json` + `phases/*.md`，負擔大。plan 收斂時順手產 `PLAN_SUMMARY.md`（階段/任務表、依賴圖、輪數與成本估算、風險點），`loop approve-plan` 蓋章放行。

---

## 5. 大翻新藍圖（v3）：引擎主導的編排

> 前提已確認：**不需向後相容**，可以動資料結構。以下是建議的目標架構，以及為什麼。

### 5.1 把「挑任務」從 agent 收回引擎

**現況**：boot-sequence STEP 0–4 要 agent 自己讀 state.json、判停止、判 phase gate、按表序+依賴挑「唯一一個可做任務」。為了防它挑錯/挑軟柿子/一輪多做，配了三大段嚴禁條款 + review gate 第 3 項 + state.py 配額，三層執法。

**但這個決策是純機械的**：「第一個非 CONVERGED、非 FROZEN、依賴全 CONVERGED 的任務」——引擎用 20 行 Python 就能算，而且**不可能算錯、不可能被說服**。

**提案**：每輪引擎先算好，然後發給 agent 一張**任務卡（task card）**，prompt 直接長成：

```
本輪任務：TASK-17「移植 GET /api/orders/:id」（phase 2，第 3 次獨立重驗）
規格（引擎已擷取 PHASE2.md 對應小節，貼在下方）：…
依賴讀取：src/legacy/orders.js:120-210、.loop/…/docs/orders-api.md
本輪動作類型：RE-VERIFY —— 依下列重驗程序執行（convergence.md 對應段落內嵌）…
完成後：跑 `<state_cli> report ...` 回報，git commit，立即結束 process。
```

**收益**：
- boot-sequence 從 142 行縮到 ~30 行（只剩寫檔守則、留證、停機紀律）；每輪 context 省下大量 token——**這對弱模型既是省錢也是提升正確率**（指令越短越專一，弱模型表現越好）。
- 「挑軟柿子／一輪多任務／跳過依賴／提前過 gate」整類漏洞**物理上消失**，review gate 對應紅線可以刪掉。
- phase gate、停止判定本來就已經在引擎裡有（`is_done`），agent 側的 STEP 2/3 是重複實作，收回後單一事實來源。
- 引擎知道本輪是「初稿/重驗/修正/驗證」哪種動作，可以**按動作類型注入對應 rules 小節**（而不是叫 agent 自己去讀對的檔），rules 的「按需讀」從自律變成機制。

### 5.2 客觀驗證引擎化：任務契約（task contract）

**提案**：翻新任務資料結構（見 5.3），每個任務宣告驗證方式：

```yaml
verify:
  kind: command | reverify | enumerate | none   # 客觀指令 / LLM 獨立重驗 / 集合列舉 / init 免驗
  check: "cd src && npm test -- orders.spec.ts" # kind=command 時必填
  threshold: 2                                   # kind=reverify/enumerate 的收斂門檻
```

執行時序改為：**agent 停機後，引擎親自跑 `check`**，exit code 直接寫入 `last_round_result` 與任務狀態。agent 從此**沒有能力**謊報 PASS——不是被規則禁止，是根本沒有這個寫入路徑。

**連鎖收益**：
- `convergence.md` 的「有客觀把關的任務不需多次主觀重推」正式落地：有 `check` 的任務收斂 = 指令綠，一輪定稿，**省掉大量重驗輪**（這是目前最大的輪數開銷之一）。
- review gate 紅線 11（驗收證據缺失）對 command 型任務直接作廢——證據就是引擎自己的執行記錄，寫進 rounds.jsonl。
- phase 收尾的「全量驗證 ×10 輪」對有測試套件的專案可以改成「引擎跑全套 test ×N 次穩定」，從 10 輪 LLM 呼叫變成 10 次免費的 pytest。
- LLM 重驗（reverify/enumerate）只保留給真正主觀的分析/文件任務——這才是它的比較優勢所在。
- **對 plan 品質形成正向壓力**：plan gate 增加一條機械檢查「每個實作型任務都有可執行的 check」，逼規劃期就想清楚驗收方式（寫不出 check 的任務 = 切壞了，這與 BLUEPRINT「可獨立驗證是硬條件」完全一致，只是變成可機器強制）。

### 5.3 state.json 資料結構翻新

**現況問題**：
- 頂層扁平字串鍵（`p1_consecutive_pass`、`last_round_mode`…）+ `control` 物件混用，`get_val/set_val` 全走字串鍵路由（`state.py` 用 60,867 bytes 中相當比例在處理鍵名解析與白名單）。
- 「哪些欄位歸 agent 寫、哪些歸引擎寫」只靠白名單約定，語意上不可見。
- phases/tasks 內嵌大量執行期欄位，設定與狀態仍有殘餘混雜。

**提案（既然不用相容，直接重切）**：

```jsonc
{
  "schema_version": 3,
  "run": {            // 只有引擎可寫：run_id、current_phase、stuck、model_tier、human_required…
    "current_phase": "2", "stuck_level": 0, "human_required": null, "wall_deadline": "…"
  },
  "phases": [{
    "id": "2",
    "gate": { "consecutive_pass": 3, "required": 10 },
    "tasks": [{
      "id": "TASK-17", "title": "…", "depends_on": ["TASK-05"],
      "spec_ref": "phases/PHASE2.md#task-17",     // 引擎據此擷取小節注入任務卡
      "verify": { "kind": "command", "check": "npm test -- orders" },
      "status": "DRAFTED", "conv": 1,
      "evidence": ["rounds/R087-check.log"]        // 引擎寫入，不是 agent 自稱
    }]
  }],
  "issues": [ { "id": "ISSUE-04", "level": "BLOCKING", "status": "OPEN", "file": "issues/issue-04.md" } ],
  "requirements_map": { "R001": ["TASK-03","TASK-17"], … },
  "agent_report": {   // agent 唯一可寫的區域，且只透過 CLI 的 `report` 子命令整包提交
    "round": 87, "summary": "…", "wrote_files": […], "opened_issues": […]
  }
}
```

重點：
1. **寫入權限用結構表達**：`run.*` 引擎專屬、`agent_report` agent 專屬、任務狀態推進由**引擎根據 verify 結果與 agent_report 推導**，agent 不再直接 `task-status --to CONVERGED`。state.py 的守衛從「防 agent 寫壞」簡化成「解析 agent_report + 執行狀態機」，程式量預估砍半。
2. **`schema_version` 進檔**，之後翻新用 migration，不再靠 `migrate_to_json` 這種一次性函式。
3. `spec_ref` 用「檔案#錨點」讓引擎機械擷取任務卡內容——phase 檔的格式也要跟著模板化（PHASE.template.md 每個任務一個標準錨點小節）。
4. `state-cli-guide.md`（167 行、agent 每輪要讀）可以整份刪除——agent 只剩一個 `report` 動作，說明放進任務卡三行講完。

### 5.4 Review Gate 分層瘦身

**現況**：每輪一定燒一次 review agent，13 項清單其中多數可機械判定；且 REVERT 後只帶一行 notice 重試，同一問題可能反覆 REVERT 直到指紋機制介入。

**提案三層**：
1. **第 0 層（Python，免費）**：JSON/YAML 可解析、衝突標記、佔位符 pattern（`// ... existing code`）、檔案截斷/空白、`<think>` 殘留、計數器單輪增量、狀態跳級（state.py 已擋大半）、產出異動未歸零（diff 掃 output 範圍 + conv 欄位比對）。**這些全部規則化，不用 LLM。**
2. **第 1 層（LLM，條件觸發）**：只剩真正需要語意判斷的 3~4 項（語意一致性、思考外洩的變體、假證據抽查）。觸發條件：第 0 層全過 **且**（diff 超過門檻行數 或 本輪宣稱了收斂推進 或 隨機抽樣 20%）。小 diff 的純推進輪直接放行。
3. **REVERT 回饋強化**：REVERT 時把 verdict 的 evidence 寫進該任務的 `revert_history`，下一輪任務卡帶上「上次被退的具體原因與位置」，而不是一行通用警告——弱模型需要具體到檔:行的指示才改得對。

**預估效益**：review 呼叫次數 −50%~70%，且機械項的判定從「LLM 可能漏」變成「必然抓到」。

### 5.5 模型調度細部優化

1. **plan 期宣告任務難度**：`tier_hint: fast|normal`。明知很難的任務（跨檔重構、複雜演算法）直接從 normal 起跳，省掉「fast 撞 10 輪才升級」的空轉。這與「順風用角色預設」不衝突——hint 就是該任務的角色預設。
2. **升級門檻分訊號調參**：`stall_threshold=10` 對「連續相同指紋」太鈍。相同指紋重複 3 次（明確在原地繞）就該升級；10 輪門檻留給「有變化但沒進展」的情況。
3. **plan 迴圈的 Round B 快取**：規劃書無實質變更（changed=False）且上一 cycle Gate 已 PASS 時，可跳過重跑 Gate（或降到 fast 模型只做 diff 確認），plan 收斂尾段的 cycle 成本近乎減半。
4. **成本記帳**：rounds.jsonl 已記 model_tier，補記每輪 duration 與（CLI 有輸出時）token 用量；RUN_REPORT 匯總「本次 run 各層模型輪數×時長」，讓「便宜」可以被量化驗證，也讓 plan gate 的輪數估算有真實數據校準（餵回 maintenance/trace 分析）。

---

## 6. 規則面（rules/）翻新原則

配合 §5 的引擎翻新，rules 目錄的重整原則：

1. **每條規則標記執法者**：翻新後每份 rule 開頭聲明 `enforced-by: engine | state-cli | review-gate-L0 | review-gate-L1 | prompt`。凡是 `enforced-by: prompt`（只靠 agent 自律）的條款，就是下一個要被機制化的目標——這讓 maintenance loop 的爬坡有明確方向。
2. **agent 每輪必讀的內容 ≤ 50 行**：boot-sequence 瘦身後，加上任務卡內嵌的動作指引，agent 的固定閱讀負擔要有硬上限（context-budget.md 精神用在框架自己身上）。
3. **刪除三處門檻數字漂移**（B6）：門檻只活在 config/DEFAULTS 一處，rules 引用時一律寫「見 config」不寫數字。
4. **tree 殘留清理**：BLUEPRINT §3.10 整節、plan-review-gate 的葉子條款、preflight/roles 的 decompose 引用——要嘛砍掉（目前 engine 已不支援），要嘛移進「未來功能」附錄，別讓規劃 agent 讀到不存在的機制。
5. **BLUEPRINT 定位調整**：421 行的 BLUEPRINT 目前身兼「設計哲學」+「操作規範」+「現況盤點」。翻新後拆成：`PHILOSOPHY.md`（人讀，講為什麼）與機器實際引用的精簡規格；§9 的人類介入點盤點併入本報告 §4 的 gate 設計後刪除。

---

## 7. 團隊導入配套（非程式碼）

1. **「下班前 checklist」一頁文件**：git 乾淨？在正確 repo？`loop doctor` 綠？`--smoke` 過？通知 webhook 設了？tmux/nohup or dashboard 掛著？——五分鐘儀式，寫進 README 頂部。
2. **任務型 preset**：常見任務型（legacy 遷移、補測試覆蓋、批量文件生成、資料清洗）各附一份範例 REQUIREMENTS + 已調好門檻的 config。同事從 preset 改，而不是從空白模板開始——這同時能讓 plan 迴圈收斂更快（規劃 agent 有好範本可抄）。
3. **試點策略建議**：先讓 2~3 位同事用「補測試覆蓋」這類**客觀驗證天然強**（check=coverage 門檻）、**失敗代價低**（在 loop 分支上）的任務型試跑一兩週，用 RUN_REPORT 的數據說話，再推廣到遷移/重構型任務。
4. **安全提醒文件**：overnight agent 是拿著使用者憑證在跑的——明文列出：只在隔離分支、絕不 push（引擎本來就不 push，寫明）、目標 repo 不含生產憑證、CLI 的 auto-approve 範圍設到 repo 目錄內。

---

## 8. 建議施工順序

**第一批（本週可完，全部小工作量）**
- 修 B1（preflight tree prompts）——不修框架跑不起來
- 修 B3/B5/B7 + 清 B2/B8 死碼；CI 加 `run.py --preflight` 煙霧測試
- `notify_cmd` 終止通知；快速失敗偵測（cli_failing breaker）；`max_wall_seconds`
- RUN_REPORT.md 產生器（純消費 rounds.jsonl/state.json）

**第二批（1~2 週）**
- 預設 branch 模式 + `loop accept/reject` 驗收流；PLAN_SUMMARY.md
- 統一 `loop` CLI + profiles + doctor + --smoke
- HUMAN_NOTES 回饋通道；REQUIREMENTS CONFIRMED 升級為 error
- Review Gate 第 0 層機械化（先不動 LLM 層，直接省呼叫）

**第三批（大翻新，2~4 週，一次到位不留相容層）**
- state.json schema v3 + 引擎挑任務/任務卡 + verify 契約引擎執行
- rules 全面瘦身重整（每條標 enforced-by）
- review gate 語意層縮到 3~4 項條件觸發
- 模型調度優化（tier_hint、指紋快升、plan gate 快取、成本記帳）

**衡量翻新是否成功的指標**（用 maintenance 的 trace 機制驗證）：
- 每輪平均 prompt token（應 −40% 以上）
- 每個 CONVERGED 任務的平均輪數（command 型任務應 → ~1.5 輪）
- review REVERT 率與 review 呼叫次數（呼叫 −50%，REVERT 中機械類 → 0，因為第 0 層先擋）
- 「跑一整晚無人值守，早上拿到可讀報告」的成功率——這是同事採用率的先行指標

---

## 附錄：本次審查中確認「不建議做」的方向

- **同 repo 同時多 loop**：現行「一次一個 + worktree 並行」的立場正確，不要為了吞吐犧牲 git 安全網語意。
- **讓引擎自動放寬 breaker / 自動解凍 FROZEN**：授權紅線是本框架最寶貴的設計之一，任何「智慧化」都不該越過它。
- **把 dashboard 做成主要操作面**：dashboard 適合觀測與少量操作（start/resume），但流程真相應該留在 CLI + 檔案（可 script、可 CI、可 remote），同事的肌肉記憶才可遷移。
- **綁定單一 agent CLI**：CLI 中立是能讓全組不同工具偏好的人共用的前提，`build_cmd` 抽象保留；只用 profile 降低填寫成本即可。
