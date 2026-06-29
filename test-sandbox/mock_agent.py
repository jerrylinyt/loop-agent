import sys
import os
import re
import subprocess

def log(msg):
    print(f"[MOCK_AGENT] {msg}")

def main():
    if len(sys.argv) < 3:
        log("Usage: mock_agent.py <model> <prompt>")
        sys.exit(1)
        
    model = sys.argv[1]
    prompt = sys.argv[2]
    
    log(f"Invoked with model={model}")
    
    if "Git Review Gate" in prompt or "git_review" in prompt:
        log("Detected Git Review Gate prompt.")
        # Find the result file path in the prompt
        match = re.search(r'(\S+git_review_result)', prompt)
        if match:
            res_path = match.group(1).strip('`"\'')
        else:
            res_path = ".loop/default/.loop_state/git_review_result"
        
        log(f"Writing Git Review result to: {res_path}")
        os.makedirs(os.path.dirname(res_path), exist_ok=True)
        content = """1. 中斷與殘留防護: PASS
2. 排版與狀態檔結構破壞: PASS
3. 不合理狀態進展: PASS
4. 中間區段被挖空: PASS
5. 思考過程外洩: PASS
6. 語意一致性: PASS
7. AI 偷懶佔位符: PASS
8. 無故刪檔與路徑幻覺: PASS
9. 衝突標記與取代錯位: PASS
10. 基礎語法與格式全毀: PASS
11. 驗收證據缺失: PASS
12. 收斂計數防偽: PASS
13. 產出異動卻沒歸零收斂: PASS
14. 整合輪越界改葉子: PASS

[REVIEW: PASS]
"""
        with open(res_path, "w", encoding="utf-8") as f:
            f.write(content)
        sys.exit(0)
        
    elif "獨立 Plan Gate" in prompt or "plan_gate" in prompt:
        log("Detected Plan Gate prompt.")
        plan_md = None
        match = re.search(r'(\S+PLAN\.md)', prompt)
        if match:
            plan_md = match.group(1).strip('`"\'')
        else:
            plan_md = ".loop/default/PLAN.md"
            
        with open(plan_md, "r", encoding="utf-8") as f:
            plan_lines = f.readlines()
            
        new_plan_lines = []
        for line in plan_lines:
            if line.startswith("plan_gate_last:"):
                new_plan_lines.append("plan_gate_last: PASS\n")
            else:
                new_plan_lines.append(line)
                
        with open(plan_md, "w", encoding="utf-8") as f:
            f.writelines(new_plan_lines)
            
        log("Plan Gate check PASS.")
        subprocess.run(["git", "add", "-A"])
        subprocess.run(["git", "commit", "-m", "Plan gate PASS"])
        sys.exit(0)
        
    elif "生成/精修規劃書" in prompt or "plan" in prompt:
        log("Detected Plan Generation prompt.")
        plan_md = None
        match = re.search(r'(\S+PLAN\.md)', prompt)
        if match:
            plan_md = match.group(1).strip('`"\'')
        else:
            plan_md = ".loop/default/PLAN.md"
            
        control_md = ".loop/default/CONTROL.md"
        phase_dir = ".loop/default/phases"
        phase1_md = os.path.join(phase_dir, "PHASE1.md")
        
        changed = False
        if not os.path.exists(control_md):
            changed = True
            log("Generating CONTROL.md and PHASE1.md...")
            control_content = """# 🎛️ CONTROL — Test Project Control File

> plan_version: 1   framework_ref: ""

---

# 📁 第二段：Repository 結構
```
src/
.loop/
```

---

# 📊 第三段：變數與計數器
```yaml
current_phase: 1
p1_consecutive_pass: 0
p1_total_validations: 0
p1_last_result: ""

blocking_issues: 0
stop_condition_met: false
plan_version: 1
framework_ref: ""

last_round_mode: ""
last_round_result: ""
last_round_fail_tasks: ""

rounds_since_progress: 0
stuck_level: 0
current_model_tier: ""
enhanced_rounds_used: 0
human_required: false
```

---

# 🧩 第四段：各 Phase 狀態表 + Coverage

## Phase 1（測試階段）狀態表
| # | 任務 | 產出位置 | Status | Conv | Round |
|---|------|---------|--------|------|-------|
| 01 | TASK-01 | src/hello.py | TODO | 0/1 | - |

## Coverage 定義與統計
| 指標 | 分母 | 分子 | % | 更新 Round |
|------|------|------|---|-----------|
| 任務 | 1 | 0 | 0% | - |

---

# 🔗 第五段：需求 → 任務 追溯表
| 需求 ID | 對應任務 | 驗證 |
|---------|---------|------|
| R001 | TASK-01 | run hello.py |

---

# 🐛 第六段：Issue 索引
| Issue ID | 等級 | 標題 | Phase/TASK | 狀態 | 建立 Round |
|----------|------|------|-----------|------|-----------|
| (無) | | | | | |

---

# 📝 第七段：最近執行摘要
```
=== Round #0 ===
Initialized
```
"""
            with open(control_md, "w", encoding="utf-8") as f:
                f.write(control_content)
                
            phase1_content = """# 📋 PHASE1 — 測試階段 任務規格

## TASK-01｜測試任務
- **依賴讀取**: 無
- **做什麼**: 建立 src/hello.py 檔案
- **產出位置**: src/hello.py
- **驗證標準**: 檔案存在
- **收斂**: 單任務收斂(門檻 1)
"""
            os.makedirs(phase_dir, exist_ok=True)
            with open(phase1_md, "w", encoding="utf-8") as f:
                f.write(phase1_content)
        
        with open(plan_md, "r", encoding="utf-8") as f:
            plan_lines = f.readlines()
        
        new_plan_lines = []
        for line in plan_lines:
            if line.startswith("plan_changed_last:"):
                val = "true" if changed else "false"
                new_plan_lines.append(f"plan_changed_last: {val}\n")
            else:
                new_plan_lines.append(line)
                
        with open(plan_md, "w", encoding="utf-8") as f:
            f.writelines(new_plan_lines)
            
        log(f"Plan Generation done. changed={changed}")
        subprocess.run(["git", "add", "-A"])
        subprocess.run(["git", "commit", "-m", f"Plan update (changed={changed})"])
        sys.exit(0)
        
    elif "BOOT SEQUENCE" in prompt or "boot-sequence" in prompt:
        log("Detected Execution/Base Prompt.")
        control_md = ".loop/default/CONTROL.md"
        
        with open(control_md, "r", encoding="utf-8") as f:
            control_content = f.read()
            
        phase_match = re.search(r"current_phase\s*:\s*(\d+)", control_content)
        p1_pass_match = re.search(r"p1_consecutive_pass\s*:\s*(\d+)", control_content)
        
        current_phase = int(phase_match.group(1)) if phase_match else 1
        p1_pass = int(p1_pass_match.group(1)) if p1_pass_match else 0
        
        log(f"Execution: phase={current_phase}, pass={p1_pass}")
        
        if "TODO" in control_content:
            log("Task is TODO. Transitioning to CONVERGED.")
            os.makedirs("src", exist_ok=True)
            with open("src/hello.py", "w", encoding="utf-8") as f:
                f.write("print('Hello from Loop Agent')\n")
            
            control_content = control_content.replace(
                "| 01 | TASK-01 | src/hello.py | TODO | 0/1 | - |",
                "| 01 | TASK-01 | src/hello.py | CONVERGED | 1/1 | 1 |"
            )
            control_content = re.sub(
                r"last_round_mode\s*:\s*.*",
                "last_round_mode: 推進",
                control_content
            )
            control_content = re.sub(
                r"last_round_result\s*:\s*.*",
                "last_round_result: PASS",
                control_content
            )
            os.makedirs("src/.reverify", exist_ok=True)
            with open("src/.reverify/TASK-01-R001.md", "w", encoding="utf-8") as f:
                f.write("# Reverify TASK-01\nPASS")
            
            with open(control_md, "w", encoding="utf-8") as f:
                f.write(control_content)
                
            subprocess.run(["git", "add", "-A"])
            subprocess.run(["git", "commit", "-m", "R001 | phase1 | TASK-01 | 推進 | hello.py created"])
            sys.exit(0)
            
        elif "CONVERGED" in control_content:
            if p1_pass == 0:
                log("All tasks converged. Running validation.")
                control_content = re.sub(
                    r"p1_consecutive_pass\s*:\s*\d+",
                    "p1_consecutive_pass: 1",
                    control_content
                )
                control_content = re.sub(
                    r"last_round_mode\s*:\s*.*",
                    "last_round_mode: 驗證",
                    control_content
                )
                control_content = re.sub(
                    r"last_round_result\s*:\s*.*",
                    "last_round_result: PASS",
                    control_content
                )
                os.makedirs("src/.validate", exist_ok=True)
                with open("src/.validate/p1-R002.md", "w", encoding="utf-8") as f:
                    f.write("# Validation p1-R002\n- 測試任務: PASS\n[MOCK TEST OUTPUT] All green\n")
                
                with open(control_md, "w", encoding="utf-8") as f:
                    f.write(control_content)
                    
                subprocess.run(["git", "add", "-A"])
                subprocess.run(["git", "commit", "-m", "R002 | phase1 | 驗證 | PASS"])
                sys.exit(0)
            else:
                log("Validation pass already satisfied. Preparing stop sequence.")
                print("LOOP COMPLETE")
                sys.exit(0)
                
    else:
        log(f"Unknown prompt type. Prompt: {prompt[:100]}")
        sys.exit(1)

if __name__ == "__main__":
    main()
