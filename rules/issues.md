# 🐛 RULE — Issue 管理 + 修正記錄

> **唯讀框架規則**。不確定就建 Issue,**絕不腦補**(BLUEPRINT 原則 6)。

## 1. Issue 分級
| 等級 | 定義 | 阻擋停止? |
|------|------|----------|
| `BLOCKING` | 不解決就無法正確完成 | ✅ 必須為 0 |
| `NON_BLOCKING` | 已知風險/外部依賴,可帶著完成 | ❌ 允許留存 |

> ⚠️ **千萬別把停止條件設成「Open Issue = 0」**——外部依賴的 Issue 永遠關不掉,會死結。
> 停止條件用「**無 BLOCKING Issue**」(即 `blocking_issues == 0`)。
>
> 🚨 強制約束(分級從嚴,對齊 convergence.md 的「實質/表面」從嚴預設):有疑義一律先列 `BLOCKING`;
>    只有「明確外部依賴 / 已知且可接受的風險」才可列 `NON_BLOCKING`,且須在 Issue 內寫明理由。
>    ❌ 嚴禁:為了讓停止條件成立(`blocking_issues==0`)、或為了避免 `consecutive_pass` 歸零,
>    把一個「不解決就無法正確完成」的問題降級成 NON_BLOCKING。分不清屬於哪級 → 從嚴算 BLOCKING。

## 2. 何時開 Issue（不准腦補）
遇到不確定一律建 Issue,不准腦補:未知格式、不明錯誤碼、無法解析的動態邏輯、缺檔、
規格矛盾(配合 oscillation-escalation.md 開 BLOCKING + FROZEN)、發現前一次 commit 損壞(配合 git-safety.md G0)。

## 3. Issue 儲存（Context 防爆）
- **一 Issue 一檔**:`<outputs>/issues/issue-NNN.md`(內文放這裡)。
- **CONTROL 只留索引一行 + blocking 計數**,不貼 Issue 內文(見 context-budget.md):
```
| Issue ID | 等級 | 標題 | Phase/TASK | 狀態 | 建立 Round |
| 001 | BLOCKING | <一句> | 1/TASK-05 | OPEN | R012 |
```
- CONTROL 的 `blocking_issues` 計數器 = 目前 OPEN 的 BLOCKING 數。任一新增 BLOCKING → 該 phase `consecutive_pass` 歸零。

## 4. 修正記錄（寫進對應產出檔底部，不塞 CONTROL）
```
=== 修正記錄 #001 ===
時間/Round:      Phase:
問題所在檔案:
問題描述:
修正內容:
同步更新的引用檔案:（雙向 traceability）
git 還原?:（是否用了 git checkout 救檔,救自哪個 commit）
===
```

## 5. 重置規則
- 任一次驗證 FAIL,或新增 BLOCKING Issue → 對應 phase 的 `consecutive_pass` 立即歸零。
- BLOCKING Issue 關閉後,計數重新累積。
