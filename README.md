# 🔁 loop-engineering — 通用 Loop Engineering Agent 框架

把「**做不完、信不過、會中斷、會卡死**」的大任務，交給一個「由 AI agent 反覆執行、直到收斂達標」的迴圈。
本框架是**共享、唯讀**的：它只提供讀取，所有要改的東西（規劃書 + code）都落在你的 **code repo**。

> 設計緣由與完整取捨見 `../loop-agent/REFACTOR_PLAN.md`。方法論見 `rules/BLUEPRINT.md`。

## 三段生命週期
```
① 需求討論（互動）   generators/0-requirements-interview.md → .loop/REQUIREMENTS.md  〔人類確認〕
② 生成規劃書（半自動）generators/1-plan-generator.md → .loop/{loop.config.yaml, CONTROL.md, phases/*.md}
                     generators/2-plan-review-gate.md（Plan Gate）                  〔人類確認 plan〕
③ 執行迴圈（自動）   engine/loop.py 反覆觸發 agent → 收斂/自我修正/震盪升級 → 直到達標或交人類
```

## 目錄
```
loop-engineering/            ← 共享、唯讀框架（不進任何 code repo）
├── rules/                   規則區（通用方法論，技術中立）
│   ├── BLUEPRINT.md             設計藍圖（九大原則、反模式）
│   ├── boot-sequence.md         每輪開機程序（STEP G→10）
│   ├── git-safety.md            Git 安全網（只作用工作區；禁寫框架）
│   ├── convergence.md           單任務收斂（不信單次）
│   ├── completeness.md          大範圍防漏（列舉清單+行覆蓋）
│   ├── oscillation-escalation.md 震盪偵測 + 三層升級 + FROZEN
│   ├── issues.md                Issue 分級 + 修正記錄
│   ├── state-model.md           狀態/流程控制（N 階段、config 驅動）
│   └── context-budget.md        ★Context 防爆（橫切硬約束）
├── generators/              生成區（前期：需求 → 規劃書）
│   ├── 0-requirements-interview.md / 1-plan-generator.md / 2-plan-review-gate.md
│   └── templates/           CONTROL / PHASE / REQUIREMENTS / loop.config / profile 樣板
├── engine/                  引擎區（執行期：loop.py，config 驅動、N 階段）
└── init-project.py          腳手架：在 code repo 內建 .loop/、寫 framework_path
```

## 四區 + 使用者定義區
| 區 | 放什麼 | 位置 |
|----|--------|------|
| 規則區 | 通用方法論 | 本框架 `rules/`（唯讀） |
| 設定區 | 階段/門檻/模型/停止條件 | code repo `.loop/loop.config.yaml` |
| 專屬規則區 | 狀態表/任務規格/coverage | code repo `.loop/CONTROL.md` + `phases/` |
| 工作區 | 輸入/產出/log/活計數器 | code repo |
| 使用者定義區 | 模型/風格/門檻預設（跨專案） | `~/.loop/profile.yaml` |

cascade：**框架預設 < `~/.loop/profile.yaml` < 專案 `.loop/loop.config.yaml` < 環境變數**。

## 快速開始
```bash
# 0) 框架放在固定位置（本資料夾就是；或 clone 到 ~/.loop/framework）
# 1) 在你的 code repo 初始化
python3 <此框架路徑>/init-project.py /path/to/your-code-repo
# 2) 跑階段① 需求訪談（把 generators/0 交給 agent）→ 確認 REQUIREMENTS.md
# 3) 跑階段② 生成規劃書（generators/1）→ Plan Gate（generators/2）→ 確認
# 4) 執行
cd /path/to/your-code-repo/.loop && python3 <此框架路徑>/engine/loop.py
#   另一視窗：tail -f loop.log
```

## 核心原則（為什麼這樣設計）
- **文件即狀態**：換 agent / 換模型 / 中斷後，只靠 `.loop/` 就能接手。
- **不信單次**：收斂協定（獨立重推 + 連續 N 次一致）。
- **不會漏看**：列舉清單（分母）+ 行覆蓋 + 集合穩定收斂。
- **卡死有逃生門**：震盪偵測 → 三層升級 → FROZEN → 交人類。
- **Git 是安全網**：一輪一 commit（只在工作區）；框架唯讀、絕不寫入。
- **Context 防爆**：log 不進 context、CONTROL 保持決策最小集、不整批讀資料。
