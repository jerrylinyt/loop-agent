# 🚀 GENERATOR — Bootstrap（前期準備總入口：開 workspace → 訪談需求 → 停在你跑 python 之前）

> **怎麼用**:這是整個 Loop Engineering 流程的**唯一進入點**。把這份檔案交給任何一個 agent
> (Claude Code、codex、opencode……皆可,本檔不假設特定 CLI),它會依序帶你完成「前期準備」——
> **開 workspace + 需求訪談 + 人類確認**——做完就**停下來**,把下一步的 python 指令交給你自己執行。
>
> ❗**本檔管轄的工作邊界**:agent 在這個流程裡**只允許執行一次性、快速的腳手架指令**
> (`init-project.py`,秒級完成);**絕對不允許**自己呼叫 `plan_loop.py` / `run.py` / `loop.py`
> ——那些是**長時間跑、會消耗大量模型用量的收斂迴圈**,必須由人類自己決定何時啟動。
> agent 做完前期準備後,任務就是把「你要自己貼上去跑的那一行指令」清楚印出來,然後結束。

---

## STEP 0｜確認框架與目標

問清楚(不確定就問,不要腦補):
1. **框架在哪**:`framework_path`(這份 bootstrap.md 所在的 `loop-engineering/` 目錄,或使用者指定的共享 clone 路徑,如 `~/.loop/framework`)。
2. **目標 code repo 在哪**:要被 agent 操作、產出落地的那個既有專案路徑。
3. **這份需求的 workspace 名稱**:同一個 repo 可以開多份需求(`.loop/<name>/`),預設用 `default`;
   若使用者一開始就說了這是「第二份需求」之類,幫他取一個有意義的名字(如 `feature-x`)。

## STEP 1｜執行腳手架（唯一允許的 python，一次性、秒級）

用你的 shell 工具執行(把 `<framework_path>` / `<repo>` / `<name>` 換成 STEP 0 確認的值):
```bash
python3 <framework_path>/init-project.py <repo> --name <name>
```
這只會建立 `.loop/<name>/`(REQUIREMENTS/config 樣板 + `.gitignore`),**不會啟動任何收斂迴圈**,
跑完馬上結束、安全。若指令印出「= 已存在,略過」,代表這個 workspace 已經初始化過,跳過此步驟即可。

## STEP 2｜需求訪談

依 `0-requirements-interview.md` 的問題清單,**一組一組問清楚**(不要一次轟炸),把答案寫進
`.loop/<name>/REQUIREMENTS.md`(STEP 1 已建好樣板,照填即可;`templates/REQUIREMENTS.template.md` 是其來源)。
過程中注意:
- 若輸入資料很大(大檔/大量項目)→ 標記「需要大範圍防漏協定」,留給階段②的生成器處理。
- 提醒使用者:之後的執行階段**不會把資料整批讀進 context**;完整性靠列舉清單 + 行覆蓋。

## STEP 3｜人類確認需求（停止點之一）

把寫好的 `REQUIREMENTS.md` 完整內容(或摘要)念給使用者確認**逐條需求**是否正確、有無遺漏。
使用者確認後,在檔案標記 **REQUIREMENTS CONFIRMED(日期/確認人)**。
**未確認前不要往下走**——尤其不要自己接著去跑生成規劃書。

## STEP 4｜停下來，把下一步指令交給人類

需求確認後,**到此為止**。輸出大致像這樣的收尾訊息(依實際路徑/workspace 名稱替換):

```
✅ 前期準備完成：.loop/<name>/REQUIREMENTS.md 已確認。

接下來是「生成規劃書」與「執行」——這兩段都是會持續跑到收斂為止的 python 迴圈，
請你自己決定何時啟動：

  cd <repo>
  python3 <framework_path>/engine/run.py --workspace <name>

  · 預設 gated 模式：規劃書生成收斂後會停下來等你 review，你 review 完再跑：
      python3 <framework_path>/engine/run.py --workspace <name> --stage execute
  · 想全自動可加 --mode auto。

我不會自己執行這個指令。
```

❌ **不要**自己呼叫 `plan_loop.py`、`run.py`、`loop.py`，也不要建議用背景/nohup 方式偷跑——
這是刻意的人類決策點,不是技術限制。

---

## 給「人」的使用說明（非 agent 指令，供你自己參考）
1. 開一個全新 agent session(任何 CLI 都行),貼上這份 `bootstrap.md` 全文 + 你的初步想法(一兩句話也行)。
2. agent 會問你問題、帶你把 STEP 0~3 走完,最後印出指令給你。
3. 你看過指令、確認沒問題後,**自己貼上去跑**——之後就是 `run.py` 接手反覆觸發、直到收斂或交人類裁決。
