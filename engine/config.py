import os
import logging
import yaml

logger = logging.getLogger(__name__)

# ─────────────── 框架預設（cascade 最底層） ───────────────
DEFAULTS = {
    "framework_path": os.path.expanduser("~/.loop/framework"),
    "index": os.path.expanduser("~/.loop/index.md"),   # 跨專案總覽（自動維護）
    "control": "CONTROL.md",
    "control_files": ["CONTROL.md", "phases/*.md"],
    "workspace": {"mode": "in_repo"},
    "phases": [],                       # 由專案 config 提供
    "stop_condition": {
        "final_phase_pass_gte": 10,
        "blocking_field": "blocking_issues",
        "blocking_eq": 0,
        "done_flag": "stop_condition_met",
        "human_flag": "human_required",
    },
    "extra_thresholds": {},
    "oscillation": {
        "stall_threshold": 6,
        "osc_window": 8,
        "osc_distinct_max": 3,
        "enhanced_max_rounds": 8,
        "human_stop_after": 4,
    },
    # ── 最小工作單位 proxy 圍欄（可校準） ──
    "min_unit": {
        "max_files": 3,
        "max_lines": 150,
    },
    # ── 硬 breaker：撞線即凍結交人，程式不准自我放寬（可校準） ──
    "breaker": {
        "max_depth": 5,
        "max_leaves": 1000,        # 刻意設大——明顯壞掉才觸發的跳閘，非壓樹目標
        "max_leaf_reflow": 3,
        "growth_stall_rounds": 6,
    },
    "runtime": {
        "max_rounds": 600,
        "interval_seconds": 5,
        "round_timeout_seconds": 3600,
        "idle_timeout_seconds": 1800,
        "control_min_bytes": 200,
        "log_file": "./loop.log",
        "state_dir": "./.loop_state",
        "log_rotate_max_mb": 50,
        "log_rotate_keep": 5,
        "journal_in_control_keep": 1,
        "control_max_bytes": 60000,
        "console_echo": True,            # 直接把 agent 詳細輸出印到主控台（不用另開視窗 tail -f）；LOOP_QUIET=1 可關
    },
    # ── Agent 指令與提示（全抽成設定；code 只讀這裡，不寫死）──
    "agent": {
        # 指令樣板：{model}/{prompt} 帶入；可選 {args} 佔位插入 extra_args（{prompt} 保持單一參數）
        "build_cmd": "opencode run -m {model} {prompt}",
        # 額外固定 CLI 參數（如 ["--yolo"]）；template 無 {args} 佔位時，接在 {prompt} 之前
        "extra_args": [],
        "models": {
            "fast": "flash",  # 葉子執行（可校準）
            "normal": "",     # review／整合驗證（可校準）
            "thinking": "",   # 拆解／分析（可校準）
        },
        # ── 角色維預設指派（可校準） ──
        "roles": {
            "decompose": "thinking",
            "review": "normal",
            "integrate": "normal",
            "execute": "fast",
        },
        # 提示樣板（佔位：{control} {plan_md} {requirements}）。省略則用以下預設。
        "prompts": {
            "base": (
                "請讀取 {control}，依 .loop/rules/boot-sequence.md 的 BOOT SEQUENCE 開始工作"
                "（結束時做 STEP C 的提交）。"
                "本輪必讀：{control} 與 .loop/rules/boot-sequence.md；其餘 rules 按需讀。"
                "每輪務必回填 last_round_mode / last_round_result / last_round_fail_tasks。"
            ),
            "escalation": (
                "前幾輪偵測到反覆修壞（A↔B 震盪 / 卡在驗證）。請先判斷根因再動手："
                "(1) 實作疏漏（A、B 可同時滿足）→ 一次修對兩邊；"
                "(2) 規格矛盾（兩條規格本質衝突）→ 不要硬修，開 BLOCKING Issue 寫清楚衝突與出處，"
                "把涉及任務標 FROZEN，交人類裁決。判斷依據寫進 Issue/修正記錄。"
            ),
            "git_review": (
                "你正在執行 Loop Engineering 的【獨立 Git Review Gate】（全新 context，只審不寫 code）。\n"
                "目標：審查上一次的 Commit Diff 是否合理，並驗證核心狀態檔是否遭到破壞，防止 Agent 幻覺搞砸大腦。\n"
                "讀取：.loop/rules/git-review-gate.md 的檢查規則。\n"
                "輸入 Diff 如下：\n"
                "{diff_content}\n\n"
                "目前狀態檔的完整內容如下：\n"
                "{control_contents}\n\n"
                "請依據規則嚴格審查，並將最終判決寫入 `{result_file}` 檔案中\n"
                "（請直接覆寫該檔，內容只要一行 `[REVIEW: PASS]` 或 `[REVIEW: REVERT] <具體原因>` 或 `[REVIEW: FATAL_STATE] <具體原因>`）。\n"
                "寫檔完成後直接結束，不需執行 git commit。"
            ),
            "plan": (
                "你正在執行 Loop Engineering【階段②：生成/精修規劃書】（生成輪）。\n"
                "讀 {requirements} + 框架 rules（.loop/rules/ 的 BLUEPRINT、context-budget、"
                "state-model、convergence、completeness）。\n"
                "依 .loop/generators/1-plan-generator.md：(重新)獨立推導並產出/精修 "
                "{control} 等規劃書（loop.config.yaml + CONTROL.md + phases/*.md）。\n"
                "收斂迴圈：若已存在規劃書，請『先不看舊版、從需求獨立重推一份』再與現有比對；\n"
                "  僅在有『實質差異』時才修改檔案；無實質差異就不要動檔。\n"
                "把 {plan_md} 的 plan_changed_last 設 true（本輪有實質改動）/ false（無）。\n"
                "寫檔只允許 .loop/，禁止寫框架。結束 git add -A && git commit。\n"
                "（Plan Gate 由獨立的審查輪負責，你這輪不需自審。）"
            ),
            "plan_gate": (
                "你正在執行 Loop Engineering【階段②的獨立 Plan Gate】（全新 context，只審不生）。\n"
                "讀 {requirements} + .loop/ 的 loop.config.yaml / CONTROL.md / phases/*.md "
                "+ .loop/generators/2-plan-review-gate.md。\n"
                "逐項檢查 Gate（需求全覆蓋 / 任務粒度 / 無循環依賴 / 停止可判讀 / 收斂就位 / "
                "逃生門 / context 防爆 / 框架唯讀 / 引擎可讀 / 輪數估算）。\n"
                "❗只審查、不要修改任何規劃書檔（read-only verify）。\n"
                "把結果寫進 {plan_md}：plan_gate_last= PASS（全過）或 FAIL（未過項記到 plan.log）。\n"
                "結束 git add -A && git commit（理論上只有 {plan_md} 會變）。"
            ),
            # ── 漸進拆解（樹模式） ──
            "tree_decompose": (
                "你正在執行 Loop Engineering【規劃期：漸進拆解】。本輪只拆解一個節點。\n"
                "目標節點：{node_id}（工單見 {decomp_file}）。\n"
                "讀 {requirements} + 框架 rules（.loop/rules/ 的 BLUEPRINT、convergence、"
                "completeness、context-budget）。\n"
                "獨立重推：將此節點拆成子項，寫進 {decomp_file}。\n"
                "  - proposed_children: 逗號分隔的子項 ID（簡短 slug）\n"
                "  - 每個子項加 child_{{id}}_type = leaf（可獨立驗證的最小工作單位）或 pending（需進一步拆）\n"
                "  - 每個子項加 child_{{id}}_summary = 一句話描述\n"
                "收斂迴圈：若已有提議，先不看舊版、從需求獨立重推一份再比對；\n"
                "  僅在有實質差異時才修改；無差異就不動檔。\n"
                "把 decomp_changed_last 設 true（有改動）/ false（無）。\n"
                "寫檔只允許 {decomp_file}。結束 git add -A && git commit。"
            ),
            "tree_decompose_gate": (
                "你正在執行 Loop Engineering【規劃期：拆解審查】（全新 context，只審不生）。\n"
                "審查 {decomp_file} 中 {node_id} 的拆解結果。\n"
                "讀 {requirements} + .loop/rules/convergence.md + completeness.md。\n"
                "檢查：子項是否互不重疊、是否涵蓋父節點所有面向、\n"
                "  leaf 子項是否真的可獨立驗證且符合最小工作單位（≤ {max_files} 檔、≤ {max_lines} 行、"
                "單一關注點）。\n"
                "❗只審查、不修改拆解結果。\n"
                "把結果寫進 {decomp_file}：decomp_gate_last = PASS 或 FAIL。\n"
                "結束 git add -A && git commit。"
            ),
        },
    },
}


