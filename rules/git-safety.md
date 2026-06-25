# 🧷 RULE — Git 安全網（防止檔案被弄壞）

> **唯讀框架規則**。git 在這裡的首要任務是**還原點**:任何一輪把檔案改壞,都能退回上一輪的良好狀態。
> ⚠️ **作用範圍**:git 只作用於「**工作區(被 agent 操作的 code repo)**」。`framework_path` 下的共享框架是**外部、唯讀**,絕不寫入、絕不納入此 repo 的 git。

## 1. 核心機制
- **一輪一 commit**(BOOT STEP C):每輪結束提交一次,訊息含 Round/Phase/Task。每個 commit 都是乾淨還原點。
- **開機自檢 + 還原**(BOOT STEP G):下一個 agent 開機先驗證主控檔健康,壞了就 `git checkout HEAD -- <檔>` 從上一個 commit 救回。
- **局部編輯優先**:改主控檔/規格檔用局部取代,不整檔重寫,從源頭降低「變白」機率。寫完讀回確認。

## 2. 安全紅線（絕不做）
- ❌ `git reset --hard`、`git clean -fd/-fdx`、`git checkout .`（無差別覆蓋,會吃掉本輪以外的好東西）
- ❌ `git push --force`
- ❌ 刪除 `.git`、刪除輸入來源
- ❌ **寫入 / commit `framework_path` 下任何檔**(框架唯讀)
- ✅ 只允許「逐檔還原」:`git checkout HEAD -- <指定檔>`

## 3. 寫檔守則（防變白）
1. 優先用「targeted edit / 局部取代」,避免整檔重寫。
2. 每次寫完立刻讀回確認:非空、結構完整。
3. 若發現自己把檔案寫壞且「尚未 commit」→ `git checkout -- <檔>` 還原後重做。
4. **寫入白名單**:只允許寫本專案 `.loop/`(CONTROL/phases/config/log)與工作區產出;其餘(尤其 framework_path)一律禁止。

## 4. STEP G 開機自檢（六步）
```
G0. 【AGENT 親自讀 diff、用語意審查前一次 commit】(前提:存在 HEAD~1)
    ❗這一步必須由你讀內容判斷,不是靠數字。損壞常是「檔案還很大、只是中間被砍一段」,
      機械式(位元組/行數)判斷抓不到,只有讀得懂內容才看得出。
    a. git show HEAD --stat ; git diff HEAD~1 HEAD（重點看「刪除/-」的部分）
    b. 用語意判斷:commit 訊息對得上實際改動嗎?有沒有原本有內容的段落被無故整段刪掉/截斷?
       刪掉的內容有搬到別處或有理由嗎?對照狀態表/日誌,上一輪「該做的」與「實際改的」相符嗎?
    c. 合理 → 不動,往下。 不合理 → git revert --no-edit HEAD（用新 commit 撤銷,不改寫歷史;
       衝突則 git revert --abort 後改逐檔 git checkout HEAD~1 -- <受損檔> 救回再 commit）+ 開 Issue。
    d. 以「已修復的 HEAD」為基準再做 G1~G4。
G1. 工作區 .git 不存在 → 記住稍後 git init（初始化任務）。
G2. 主控檔「整檔空白」粗篩(非空 + 第一行是其標題)→ 損壞就 git checkout HEAD -- <該檔>。
G3. 懷疑其他產出檔被弄壞 → git status 檢視,逐一處理(禁無差別還原)。
G4. 確認工作區乾淨可信才往下。
```

## 5. 復原指引
1. 還沒 commit 的壞改 → `git checkout -- <檔>`。
2. 已 commit 但是上一輪弄壞 → `git checkout HEAD~1 -- <檔>` 取回更早版本,並開 Issue。
3. 不確定哪裡壞 → `git status` + `git diff` 逐檔處理,**不要無差別還原**。
4. 整個前一次 commit 就是損壞 → `git revert --no-edit HEAD`（見 G0）。

## 6. 分工：程式兜底空白、AGENT 審內容
- **程式層(loop 引擎 / git_guard)只做兜底**:把「整檔被清空」的主控檔在繼續前還原,確保下一輪 agent 至少讀得到 CONTROL。**不對內容做合理性判斷、不自動 revert**(程式看不懂內容,亂 revert 反而誤殺正常重構)。
- **AGENT 層(STEP G0)做語意審查**:每輪開機親自讀 diff,不合理就自己 revert + 開 Issue。
- 兩層都救不回(極端)→ 開 BLOCKING Issue + 設 human_required,停下交人類。

## 7. .gitignore（初始化任務建立，工作區用）
```
node_modules/      # 或對應語言的相依目錄
dist/  build/      # 建置產物
*.log              # loop.log 等不進版控
.loop/.loop_state/ # 震盪偵測狀態(引擎用,不進版控也不進 context)
.DS_Store
```
> 輸入、產出、`.loop/` 內的 CONTROL/phases/config 都要進版控。只有相依、建置產物、log、loop_state 忽略。

## 8. commit 訊息格式
```
R012 | phase1 | TASK-05 | 推進 | <一句摘要>
R045 | phase2 | TASK-B13 | 驗證 | build/test 全綠,p2_pass=7
```
