# 🛟 RULE — 震盪偵測與模型升級協定（改A壞B 防卡死）

> **唯讀框架規則**。解決「改 A 壞 B、改 B 壞 A,永遠卡在 verify」的死循環。
> **偵測由外部 loop 引擎做**(它每輪 parse CONTROL + 看 git 改動,最客觀;agent 自己繞圈時往往不自知)。
> **升級階梯固定三層:預設 → 增強 → 人類。** 門檻與模型指令全來自 `loop.config.yaml`(`oscillation` / `models`)。

## A. 兩種「卡住」與訊號
| 卡法 | 現象 | 偵測訊號 |
|------|------|----------|
| **不收斂** | 同一問題一直修不好 | `rounds_since_progress >= stall_threshold`（連續失敗驗證輪沒進展）|
| **震盪 A↔B** | 每輪都「修好一個」卻原地繞 | 最近 `osc_window` 輪的「失敗指紋」只在 ≤`osc_distinct_max` 種間循環,且有重複 |

**失敗指紋(fingerprint)** = `sha1( 排序(last_round_fail_tasks) + "|" + 排序(本輪 git 改動檔案) )`
- `last_round_fail_tasks`:agent 每輪回填(驗證失敗被打回的任務)。
- 改動檔案:外部 loop 用 `git diff --name-only HEAD~1 HEAD` 取得。
- **只在「失敗的驗證輪」推進指紋歷史**(推進/初稿輪不算,避免誤判正常進展)。
- 指紋歷史存 `.loop_state/`(引擎用,環狀固定長度 = osc_window,**不進 context**)。

## B. 三層升級狀態機（外部 loop 執行）
```
Lv0 預設模型（current_model_tier=default, stuck_level=0）
  每個失敗驗證輪:rounds_since_progress++；PASS 一次就歸零、stuck_level 歸零、換回預設。
  若 偵測到震盪 或 rounds_since_progress>=stall_threshold:
      → stuck_level=1、current_model_tier=enhanced、enhanced_rounds_used=0
        下一輪改用「增強模型」,並注入 C 的特別提示。

Lv1 增強模型（current_model_tier=enhanced, stuck_level=1）
  每輪 enhanced_rounds_used++。
  若 出現 PASS / 有實質進展 → 回 Lv0:換回預設、stuck_level=0、計數歸零(省成本)。
  若 enhanced_rounds_used>=enhanced_max_rounds 仍未解 → stuck_level=2,進 Lv2。

Lv2 升級人類（stuck_level=2）
  指示 agent:對互卡任務開一個 BLOCKING Issue(寫清楚 A、B 衝突點)、
             把涉及任務改 FROZEN(挑任務時跳過)、若還有其他可做任務就先做。
  終止判斷(二擇一即停下交人類):
    · agent 判定「除凍結任務外已無可做任務」→ 設 human_required=true
    · 或 升級人類後再撐 human_stop_after 輪仍無進展(硬性保險)
  loop 偵測到 human_required==true(或硬性保險)→ 停止觸發、大聲通知人類。
```

## C. 增強模型那一輪要注入的提示（關鍵）
> 換更強模型只治「能力不足」,治不了「規格本身矛盾」。所以一定要先讓它判斷根因:
```
前幾輪偵測到反覆修壞（A↔B 震盪 / 卡在驗證）。請先「判斷根因」再動手:
 (1) 若是「實作疏漏」（A、B 其實可同時滿足,只是之前沒看出耦合）→ 一次修對兩邊。
 (2) 若是「規格矛盾」（A 的規格與 B 的規格本質衝突,無法同時成立）→
     不要硬修!直接開 BLOCKING Issue,寫清楚衝突的兩條規格與出處,
     把涉及任務標 FROZEN,交人類裁決。
判斷依據要寫進 Issue 或修正記錄,不要默默繼續繞圈。
```

## D. FROZEN 狀態
- 任務狀態 `FROZEN`:因規格衝突暫凍結,**BOOT STEP 4 挑任務時跳過**。
- **逃生門比任何自動修復都重要**:遇到規格矛盾,凍結互卡任務、跳做別的、最後停下交人類,才不會無限迴圈。

## E. 人類交棒後的重啟
人類解決衝突 → 更新規格/需求 → 把該任務改回 `NEEDS_REVISION`、清掉對應 BLOCKING Issue、
`stuck_level=0`、`human_required=false` → 重新觸發 loop,從 NEEDS_REVISION 任務接續。

## 設計要點
- 換模型只治能力不足;增強模型那輪**務必注入 C 的提示**(先判根因)。
- 建議「預設→增強→人類」精簡三層即可;無腦輪流整串模型,遇到規格矛盾只是把每個模型都燒一輪。