def _normalize_models(models: dict) -> dict:
    """單向相容：為支援舊版 (default/enhanced) 設定檔，自動轉為新鍵 (fast/normal/thinking)。"""
    m = dict(models)
    
    if m.get("default") and not m.get("fast"):
        m["fast"] = m.get("default")
    if m.get("enhanced") and not m.get("thinking"):
        m["thinking"] = m.get("enhanced")
        
    if not m.get("normal"):
        m["normal"] = m.get("enhanced") or m.get("default") or ""
        
    return m


_UPGRADE_CHAIN = ("fast", "normal", "thinking")


def select_model(cfg: dict, role: str, stuck_level: int = 0) -> str:
    """(角色 × stuck_level) 二維模型選擇。

    順風 (stuck_level=0) → roles[role] 指定的模型層。
    卡住 → 沿 fast→normal→thinking 往上爬。
    """
    models = cfg["agent"]["models"]
    roles = cfg["agent"].get("roles", {})
    base_key = roles.get(role, "normal")
    if stuck_level <= 0:
        return models.get(base_key) or ""
    try:
        idx = _UPGRADE_CHAIN.index(base_key)
    except ValueError:
        idx = 1
    upgraded_idx = min(idx + stuck_level, len(_UPGRADE_CHAIN) - 1)
    upgraded_key = _UPGRADE_CHAIN[upgraded_idx]
    return models.get(upgraded_key) or ""


