# 引擎側需求：逐輪歷史 `rounds.jsonl`

> 給**引擎實作 agent** 的工作說明書（動的是 `engine/`，不是 dashboard）。
> 目的：讓引擎在每一輪結束時，append 一行結構化紀錄到 workspace 的狀態夾，作為 dashboard 進度趨勢圖（D3 sparkline）與任何離線分析的單一事實來源。
>
> **核心原則**：這是**唯讀於既有狀態、只新增一個檔**的低風險改動。**不得**改動 CONTROL.md / TREE.md 既有欄位語意、不得改變現有控制流程或回傳碼。若這行寫入失敗，**引擎必須照常繼續跑**（best-effort，吞例外、記 warning）。

---

## 1. 產出物

每個 workspace 一個檔：

```
<repo>/.loop/<ws>/.loop_state/rounds.jsonl
```

- **JSON Lines**：一行一個 JSON 物件，UTF-8，`\n` 結尾。
- **Append-only**：每輪結束 append 一行，跨程序重啟自然累積（與 `fail_history` / `progress` 同一個 `state_dir`，見 [`engine/state.py`](../engine/state.py)）。
- 路徑用 `cfg["runtime"]["state_dir"]`（既有變數，迴圈內就有），不要自己拼路徑。

### 每行 schema

| 欄位 | 型別 | 來源（迴圈內現有變數） | 說明 |
|------|------|----------------------|------|
| `ts` | string | `datetime.now().strftime("%F %T")` | 本輪結束時間（本機時區） |
| `round` | int | `i` | **程序內**的輪次計數；**會隨重啟從 1 重來**，不可當全域唯一鍵（見 §4） |
| `loop_type` | string | 常數 | `"execute"`（線性）/ `"tree"`（樹）/ `"plan"`（規劃，選做） |
| `phase` | string | `phase`（= `current_phase`） | 當前 phase id |
| `leaf` | string\|null | `current_leaf`（樹模式才有，線性填 `null`） | 當前處理的葉子節點 |
| `result` | string | `result`（= `last_round_result`） | 例：`PASS` / `FAIL` / `NA` / `""` |
| `mode` | string | `mode`（= `last_round_mode`） | 例：含「驗證」、「中斷」等 |
| `killed` | string\|null | `killed` | watchdog 中斷原因：`"timeout"` / `"idle"` / `null` |
| `stuck_level` | int | `stuck_level` | 0/1/2 |
| `rounds_since_progress` | int | `rounds_since` | |
| `enhanced_rounds_used` | int | `enhanced_used` | |
| `no_activity` | int | `no_activity` | 連續無活動輪數（idle/killed 取大） |
| `consecutive_pass` | int | `cur_pass` | 當前 phase 的 `p{phase}_consecutive_pass` |
| `progressed` | bool | `progressed` | 本輪是否判定為有進展 |
| `model_tier` | string | `tier` | 本輪使用的模型階層標籤 |

> 上述變數**在寫入點當下全部已存在且為最終值**（見 §3 的錨點）。不要為了這份紀錄重新 `get_val` 一次，直接用迴圈內的區域變數即可，保證與引擎當輪決策一致。

範例行：
```json
{"ts":"2026-06-27 22:14:03","round":5,"loop_type":"execute","phase":"2","leaf":null,"result":"PASS","mode":"驗證","killed":null,"stuck_level":0,"rounds_since_progress":0,"enhanced_rounds_used":0,"no_activity":0,"consecutive_pass":3,"progressed":true,"model_tier":"default"}
```

---

## 2. 新增 helper（放 `engine/state.py`）

沿用該檔既有的 `fail_history_path` / `save_progress` 風格，新增兩個函式：

```python
import json

def rounds_log_path(cfg: dict) -> str:
    return os.path.join(cfg["runtime"]["state_dir"], "rounds.jsonl")


def append_round_record(cfg: dict, record: dict) -> None:
    """Append 一行逐輪紀錄到 rounds.jsonl。Best-effort：失敗只記 warning，絕不中斷主迴圈。"""
    p = rounds_log_path(cfg)
    try:
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        line = json.dumps(record, ensure_ascii=False)
        with open(p, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except (OSError, TypeError, ValueError) as e:
        logger.warning(f"Failed to append round record: {e}")
```

- `ensure_ascii=False` 讓中文 mode/result 維持可讀。
- 用 `"a"` append 模式，**不可** rewrite 整檔（避免長跑時 O(n²) 與競態）。
- 例外要吞掉（含 `TypeError`：萬一 record 帶了不可序列化的值）。

---

## 3. 寫入點（兩處，必做）

`engine/loop.py` 兩個執行迴圈在每輪結尾都有**完全相同的一段收尾**——找這個錨點，在它**後面**插入一行 `append_round_record(...)`：

