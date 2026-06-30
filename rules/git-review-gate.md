# 🛡️ RULE — Git Review Gate (獨立審查輪)

> **唯讀框架規則**。這是引擎在正式執行下一輪任務前，自動開啟的「獨立審查輪」。
> 你的唯一工作是審查從上次安全基準點到目前的 `git diff last_safe_sha HEAD`，抓出中斷殘留、破壞排版或格式錯亂等問題。
> **這是一個全新的 context，你不需要、也不能修改檔案，只要給出判決。**

## 1. 審查目標
確保上一輪的改動合理且沒有破壞現有結構。若發現任何以下「判死刑」的狀況，必須毫不留情地輸出 JSON verdict `"REVERT"`。

## 2. 審查紅線（中一條即 REVERT）

1. **中斷與殘留防護**
   - 檔案結尾是否有被異常截斷？
   - Markdown 區塊 (```` ``` ````) 或 HTML 標籤是否未閉合？
   - 是否有寫到一半的殘留程式碼或未完成的句子？

2. **排版與狀態檔結構破壞 (嚴格審查)**
   - ⚠️ 你現在不只會看到 Diff，還會看到最新的 `state.json` 狀態檔完整內容。
   - 狀態檔 `state.json` 是否保持合法的 JSON 結構與格式？是否被扭曲、欄位被無故刪除或格式寫壞？
   - 改動後的上下文語意是否矛盾？（例如 `current_phase` 寫已抵達 3，但任務卻都還在 Phase 1）。
   - 若狀態控制的核心骨架遺失或受到毀滅性破壞，請直接輸出 JSON verdict `"FATAL_STATE"`。


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
    - 本輪是否在 `state.json` 把 `last_round_result` 標 `PASS`、或讓 `p{i}_consecutive_pass` 往上 +1（宣稱推進/收斂）？
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
    - ⚠️ 排除:scratch 證據檔(`.reverify/` `.enum/` `.validate/`)、Issue 檔、`state.json` 狀態欄位本身不算
      「產出異動」;重驗一致那輪本來就會新增這些 scratch 檔,不因此要求歸零。只看**正式產出檔**有沒有被改。

## 3. 輸出格式

🚨 強制約束(你是最後一道安全網,你的判決本身不准被橡皮圖章)：
你必須將單一 JSON 物件覆寫到 Prompt 指定的 `{result_file}`。檔案前後不得有任何散文或 HTML 標籤（包括 ```json ``` 標籤也請不要輸出，僅輸出純 JSON）。

```json
{
  "verdict": "PASS",
  "checklist": [
    { "id": 1,  "name": "中斷與殘留防護",        "result": "PASS" },
    { "id": 2,  "name": "排版與狀態檔結構破壞",   "result": "PASS" },
    { "id": 3,  "name": "不合理狀態進展",         "result": "PASS" },
    { "id": 4,  "name": "中間區段被挖空",         "result": "PASS" },
    { "id": 5,  "name": "思考過程外洩",           "result": "PASS" },
    { "id": 6,  "name": "語意一致性",             "result": "PASS" },
    { "id": 7,  "name": "AI偷懶佔位符",           "result": "PASS" },
    { "id": 8,  "name": "無故刪檔與路徑幻覺",      "result": "PASS" },
    { "id": 9,  "name": "衝突標記與取代錯位",      "result": "PASS" },
    { "id": 10, "name": "基礎語法與格式全毀",      "result": "PASS" },
    { "id": 11, "name": "驗收證據缺失",           "result": "PASS" },
    { "id": 12, "name": "收斂計數防偽",           "result": "PASS" },
    { "id": 13, "name": "產出異動卻沒歸零收斂",    "result": "PASS" }
  ],
  "reason": ""
}
```

🚨 限制與規則：
1. `verdict`：只能是 `"PASS"`、`"REVERT"`、`"FATAL_STATE"` 之一。
2. `checklist`：必須精確包含上面 13 項紅線檢查（如實標明各 id 與 name）。`result` 僅能為 `"PASS"` 或 `"FLAG"`。當 `result` 是 `"FLAG"` 時，該項物件內**必須包含 `"evidence"` 欄位**以說明具體證據（檔:行 或程式段落）；若為 `"PASS"` 時，則不得包含 `"evidence"` 或是 `"evidence"` 留空。
3. `reason`：當 `verdict` 為 `"REVERT"` 或 `"FATAL_STATE"` 時**必填**（人類可讀原因）；`PASS` 時必須為空字串。
4. ⚠️ 引擎 fail-closed：檔案若非合法 JSON、欄位缺失、`checklist` 項目數不等於 13、`FLAG` 缺乏證據、或 `REVERT/FATAL_STATE` 缺乏 reason，該判決一律被視為無效判決（不放行且累計 streak，滿 8 次會停機交給人類）。

⚠️ **注意**：
1. 必須是覆寫 (Overwrite) 該檔案，不要用附加 (Append)。
2. 寫檔完成後即可結束，**不要**執行 `git commit`。
3. 🚨 寫完判決檔即【立即停止輸出、結束本 process】，控制權交還引擎；❌ 嚴禁額外修改任何檔案、自行重審、或續跑下一輪。

