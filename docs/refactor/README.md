# 📋 Refactor 實作計畫書系列 — 總索引

> 依據 `docs/review/2026-07-02-framework-review.md` 的體檢結論拆解成的**可交付給 coding agent 的實作計畫書**。
> 每份計畫書自成一包（可獨立驗收），但有依賴順序，請按編號執行。

## 執行順序與依賴

```
1-bugfix-and-hardening.md      ← 先做：修 blocker bug + 夜間跑安全網（其餘計畫的地基）
        │
        ├── 2-overnight-workflow.md      ← 依賴 1（RUN_REPORT / notify / finish 流程）
        └── 3-context-growth-budget.md   ← 依賴 1（rounds.jsonl 欄位）；與 2 可並行
                │
                ▼
4-engine-v3-orchestration.md   ← 大翻新，依賴 1/2/3 全部完成
                │
                ▼
5-workspace-analytics-optimization.md   ← 執行歷史分析與校準優化，依賴 1/2/3/4
```

## 給執行本系列計畫的 coding agent 的共同約定

1. **一份計畫書 = 一個 feature branch = 一個 PR**。branch 命名 `refactor/<編號>-<slug>`。
2. 每份計畫書內的工作項（T1, T2…）**依序執行**，每個工作項一個以上的 commit，訊息格式 `refactor(<編號>): T<n> <一句摘要>`。
3. **不需要向後相容**（使用者已明確授權）：可以改資料結構、刪除死碼、改預設值，不必留舊路徑。唯一例外：`rules/` 與 `generators/` 是會被既有專案 `sync_framework_docs` 同步走的文件，語意變更要同步改所有引用處。
4. 每個工作項完成後必須：
   - 跑 `python3 -m pytest engine/test_engine_features.py -x`（既有測試不得變紅）；
   - 為新行為**補測試**（驗收標準有列的測項為最低要求）；
   - 更新受影響的文件（README / engine/README.md / rules）。
5. **驗收標準是機械可查的**：每份計畫書末尾的驗收清單，逐條附驗證指令或測試名稱；全部打勾才算完成該計畫書。
6. 禁止事項：不動 `dashboard/`（另案）；不改 git 安全紅線的語意（`rules/git-safety.md` §2）；不引入新的第三方依賴（標準庫 + PyYAML 為限，計畫書內明確授權者除外）。
7. 計畫書如與現有程式碼衝突（行號漂移、函式已改名），**以計畫書描述的「行為規格」為準**，行號僅供定位。

## 各計畫書一句話摘要

| 編號 | 檔案 | 摘要 |
|------|------|------|
| 1 | `1-bugfix-and-hardening.md` | 修 10 個已確認缺陷（含啟動 blocker B1）、快速失敗偵測、牆鐘上限、終止通知、收工報告、CI 煙霧測試 |
| 2 | `2-overnight-workflow.md` | 隔離分支模式、統一 `loop` CLI、doctor/smoke、需求確認硬 gate、PLAN_SUMMARY、人類回饋通道、驗收 gate |
| 3 | `3-context-growth-budget.md` | 系統性治理「檔案無限長大 → 被讀進 context / 拖垮引擎」：state.json 預算執法、jsonl 輪替與尾讀、review prompt 內嵌上限、證據檔修剪 |
| 4 | `4-engine-v3-orchestration.md` | v3 大翻新：引擎挑任務發任務卡、verify 契約引擎執行、state.json schema v3、Review Gate 分層、rules 瘦身 |
| 5 | `5-workspace-analytics-optimization.md` | 分析跑過的 workspace：任務級成本歸因、`loop analyze`、門檻校準建議（只建議不自動改）、輪數估算回饋校正 |