```python
        set_val(control, "rounds_since_progress", str(rounds_since))
        set_val(control, "stuck_level", str(stuck_level))
        set_val(control, "enhanced_rounds_used", str(enhanced_used))
        progress = {"sig": sig, "idle": idle_rounds, "killed_streak": killed_streak,
                    "phase": phase, "last_pass": cur_pass}
        save_progress(cfg, **progress)
        # ↓↓↓ 新增（best-effort，放在 save_progress 之後）
        append_round_record(cfg, {
            "ts": datetime.now().strftime("%F %T"),
            "round": i, "loop_type": "execute",          # 樹迴圈改成 "tree"
            "phase": phase, "leaf": None,                 # 樹迴圈填 current_leaf
            "result": result, "mode": mode, "killed": killed,
            "stuck_level": stuck_level, "rounds_since_progress": rounds_since,
            "enhanced_rounds_used": enhanced_used, "no_activity": no_activity,
            "consecutive_pass": cur_pass, "progressed": progressed,
            "model_tier": tier,
        })
```

兩處錨點：
1. **線性執行**：`_run_loop_locked`，在 [`engine/loop.py:430`](../engine/loop.py) 的 `save_progress(cfg, **progress)` 之後。`loop_type="execute"`、`leaf=None`。
2. **樹模式執行**：`_run_tree_execute_locked`，在 [`engine/loop.py:642`](../engine/loop.py) 的 `save_progress(cfg, **progress)` 之後。`loop_type="tree"`、`leaf=current_leaf`。

> **重要**：只在「正常跑完一輪」的收尾寫入。對於「Git Review Gate 還原後 `continue` 跳過本輪」「`is_done`/`human_needed` 提早 `return`」這些路徑**不要**補寫——那些不是一個完成的執行輪，補了只會讓趨勢圖出現雜訊。提早 `return 2`（升級人類後硬性保險）那條也維持不寫（它在 `save_progress` 之前就 return 了）。

### 選做：規劃迴圈
若要連規劃階段也有資料點，可在 [`engine/plan_loop.py`](../engine/plan_loop.py) 的每輪收尾比照寫入，`loop_type="plan"`，欄位能填多少填多少（拿不到的填 `null`）。**非必要**，趨勢圖主要看 execute；不確定就先不做。

---

## 4. 邊界與相容性

- **`round` 會隨重啟重來**：每次 `run.py` 起新程序，`i` 從 1 開始。因此 `round` **不是**全域唯一鍵。dashboard 畫趨勢圖時 x 軸請用「行序 / `ts`」，把 `round` 僅當參考欄位。（若日後需要全域單調序號，可另存一個持久化 counter，但本期不做，避免增加狀態。）
- **檔案成長**：一行約 200–300 bytes，1000 輪約 0.2–0.3 MB，可接受，**本期不做 rotation**。dashboard 端只讀「最後 N 行」即可。若未來要設上限，採「append 到門檻後一次性裁切保留最後 N 行」，不要每輪 rewrite。
- **既有 workspace 無此檔**：第一次寫入時 `append` 自動建檔；dashboard 端要容忍檔案不存在（回空陣列）。
- **不影響 Git Review Gate**：此檔在 `.loop_state/`（執行期狀態夾），與 `fail_history`/`progress`/`run.lock` 同層。確認它**不會**被 commit（應已被 `.gitignore` 涵蓋——實作前 `git check-ignore <path>` 驗一下；若沒被忽略，要補進對應 ignore 規則，因為它不該進版控、也不該觸發 review gate 的 diff）。
- **時區**：用本機時間、`%F %T` 格式，與引擎其他 log 時間戳一致（見 `loop.py` 既有 `ts`）。

---

## 5. 驗收標準

1. 跑一輪線性 execute（可用本 repo 當對象），`<repo>/.loop/<ws>/.loop_state/rounds.jsonl` 出現新行，欄位齊全、JSON 合法、中文不被跳脫成 `\uXXXX`。
2. 連跑多輪，每輪 append 一行；中途 `Ctrl+C` 再重啟，新行繼續 append、舊行不被覆寫。
3. 一輪被 watchdog 中斷（`killed` 非 null）後，該行 `killed` 正確記錄、`result` 為 `NA`。
4. 樹模式跑一輪，`loop_type="tree"` 且 `leaf` 為當前葉子 id。
5. 故意讓 `state_dir` 不可寫（或 mock 例外），引擎**照常完成該輪**、只在 log 留一行 warning（驗證 best-effort 不阻斷）。
6. `git status` 不應出現 `rounds.jsonl`（已被忽略）。
7. 既有測試全綠（`pytest`），無回歸。

---

## 6. 與 dashboard 的介面契約（給 dashboard 端對齊）

dashboard 將新增 `GET /api/projects/{id}/rounds?limit=N`：讀此檔最後 N 行、逐行 `json.loads`、回成陣列（壞行跳過）。前端用 §1 的欄位畫 sparkline（`stuck_level` 隨序變化、`result`/`progressed` 標點）。**欄位名是兩端的契約**，若引擎端調整欄位，dashboard 的 `/rounds` 解析與 sparkline 需同步調整。
