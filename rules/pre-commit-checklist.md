# ✅ RULE — Pre-Commit 自查清單（STEP C 用）

> **唯讀框架規則**。在 `git add / commit` 前快速機械確認，攔截自己明顯能發現的問題。
> 不需重新讀 diff，只看「本輪剛寫/改的檔案」。
> 深度語意稽核（收斂計數、驗收證據、整合越界等）由外部 Git Review Gate 獨立承接。

## 6 項快速自查

```
□ 1. 檔案完整性
     本輪寫入的每個檔案：結尾非空截斷、Markdown ``` 區塊已閉合、
     HTML 標籤已閉合、無寫到一半的殘留句子。

□ 2. state.json 結構
     若本輪修改了 state.json（透過 CLI）：git diff state.json
     確認仍是合法 JSON（大括號閉合、無多餘逗號）。

□ 3. 無佔位符偷懶
     本輪修改的程式碼/文件中，無 `// ... existing code ...`、
     `# TODO: implement`、`# 此處省略` 等佔位符替代真實內容。

□ 4. 無衝突標記殘留
     本輪改動的檔案中，無 `<<<<<<< HEAD`、`=======`、`>>>>>>>` 殘留。

□ 5. commit 訊息與實際改動吻合
     commit message 說改了什麼，實際就改了什麼；無「說 A 改 B」。
     格式：`R### | phase{n} | TASK-## | 推進/驗證 | <一句摘要>`

□ 6. 未寫入 framework_path
     本輪無任何檔案寫入 framework_path（唯讀框架目錄）。
```

> 6 項全過 → 執行 `git add -A && git commit`。
> 有任何一項 ❌ → 修正後再 commit，不要帶問題 commit 進去讓外部 Review Gate REVERT。
