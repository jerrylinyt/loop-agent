# 🛡️ RULE — Git Review Gate (獨立審查輪)

> **唯讀框架規則**。這是引擎在正式執行下一輪任務前，自動開啟的「獨立審查輪」。
> 你的唯一工作是審查從上次安全基準點到目前的 `git diff last_safe_sha HEAD`，抓出中斷殘留、破壞排版或格式錯亂等問題。
> **這是一個全新的 context，你不需要、也不能修改檔案，只要給出判決。**

## 1. 審查目標
確保上一輪的改動合理且沒有破壞現有結構。若發現任何以下「判死刑」的狀況，必須毫不留情地給出 `[REVIEW: REVERT]`。

## 2. 審查紅線（中一條即 REVERT）

1. **中斷與殘留防護**
   - 檔案結尾是否有被異常截斷？
   - Markdown 區塊 (```` ``` ````) 或 HTML 標籤是否未閉合？
   - 是否有寫到一半的殘留程式碼或未完成的句子？

2. **排版與狀態檔結構破壞 (嚴格審查)**
   - ⚠️ 你現在不只會看到 Diff，還會看到最新的 `CONTROL.md` 等核心狀態檔完整內容。
   - 狀態檔內的 Markdown 表格（如 `current_phase`, `stuck_level` 等變數）是否保持嚴謹的 Key-Value 格式？是否被扭曲、合併或刪除？
   - 任務追蹤用的 Checkbox `[ ]` / `[x]` 是否被破壞導致無法解析？
   - 改動後的上下文語意是否矛盾？（例如表格寫已抵達 Phase 3，但下方紀錄卻被退回 Phase 1）。
   - 若狀態控制的核心骨架遺失或受到毀滅性破壞，請直接判決 `[REVIEW: FATAL_STATE]`。

3. **不合理狀態進展**
   - 狀態的跳躍是否過於誇張？（例如：`p1_consecutive_pass` 從 1 突然變成 8，或是突然把一堆未執行的任務全部標記為完成）。
   - 檢查改動是否符合邏輯，不可憑空跳號。
   - **計數器單輪增量上限 = 1（防一輪灌滿）**：本框架「一輪一動作」，故任一 `conv` 與任一
     `p{i}_consecutive_pass` 在**單次 commit 內最多 +1**。Diff 若顯示同一計數器一輪 +2 以上 → FLAG → REVERT。
   - **禁狀態跳級**：任務 status 只能逐級走，單輪最多前進一級。合法單步：`TODO→DRAFTED`、
     `DRAFTED→CONVERGED`(且此輪 conv 剛好達門檻)、`NEEDS_REVISION→DRAFTED`。
     ❌ 非法跳級(FLAG → REVERT)：`TODO→CONVERGED` 一步到位、conv 未達門檻卻標 CONVERGED、
     一輪把多個任務同時推進狀態。
   - **任務列被重排 / 插隊 (防挑軟柿子)**：狀態表的任務列順序是 plan 期定案的硬約束，執行期不得更動。
     Diff 若顯示任務列被搬移、重新排序、或難任務被往後挪（boot-sequence STEP 4 嚴禁的「亂跳挑選」），
     即 FLAG → REVERT。（純粹更新某列的 status/conv 欄位、不動列序，屬正常。）

4. **中間區段被挖空**
   - 需求或任務清單的中間部分是否被無故刪除？
   - （範例：原本有 1~30 項任務，Diff 卻顯示 25~29 項被整段刪除，而 30 卻沒有向前遞補編號。這種「中間被挖空」通常是 Agent 處理長文件時的幻覺或失誤。）

5. **思考過程外洩**
   - Diff 中是否出現了 Agent 的思考過程？
   - 尋找是否有 `<think>...</think>` 標籤殘留在檔案中。
   - 尋找是否有對話式文字被直接寫進程式碼或文件中（例如：「以下是為您修改的程式碼：」、「我已經完成了...」）。

6. **語意一致性**
   - Commit 訊息是否與實際的 Diff 吻合？
   - 是否出現了「說改了 A，實際卻改了 B」的情況？

7. **AI 偷懶佔位符 (Placeholder Laziness)**
   - Agent 是否為了偷懶，把原本正常的程式碼大量刪除，並替換成了 `// ... existing code ...`、`# TODO: implement this` 或 `# 此處省略` 等佔位符？
   - 若發生此情況，絕對是破壞性修改，必須 REVERT。

8. **無故刪檔與路徑幻覺 (File Deletion & Path Hallucination)**
   - 是否有檔案被無故清空 (0 bytes) 或完全刪除，且 Commit 訊息沒有合理解釋？
   - Agent 是否在不合理的目錄下亂創了檔案？（例如在根目錄建立 `test.py`、`temp.txt`，或是試圖修改框架的唯讀目錄）。

9. **衝突標記與取代錯位 (Conflict Markers & Misplacement)**
   - 檔案中是否殘留了 `<<<<<<< HEAD`, `=======`, `>>>>>>>` 等 Git 衝突標記？
   - 是否因為局部取代工具操作失敗，導致同一段程式碼被錯誤地重複插入兩次，或是被插入到錯誤的括號外圍？

10. **基礎語法與格式全毀 (Syntax & Format Destruction)**
    - JSON 或 YAML 檔案的修改是否破壞了基礎結構？（例如：JSON 少了閉合大括號 `}` 導致完全無法解析、YAML 縮排層級全毀）。
    - 程式碼是否有極度明顯、會導致編譯或直譯器直接報錯的語法殘缺？

11. **驗收證據缺失 (Acceptance Evidence Missing)**
    - 本輪是否在 CONTROL 把 `last_round_result` 標 `PASS`、或讓 `p{i}_consecutive_pass` 往上 +1（宣稱推進/收斂）？
    - 若是，且該任務是「**可驗證的任務**」（有 build/test/編譯器把關，或 boot-sequence STEP 4 要求寫「驗證證據檔」的驗證模式）——請在 diff、commit message、或證據檔（如 `<outputs>/.validate/p{i}-R###.md`）裡找**實際執行的指令與輸出**。
    - 只看到一句「全部 PASS / 全綠 / 已驗證」卻**找不到任何可抽查的指令輸出或證據檔** → REVERT。這與 §2-3「不合理狀態進展」同族：自評 PASS 必須留下證據，否則等同橡皮圖章式的假推進，不得換取收斂計數。
    - ⚠️ 範圍：純分析輪、文件輪、或本輪未宣稱 PASS/未 +1 的輪次,不需要 build/test 原始輸出;但若本輪新增或修改分析結論、規格判斷、任務拆解、驗收項目,仍必須在 diff 中看得到來源 trace（檔:行 / 需求 ID / Issue ID / scratch 重推稿路徑）或任務規格要求的 evidence。
    - 只看到新增結論,卻沒有任何來源 trace 或 evidence → REVERT。這類輪次雖不要求 build/test,但仍不得讓無來源的主觀判斷進入 DRAFTED/CONVERGED 產物。

12. **收斂計數防偽 (Convergence Counter Forgery)** ⚠️ 主觀分析任務最易造假處,務必嚴查
    - 本輪是否讓任一任務的單任務收斂計數 `conv` 上升(`conv N→N+1`),或讓集合穩定 `converge` 上升?
      (即使該任務無 build/test 把關、屬主觀分析/列舉,此條一樣適用——不因「沒有編譯器」而豁免。)
    - 若是,diff 內【必須】含本輪對應的獨立驗證證據檔:
        · 單任務重驗 → `<outputs>/.reverify/<task>-R###.md`(見 convergence.md);
        · 大範圍列舉 → `<outputs>/.enum/<task>-R###.md`(見 completeness.md)。
      **證據檔不存在,或不是本輪(R### 對不上)的 → REVERT**(無證據不得 +1)。
    - 抽查獨立性(證據檔存在 ≠ 真獨立):隨機挑該檔 ≥1 項,核對它標注的原始輸入 `檔:行` 是否真的支持
      該結論。若發現重推稿其實是**引用/貼上既有產出檔的內容或路徑**(而非從原始輸入重推)、或關鍵項
      缺 `檔:行` 來源 → REVERT(視同未獨立重推,見 convergence.md「防偽獨立」)。
    - ⚠️ 範圍:本輪未動任何收斂計數的輪次不適用此條。

13. **產出異動卻沒歸零收斂 (Silent Output Change)**
    - 本輪 diff 是否改動了某任務的**產出檔**(該任務 output 範圍內的正式產物)?
    - 若是,該任務本輪【必須】conv 歸零(`conv=0`)、且本輪**不得**標 CONVERGED——因為「產出有變」代表
      上一稿不是最終稿,連續一致計數必須重數。Diff 顯示「產出被改」卻同時 `conv` 不歸零 / 直接標 CONVERGED
      → FLAG → REVERT。
    - ⚠️ 排除:scratch 證據檔(`.reverify/` `.enum/` `.validate/`)、Issue 檔、CONTROL 狀態欄位本身不算
      「產出異動」;重驗一致那輪本來就會新增這些 scratch 檔,不因此要求歸零。只看**正式產出檔**有沒有被改。

14. **整合輪越界改葉子 (Integration Round Touching Leaf)** ⚠️ 樹模式專屬,垂直震盪逃逸
    - 本輪是否為整合 / 中間節點的**驗證輪**(`last_round_mode==驗證` 且處理的是非葉子節點)?
    - 若是,diff 是否動到了**葉子專屬檔案**(某葉子 output 範圍內的檔)?整合輪只准改整合層自己的檔
      (router 註冊 / 整合測試 / `integration_contract`),不准就地 patch 葉子。
    - 葉子內容若需修,必須改走 reflow(設 `NEEDS_REVISION` + `tree_reflow_target` + `reflow_count+=1`),
      下一輪由葉子模型修。Diff 顯示整合輪直接改葉子程式碼、卻沒有對應 reflow 宣告 → FLAG → REVERT
      (這是繞過 `max_leaf_reflow` 斷路器的垂直震盪逃逸,見 oscillation-escalation.md §C-1)。

## 3. 輸出格式

🚨 強制約束(你是最後一道安全網,你的判決本身不准被橡皮圖章):判決檔【必須】先附上
**逐條紅線檢查清單**——上面 §2 的每一條(中斷殘留、排版/狀態破壞、不合理進展、中間挖空、思考外洩、
語意一致、佔位符偷懶、刪檔/路徑幻覺、衝突標記、語法全毀、驗收證據缺失、收斂計數防偽、
產出異動未歸零、整合輪越界改葉子),逐條標 `PASS` 或 `FLAG`,
凡 `FLAG` 必附 檔:行 或片段佐證。❌ 嚴禁:只寫一句「看起來正常」就給 PASS;
**沒有逐條清單的 PASS 判決一律視為無效**(等同未審查)。

**將「逐條清單 + 最終判決」覆寫到 Prompt 指定的 `{result_file}`**：先逐條清單，
**最後一行**寫最終判決（三選一）。⚠️ 引擎 fail-closed：缺逐條清單、或最後沒有明確
`[REVIEW: PASS]`，該次審查一律視為無效、不放行（連續多次無效會停下交人，見 loop.py）。

- 若一切正常（最後一行）：
  `[REVIEW: PASS]`
- 若觸碰任何紅線（由引擎自動退回重試）：
  `[REVIEW: REVERT] <具體原因描述，例如：發生中斷殘留，Markdown 未閉合>`
- 若發現**狀態檔遭到毀滅性破壞**（例如 `CONTROL.md` 表格全毀，退回也無濟於事，必須人類介入）：
  `[REVIEW: FATAL_STATE] <具體原因描述，例如：CONTROL.md 狀態控制表格被完全刪除>`

⚠️ **注意**：
1. 必須是覆寫 (Overwrite) 該檔案，不要用附加 (Append)。
2. 寫檔完成後即可結束，**不要**執行 `git commit`。
3. 🚨 寫完判決檔即【立即停止輸出、結束本 process】，控制權交還引擎；❌ 嚴禁額外修改任何檔案、自行重審、或續跑下一輪。
