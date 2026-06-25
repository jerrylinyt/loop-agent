import os
import logging
import yaml

logger = logging.getLogger(__name__)

# ─────────────── 框架預設（cascade 最底層） ───────────────
DEFAULTS = {
    "framework_path": os.path.expanduser("~/.loop/framework"),
    "profile": os.path.expanduser("~/.loop/profile.yaml"),
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
    "runtime": {
        "max_rounds": 600,
        "interval_seconds": 30,
        "round_timeout_seconds": 1800,
        "idle_timeout_seconds": 300,
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
        "build_cmd": "codex e --model {model} {prompt}",
        # 額外固定 CLI 參數（如 ["--yolo"]）；template 無 {args} 佔位時，接在 {prompt} 之前
        "extra_args": [],
        "models": {
            "default": "<你的預設模型>",
            "enhanced": "<你的增強模型>",     # 卡住時切換的更強模型
        },
        # 提示樣板（佔位：{control} {framework} {plan_md} {requirements}）。省略則用以下預設。
        "prompts": {
            "base": (
                "請讀取 {control}，依 {framework}/rules/boot-sequence.md 的 BOOT SEQUENCE 開始工作"
                "（先做 STEP G 的 Git 自檢、結束做 STEP C 的提交）。"
                "本輪必讀：{control} 與 {framework}/rules/boot-sequence.md；其餘 rules 按需讀。"
                "每輪務必回填 last_round_mode / last_round_result / last_round_fail_tasks。"
            ),
            "escalation": (
                "前幾輪偵測到反覆修壞（A↔B 震盪 / 卡在驗證）。請先判斷根因再動手："
                "(1) 實作疏漏（A、B 可同時滿足）→ 一次修對兩邊；"
                "(2) 規格矛盾（兩條規格本質衝突）→ 不要硬修，開 BLOCKING Issue 寫清楚衝突與出處，"
                "把涉及任務標 FROZEN，交人類裁決。判斷依據寫進 Issue/修正記錄。"
            ),
            "plan": (
                "你正在執行 Loop Engineering【階段②：生成/精修規劃書】（生成輪）。\n"
                "讀 {requirements} + 框架 rules（{framework}/rules/ 的 BLUEPRINT、context-budget、"
                "state-model、convergence、completeness）。\n"
                "依 {framework}/generators/1-plan-generator.md：(重新)獨立推導並產出/精修 "
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
                "+ {framework}/generators/2-plan-review-gate.md。\n"
                "逐項檢查 Gate（需求全覆蓋 / 任務粒度 / 無循環依賴 / 停止可判讀 / 收斂就位 / "
                "逃生門 / context 防爆 / 框架唯讀 / 引擎可讀 / 輪數估算）。\n"
                "❗只審查、不要修改任何規劃書檔（read-only verify）。\n"
                "把結果寫進 {plan_md}：plan_gate_last= PASS（全過）或 FAIL（未過項記到 plan.log）。\n"
                "結束 git add -A && git commit（理論上只有 {plan_md} 會變）。"
            ),
        },
    },
}


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
    """cascade：框架預設 < profile < 專案 config < 環境變數。"""
    cfg = dict(DEFAULTS)
    project_path = os.environ.get("LOOP_CONFIG", "./loop.config.yaml")
    project = load_yaml(project_path)
    # profile 路徑可被專案 config 指定
    profile_path = project.get("profile") or os.environ.get("LOOP_PROFILE") or cfg["profile"]
    profile = load_yaml(profile_path)
    cfg = deep_merge(cfg, profile)
    cfg = deep_merge(cfg, project)
    
    # 環境變數覆蓋（與舊版相容的少數常用旗標）
    env_map = {
        "MAX_ROUNDS": ("runtime", "max_rounds", int),
        "INTERVAL": ("runtime", "interval_seconds", int),
        "LOG_FILE": ("runtime", "log_file", str),
        "ROUND_TIMEOUT": ("runtime", "round_timeout_seconds", int),
        "IDLE_TIMEOUT": ("runtime", "idle_timeout_seconds", int),
        "CONTROL": (None, "control", str),
        # DEFAULT_MODEL / ENHANCED_MODEL 在下方明確導向 agent.models
    }
    for env, (sect, key, cast) in env_map.items():
        if env in os.environ:
            try:
                val = cast(os.environ[env])
                if sect:
                    cfg.setdefault(sect, {})[key] = val
                else:
                    cfg[key] = val
            except ValueError:
                logger.warning(f"Invalid environment variable format for {env}: {os.environ[env]}")

    # 確保 agent 結構完整（缺的鍵用框架預設補；整段覆蓋也安全；同時避免回寫汙染 DEFAULTS）
    cfg["agent"] = deep_merge(DEFAULTS["agent"], cfg.get("agent", {}))

    # env：模型覆蓋導向 agent.models
    if "DEFAULT_MODEL" in os.environ:
        cfg["agent"]["models"]["default"] = os.environ["DEFAULT_MODEL"]
    if "ENHANCED_MODEL" in os.environ:
        cfg["agent"]["models"]["enhanced"] = os.environ["ENHANCED_MODEL"]
    return cfg

