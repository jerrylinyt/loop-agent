# 🧨 RULE — Context 防爆（橫切硬約束）

> **唯讀框架規則,且優先級最高。** agent 的 context 是稀缺且會爆的資源。
> **任何檔案、設定、規則的設計,都要先問:「它會不會無限長大?會不會被一輪一輪讀進 context?」**——會的就必須上限、滾動、或不准讀。這是設計約束,不是事後優化。
> 生成器(產規劃書時)與每輪 boot(執行時)都要遵循本檔。

## A. 每輪讀取預算（硬上限，寫進 boot）
- **每輪固定只讀**:`CONTROL.md`(全文)+ `當輪那一節 phase 規格` + `當輪用到的那一份 rules 協定` + `任務宣告的少數依賴檔(且只讀宣告的行範圍)`。
- **rules 也按需讀**:`boot-sequence.md` 每輪必讀(故要短);其餘協定(convergence/completeness/oscillation…)**只在當輪用到時才讀那一份**,不是全部載入。→ rules 必須**分檔且每份精簡**。
- **嚴禁「保險式全掃」**:不准「為了確認沒漏,把整個 outputs/docs/src 讀一遍」。完整性 → 走**列舉清單(分母)+ 分段讀 + 行覆蓋記錄**(completeness.md),用清單代替全讀。

## B. Log 永不進 context（append-only，只給人看）
- `loop.log` 是**寫給人 `tail -f` 的**,**agent 一律禁止讀取**;引擎也**不 parse log**,只 grep CONTROL 的單行計數器(不載入 LLM context)。
- **log 自身要防爆(防硬碟)**:config 設 log rotation(`log_rotate_max_mb` + `log_rotate_keep`),超過就切檔。
- 失敗指紋歷史存 `.loop_state/`(引擎用,**不進 context**),環狀固定長度(maxlen=osc_window)。

## C. 無限增長源 → 強制滾動/上限（逐一點名）
| 增長源 | 問題 | 對策 |
|--------|------|------|
| **CONTROL 執行日誌** | 每輪 append → CONTROL 每輪變大 → STEP 0 全讀會越讀越爆 | **移出 CONTROL**:日誌 append 到 `loop.log`(agent 不回讀);CONTROL 內**最多留最近 `journal_in_control_keep` 筆**摘要 |
| **狀態表 / coverage 表** | 任務多時 CONTROL 變大 | 大專案**每階段一張狀態表,放各自 phase 檔的頭**;CONTROL 只留「當前階段那張 + 跨階段彙總計數」 |
| **Issue / 修正記錄** | 累積無上限 | **一 Issue 一檔**(issues/issue-*.md);CONTROL 只留「未關閉 Issue 的一行索引 + blocking 數」,不貼內文 |
| **inventory / 產出檔** | 單檔塞所有內容 → 一讀就爆 | **一檔一主題、分散**;inventory 只放「清單(分母)+ 狀態欄 + 行覆蓋」,不放分析內文 |

## D. 檔案 / 設定 / 規則的精簡與分散準則
- **一檔一主題**:任何檔長大到「一次讀進來就佔掉可觀 context」就拆分(rules、phases、docs/src 皆然)。
- **CONTROL 保持「決策最小集」**:只放「決定本輪做什麼 + 活計數器 + 索引」;規格放 phases、方法論放 rules、明細放產出檔、歷史放 log。CONTROL 軟上限 `control_max_bytes`;超過代表有東西該移出。
- **設定不重複**:同一門檻只在 config 出現一次,避免兩處 drift 也避免 CONTROL 變胖。
- **依賴最小宣告**:每個任務在 phase 檔明確宣告「只讀哪幾個檔、哪幾行」,讓 agent 能精準小讀,而非開整檔。

## E.「不允許任務查看資料」的落地含義
> = **不准用「把資料整批讀進 context 來檢視」當作工作方式**。
- 完整性靠**機械式列舉 + 行覆蓋追蹤**(在清單上記「這段讀過了」),不靠「把檔案再讀一遍確認」。
- 收斂重驗靠**獨立重推 + 集合比對**(比對「項目身分清單」,不是把兩份全文塞進 context)。
- 跨檔一致性靠**索引/指紋/計數器**(可 grep 的小資訊),不靠「把相關檔全開來人工比對」。

## F. 生成器(階段②)必須落實的防爆
產規劃書時就要把關(對映 Plan Review Gate):無任何「會無限長大且會被每輪讀進 context」的設計——
日誌移出 CONTROL、Issue/產出分散成檔、log rotation 已設、每輪讀取預算明確、沒有「整批讀資料來檢視」的任務。
