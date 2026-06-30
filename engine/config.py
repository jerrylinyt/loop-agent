import os
import logging
import yaml

logger = logging.getLogger(__name__)


def _load_default_prompts() -> dict:
    """從框架側 engine/prompts.yaml 載入 agent prompts（cascade 最底層）。
    prompt 只負責「本輪做什麼 + 讀哪份 rule + 產出/commit」；收斂/停止等方法論一律由 rules 承接（單一事實來源）。
    缺檔回傳 {}，由 preflight 擋下並給清楚訊息（見 utils.preflight）。"""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts.yaml")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        logger.error(f"prompts.yaml 不存在：{path}")
        return {}
    except Exception as e:
        logger.error(f"載入 prompts.yaml 失敗：{e}")
        return {}


# ─────────────── 框架預設（cascade 最底層） ───────────────
DEFAULTS = {
    "framework_path": os.path.expanduser("~/.loop/framework"),
    "index": os.path.expanduser("~/.loop/index.md"),   # 跨專案總覽（自動維護）
    "control": "state.json",
    "control_files": ["state.json", "phases/*.md"],
    "workspace": {"mode": "in_repo"},
    # ── 生成階段（階段②：plan_loop.py 規劃書收斂）。專案 config 只需覆寫 mode 與 per-workspace log_file ──
    "generation": {
        "mode": "gated",                # gated（收斂停下交人 review）/ auto（自動接執行）
        "plan_converge_threshold": 2,   # 連續幾個 cycle「無實質變更且 Plan Gate PASS」才算收斂
        "max_rounds": 30,
        "interval_seconds": 10,
        "log_file": "./.loop/plan.log", # 專案用 {{LOOP_DIR}} 覆寫成 per-workspace 路徑
    },
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
    # min_unit and breaker config removed
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
            "fast": "flash",
            "normal": "",
            "thinking": "",
        },
        # ── 角色維預設指派（可校準） ──
        "roles": {
            "plan": "thinking",
            "review": "normal",
            "execute": "fast",
        },
        # 提示樣板：外部化到 engine/prompts.yaml（框架預設層）。
        # prompt 只負責「本輪做什麼 + 讀哪份 rule + 產出/commit」，方法論交給 rules（單一事實來源）。
        # 專案可用 loop.config.yaml 的 agent.prompts.<key> 覆蓋單一 prompt。
        "prompts": _load_default_prompts(),
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
    if "state_cli" not in kw:
        control = kw.get("control", "state.json")
        base_dir = os.path.dirname(os.path.abspath(control)) if control else os.path.abspath(".")
        state_json_path = os.path.join(base_dir, "state.json")
        state_py_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.py")
        kw["state_cli"] = f"python {state_py_path} --state {state_json_path}"

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