def model_tier_label(cfg: dict, role: str, stuck_level: int = 0) -> str:
    """回傳人類可讀的模型層標籤，用於 log 顯示。

    順風 → 角色預設（如 "fast"）。
    卡住 → "base_key→upgraded_key"（如 "fast→normal"）。
    """
    roles = cfg["agent"].get("roles", {})
    base_key = roles.get(role, "normal")
    if stuck_level <= 0:
        return base_key
    try:
        idx = _UPGRADE_CHAIN.index(base_key)
    except ValueError:
        idx = 1
    upgraded_idx = min(idx + stuck_level, len(_UPGRADE_CHAIN) - 1)
    upgraded_key = _UPGRADE_CHAIN[upgraded_idx]
    if upgraded_key == base_key:
        return base_key  # 已在最高層，無處可升
    return f"{base_key}→{upgraded_key}"


def fmt_prompt(template: str, **kw) -> str:
    """提示樣板代入（用 replace 兼容舊版的 {key} 語法，避免內文花括號干擾 str.format）。"""
    out = template or ""
    for k, v in kw.items():
        out = out.replace("{" + k + "}", str(v))
    return out


def load_yaml(path: str) -> dict:
    path = os.path.expanduser(path)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        logger.error(f"Failed to load YAML {path}: {e}")
        return {}


def deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config() -> dict:
    """cascade：框架預設 < 專案 config。"""
    cfg = dict(DEFAULTS)
    project_path = os.environ.get("LOOP_CONFIG", "./loop.config.yaml")
    project = load_yaml(project_path)
    cfg = deep_merge(cfg, project)
    
    # 確保 agent 結構完整（缺的鍵用框架預設補；整段覆蓋也安全；同時避免回寫汙染 DEFAULTS）
    cfg["agent"] = deep_merge(DEFAULTS["agent"], cfg.get("agent", {}))

    # 雙向鏡射：確保 default/enhanced ↔ fast/normal/thinking 五鍵齊全
    cfg["agent"]["models"] = _normalize_models(cfg["agent"]["models"])
    return cfg

