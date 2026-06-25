#!/usr/bin/env python3
"""
loop.py — 通用 Loop Engineering 執行引擎（config 驅動、支援 N 階段）。

反覆觸發 coding agent 跑 CONTROL.md，偵測「改A壞B」震盪、自動三層升級模型（預設→增強→人類）。

與舊版差異（去專案化）：
  - 所有設定來自 cascade：框架預設 < 使用者 profile(~/.loop/profile.yaml) < 專案 config(.loop/loop.config.yaml) < 環境變數。
  - 不再寫死 phase==2 / CONTROL_FILES / codex；停止條件、受保護檔、模型指令全讀 config。
  - 支援任意 N 階段：最終階段 = config.phases 的最後一筆。
  - git 只作用於「工作區(code repo)」；framework_path（外部唯讀框架）絕不寫入。
  - log rotation：loop.log 超過上限就切檔（context-budget.md B）。

偵測原理（全在外部，不靠 agent 自述）：
  - 失敗指紋 = sha1( 排序(last_round_fail_tasks) + "|" + 排序(本輪 git 改動檔案) )
  - 只在「失敗的驗證輪」推進指紋歷史。
  - 震盪 = 最近 osc_window 輪的指紋只在 ≤osc_distinct_max 種間循環且有重複。
  - 卡住 = rounds_since_progress >= stall_threshold。

輸出：詳細 append 到單一 log；終端機只留心跳。有 pty 時用 pty 解決 CLI 緩衝問題。
"""

import os
import re
import sys
import time
import glob as globmod
import select
import signal
import shlex
import shutil
import hashlib
import argparse
import threading
import subprocess
from collections import deque, Counter
from datetime import datetime

try:
    import pty
    HAVE_PTY = True
except ImportError:           # Windows
    HAVE_PTY = False

try:                          # Windows 主控台 cp950 → 強制 UTF-8 輸出
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass


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


def fmt_prompt(template, **kw):
    """提示樣板代入（用 replace，避免內文花括號干擾 str.format）。"""
    out = template or ""
    for k, v in kw.items():
        out = out.replace("{" + k + "}", str(v))
    return out


# ─────────────── 多 workspace 支援（同一 code repo 內帶多份需求） ───────────────
def add_common_args(ap):
    """三支引擎共用的 CLI 參數：--workspace 選 .loop/<name>/、--quiet 關閉主控台直接輸出。"""
    ap.add_argument("--workspace", "-w", default=None,
                    help="選擇 .loop/<name>/ 這個 workspace（同 repo 帶多份需求時用；預設 default 或 $LOOP_WORKSPACE）")
    ap.add_argument("--quiet", "-q", action="store_true",
                    help="關閉主控台直接輸出 agent 詳細內容（仍會寫進 log 檔）；等同 LOOP_QUIET=1")
    return ap


def resolve_workspace(explicit=None):
    """決定本次跑哪個 workspace,並把 LOOP_CONFIG 設成 .loop/<name>/loop.config.yaml。
    若 LOOP_CONFIG 已被明確設定(進階用法/單一 workspace 舊式佈局),尊重之、不覆蓋。
    回傳 workspace name(供 lock 路徑、console 訊息使用)。"""
    name = explicit or os.environ.get("LOOP_WORKSPACE") or "default"
    if "LOOP_CONFIG" not in os.environ:
        os.environ["LOOP_CONFIG"] = os.path.join(".loop", name, "loop.config.yaml")
    return name


def apply_quiet_flag(quiet):
    if quiet:
        os.environ["LOOP_QUIET"] = "1"


def console_echo_enabled(cfg):
    if os.environ.get("LOOP_QUIET") == "1":
        return False
    return bool(cfg.get("runtime", {}).get("console_echo", True))


# ─────────────── 檔案鎖（同一 workspace 防重複啟動；同 repo 跨 workspace 序列化 git 操作） ───────────────
class WorkspaceBusy(Exception):
    pass


def acquire_run_lock(path, stale_seconds=3600):
    """獨佔鎖:同一 workspace 不可被兩個引擎程序同時跑(避免互踩 CONTROL/PLAN/git)。
    鎖檔超過 stale_seconds 視為前次異常結束留下的殘留,允許強制取得(不做跨平台 PID 存活檢查)。"""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    if os.path.exists(path):
        age = time.time() - os.path.getmtime(path)
        if age < stale_seconds:
            try:
                with open(path, encoding="utf-8") as f:
                    info = f.read().strip()
            except OSError:
                info = "?"
            raise WorkspaceBusy(
                f"此 workspace 已有執行中的程序佔用({info}；lock 存在 {int(age)}s)。"
                f"確定沒有其他程序在跑的話,刪除 {path} 後重試。")
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"pid={os.getpid()} started={datetime.now():%F %T}")
    return path


def release_run_lock(path):
    try:
        os.remove(path)
    except OSError:
        pass


def with_git_lock(cfg, fn, *args, timeout=30, **kwargs):
    """短暫獨佔鎖,序列化「git 變更工作區」的操作(git_guard/inspect_and_fix_blank)。
    鎖是 repo 層級(放 .loop/.git.lock,跨 workspace 共用),讓同一 repo 內多個 workspace
    並行跑時,git add/commit 不會互相踩到對方半成品。鎖只在做 git 操作這幾百毫秒內持有。"""
    lock_path = os.path.join(".loop", ".git.lock")
    os.makedirs(os.path.dirname(lock_path) or ".", exist_ok=True)
    deadline = time.monotonic() + timeout
    got = False
    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            got = True
            break
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(lock_path) > 120:  # 殘留鎖兜底
                    os.remove(lock_path)
                    continue
            except OSError:
                pass
            if time.monotonic() > deadline:
                break  # 等不到鎖:寧可冒險不鎖往下做,也不要永久卡死整輪
            time.sleep(0.5)
    try:
        return fn(*args, **kwargs)
    finally:
        if got:
            try:
                os.remove(lock_path)
            except OSError:
                pass


# ─────────────── 極簡 YAML 載入（優先 pyyaml，否則退化解析） ───────────────
def _coerce(v):
    s = v.strip()
    if s == "" or s == "~" or s.lower() == "null":
        return None
    if s.lower() in ("true", "false"):
        return s.lower() == "true"
    if (s[0], s[-1]) in (('"', '"'), ("'", "'")) and len(s) >= 2:
        return s[1:-1]
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s


def _strip_comment(line):
    # 去除非引號內的行內註解
    out, q = [], None
    for ch in line:
        if q:
            out.append(ch)
            if ch == q:
                q = None
        elif ch in ("'", '"'):
            q = ch
            out.append(ch)
        elif ch == "#":
            break
        else:
            out.append(ch)
    return "".join(out).rstrip()


def _parse_flow(s):
    s = s.strip()
    if s.startswith("{") and s.endswith("}"):
        d = {}
        for part in _split_top(s[1:-1]):
            if not part.strip():
                continue
            k, _, v = part.partition(":")
            d[k.strip()] = _coerce(v)
        return d
    if s.startswith("[") and s.endswith("]"):
        return [_coerce(x) for x in _split_top(s[1:-1]) if x.strip()]
    return _coerce(s)


def _split_top(s):
    """以頂層逗號切分（忽略 {}/[]/引號 內的逗號）。"""
    parts, depth, q, cur = [], 0, None, []
    for ch in s:
        if q:
            cur.append(ch)
            if ch == q:
                q = None
        elif ch in ("'", '"'):
            q = ch
            cur.append(ch)
        elif ch in "{[":
            depth += 1
            cur.append(ch)
        elif ch in "}]":
            depth -= 1
            cur.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    return parts


def _parse_block_by_actual(lines, idx):
    """以實際縮排層級解析（比固定 +1 穩健）。回傳 (value, next_idx)。"""
    if idx >= len(lines):
        return {}, idx
    base = lines[idx][0]
    if lines[idx][1].startswith("- "):
        result, i = [], idx
        while i < len(lines) and lines[i][0] == base and lines[i][1].startswith("- "):
            result.append(_parse_flow(lines[i][1][2:].strip()))
            i += 1
        return result, i
    result, i = {}, idx
    while i < len(lines) and lines[i][0] == base:
        key, _, val = lines[i][1].partition(":")
        key, val = key.strip(), val.strip()
        if val == "":
            if i + 1 < len(lines) and lines[i + 1][0] > base:
                child, i = _parse_block_by_actual(lines, i + 1)
                result[key] = child
            else:
                result[key] = {}
                i += 1
        else:
            result[key] = _parse_flow(val)
            i += 1
    return result, i


def load_yaml(path):
    path = os.path.expanduser(path)
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    try:
        import yaml
        return yaml.safe_load(text) or {}
    except ImportError:
        return _parse_block_by_actual(
            [(len(l) - len(l.lstrip(" ")), l.strip())
             for l in (_strip_comment(x) for x in text.splitlines()) if l.strip()],
            0,
        )[0]


def deep_merge(base, over):
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config():
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
            val = cast(os.environ[env])
            if sect:
                cfg.setdefault(sect, {})[key] = val
            else:
                cfg[key] = val

    # 確保 agent 結構完整（缺的鍵用框架預設補；整段覆蓋也安全；同時避免回寫汙染 DEFAULTS）
    cfg["agent"] = deep_merge(DEFAULTS["agent"], cfg.get("agent", {}))

    # env：模型覆蓋導向 agent.models
    if "DEFAULT_MODEL" in os.environ:
        cfg["agent"]["models"]["default"] = os.environ["DEFAULT_MODEL"]
    if "ENHANCED_MODEL" in os.environ:
        cfg["agent"]["models"]["enhanced"] = os.environ["ENHANCED_MODEL"]
    return cfg


# ─────────────── CONTROL 讀寫（單行，不載入 LLM context） ───────────────
def get_val(control, key):
    if not os.path.exists(control):
        return None
    pat = re.compile(rf"^\s*{re.escape(key)}\s*:\s*(.*?)\s*$")
    with open(control, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            m = pat.match(line)
            if m:
                return m.group(1).split("#", 1)[0].strip().strip('"')
    return None


def set_val(control, key, value):
    if not os.path.exists(control):
        return
    pat = re.compile(rf"^(\s*{re.escape(key)}\s*:\s*).*?(\s*(#.*)?)$")
    out, hit = [], False
    with open(control, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            m = pat.match(line.rstrip("\n"))
            if m and not hit:
                comment = m.group(3) or ""
                out.append(f"{m.group(1)}{value}  {comment}".rstrip() + "\n")
                hit = True
            else:
                out.append(line)
    if hit:
        with open(control, "w", encoding="utf-8") as f:
            f.writelines(out)


def as_int(v, d=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return d


# ─────────────── 完成 / 交人類 判斷（N 階段、config 驅動） ───────────────
def final_phase_id(cfg):
    phases = cfg.get("phases") or []
    if not phases:
        return None
    return phases[-1].get("id")


def is_done(cfg, control):
    sc = cfg["stop_condition"]
    if get_val(control, sc["done_flag"]) == "true":
        return True
    last = final_phase_id(cfg)
    if last is None:
        return False
    phase = get_val(control, "current_phase")
    if str(phase) == str(last) \
       and as_int(get_val(control, f"p{last}_consecutive_pass")) >= sc["final_phase_pass_gte"] \
       and as_int(get_val(control, sc["blocking_field"])) == sc["blocking_eq"]:
        return True
    return False


def human_needed(cfg, control):
    return get_val(control, cfg["stop_condition"]["human_flag"]) == "true"


# ─────────────── git 改動 + 安全網（只作用於工作區） ───────────────
def in_git_repo():
    if shutil.which("git") is None:
        return False
    try:
        return subprocess.run(["git", "rev-parse", "--is-inside-work-tree"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    except OSError:
        return False


def changed_files():
    if not in_git_repo():
        return []
    r = subprocess.run(["git", "diff", "--name-only", "HEAD~1", "HEAD"],
                       capture_output=True, text=True)
    return sorted([x for x in r.stdout.strip().splitlines() if x])


def expand_control_files(cfg):
    files = []
    for pat in cfg.get("control_files", []):
        matched = globmod.glob(pat)
        files.extend(matched if matched else [pat])
    return files


def control_file_looks_broken(path, min_bytes):
    if not os.path.exists(path):
        return False
    try:
        if os.path.getsize(path) < min_bytes:
            return True
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.strip():
                    return not line.lstrip().startswith("#")
        return True
    except OSError:
        return True


def inspect_and_fix_blank(cfg, log_both):
    """程式兜底：只還原『整檔被清空』的主控檔。內容級審查交給 agent BOOT STEP G0。"""
    if not in_git_repo():
        return
    min_bytes = cfg["runtime"]["control_min_bytes"]
    for cf in expand_control_files(cfg):
        if os.path.exists(cf) and control_file_looks_broken(cf, min_bytes):
            subprocess.run(["git", "checkout", "HEAD", "--", cf],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if control_file_looks_broken(cf, min_bytes):
                subprocess.run(["git", "checkout", "HEAD~1", "--", cf],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            log_both(f"  🩹 {cf} 整檔空白 → 已還原（程式兜底；內容級審查由 agent G0 負責）。")


def git_guard(cfg, round_no, log_both):
    if not in_git_repo():
        return
    min_bytes = cfg["runtime"]["control_min_bytes"]
    for cf in expand_control_files(cfg):
        if os.path.exists(cf) and control_file_looks_broken(cf, min_bytes):
            log_both(f"[guard] {cf} 疑似被清空 → 提交前先從 HEAD 還原")
            subprocess.run(["git", "checkout", "HEAD", "--", cf])
    if subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True).stdout.strip():
        log_both(f"[guard] 補一次安全 commit（round {round_no}）")
        subprocess.run(["git", "add", "-A"])
        subprocess.run(["git", "commit", "-m", f"loop-autocommit: round {round_no}"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ─────────────── 失敗指紋 + 震盪偵測 ───────────────
def fail_fingerprint(control):
    fails = get_val(control, "last_round_fail_tasks") or ""
    fails = ",".join(sorted([t.strip() for t in fails.split(",") if t.strip()]))
    files = "|".join(changed_files())
    return hashlib.sha1(f"{fails}||{files}".encode()).hexdigest()[:12]


def detect_oscillation(history, osc_window, osc_distinct_max):
    if len(history) < osc_window:
        return False
    window = list(history)[-osc_window:]
    counts = Counter(window)
    return len(counts) <= osc_distinct_max and max(counts.values()) >= 2


# ─────────────── log rotation（防硬碟，context-budget.md B） ───────────────
def rotate_log_if_needed(cfg):
    rt = cfg["runtime"]
    path = rt["log_file"]
    max_bytes = rt["log_rotate_max_mb"] * 1024 * 1024
    if not os.path.exists(path) or os.path.getsize(path) < max_bytes:
        return
    keep = rt["log_rotate_keep"]
    for i in range(keep - 1, 0, -1):
        src, dst = f"{path}.{i}", f"{path}.{i+1}"
        if os.path.exists(src):
            os.replace(src, dst)
    os.replace(path, f"{path}.1")


# ─────────────── 組指令（config.agent.build_cmd 樣板 + extra_args） ───────────────
def build_cmd(cfg, model, prompt):
    agent = cfg["agent"]
    template = agent.get("build_cmd") or "codex e --model {model} {prompt}"
    extra = [str(a) for a in (agent.get("extra_args") or [])]
    tokens = shlex.split(template)
    has_args_ph = "{args}" in tokens
    has_prompt_ph = any("{prompt}" in t for t in tokens)
    out, emitted_extra = [], False
    for t in tokens:
        if t == "{args}":
            out.extend(extra)
            emitted_extra = True
        elif t == "{prompt}":
            if not has_args_ph:          # 無 {args} 佔位 → extra_args 接在 prompt 之前
                out.extend(extra)
                emitted_extra = True
            out.append(prompt)
        elif "{model}" in t:
            out.append(t.replace("{model}", model))
        elif "{prompt}" in t:
            out.append(t.replace("{prompt}", prompt))
        else:
            out.append(t)
    if not has_prompt_ph:                 # 樣板沒寫 {prompt} → prompt 一定要帶上（接最後），不可遺漏
        if not has_args_ph and not emitted_extra:
            out.extend(extra)
        out.append(prompt)
    return out


# ─────────────── 跑一輪（pty 或後備 pipe；含 watchdog 逾時/閒置） ───────────────
def run_agent(cmd, cfg):
    rt = cfg["runtime"]
    round_timeout = rt["round_timeout_seconds"]
    idle_timeout = rt["idle_timeout_seconds"]
    log_path = rt["log_file"]
    echo = console_echo_enabled(cfg)

    if HAVE_PTY:
        return _run_agent_pty(cmd, log_path, round_timeout, idle_timeout, echo)
    return _run_agent_pipe(cmd, log_path, round_timeout, idle_timeout, echo)


def _run_agent_pty(cmd, log_path, round_timeout, idle_timeout, echo=True):
    log = open(log_path, "ab")
    pid, fd = pty.fork()
    if pid == 0:
        try:
            os.setsid()
        except OSError:
            pass
        try:
            os.execvp(cmd[0], cmd)
        except FileNotFoundError:
            os.write(2, f"找不到指令：{cmd[0]}\n".encode())
            os._exit(127)

    start = last_output = time.monotonic()
    killed = None

    def kill_group(sig):
        try:
            os.killpg(pid, sig)
        except (ProcessLookupError, OSError):
            try:
                os.kill(pid, sig)
            except (ProcessLookupError, OSError):
                pass

    try:
        while True:
            try:
                if os.waitpid(pid, os.WNOHANG)[0] == pid:
                    break
            except ChildProcessError:
                break
            r, _, _ = select.select([fd], [], [], 1.0)
            now = time.monotonic()
            if fd in r:
                try:
                    data = os.read(fd, 4096)
                except OSError:
                    data = b""
                if data:
                    log.write(data)
                    log.flush()
                    if echo:
                        sys.stdout.buffer.write(data)
                        sys.stdout.flush()
                    last_output = now
            if round_timeout and (now - start) > round_timeout:
                killed = "timeout"
                break
            if idle_timeout and (now - last_output) > idle_timeout:
                killed = "idle"
                break
        if killed:
            kill_group(signal.SIGTERM)
            time.sleep(5)
            try:
                os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                pass
            kill_group(signal.SIGKILL)
    finally:
        log.close()

    try:
        _, status = os.waitpid(pid, 0)
        rc = os.waitstatus_to_exitcode(status)
    except ChildProcessError:
        rc = -1
    return rc, killed


def _run_agent_pipe(cmd, log_path, round_timeout, idle_timeout, echo=True):
    """無 pty 後備（Windows）：用背景執行緒讀取子程序輸出,同時寫 log 與(可選)主控台,
    並精準量測閒置時間(取代舊版用 log 檔 mtime 推估的近似值)。"""
    log = open(log_path, "ab")
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0)
    except FileNotFoundError:
        log.write(f"找不到指令：{cmd[0]}\n".encode())
        log.close()
        return 127, None

    state = {"last": time.monotonic()}

    def reader():
        try:
            while True:
                chunk = proc.stdout.read(4096)
                if not chunk:
                    break
                log.write(chunk)
                log.flush()
                if echo:
                    sys.stdout.buffer.write(chunk)
                    sys.stdout.flush()
                state["last"] = time.monotonic()
        except (OSError, ValueError):
            pass

    t = threading.Thread(target=reader, daemon=True)
    t.start()

    killed = None
    start = time.monotonic()
    try:
        while True:
            rc = proc.poll()
            if rc is not None:
                t.join(timeout=2)
                return rc, None
            now = time.monotonic()
            if round_timeout and (now - start) > round_timeout:
                killed = "timeout"
            elif idle_timeout and (now - state["last"]) > idle_timeout:
                killed = "idle"
            if killed:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                t.join(timeout=2)
                return (proc.returncode if proc.returncode is not None else -1), killed
            time.sleep(1.0)
    finally:
        log.close()


# ─────────────── 開跑前健檢（preflight） ───────────────
def _is_placeholder(v):
    return (not v) or ("<" in str(v) and ">" in str(v))


def preflight(cfg, stage):
    """開跑前健檢。stage ∈ {'plan','execute'}。回傳 (errors, warnings);errors 非空應中止。"""
    errors, warnings = [], []
    fw = os.path.expanduser(cfg.get("framework_path", ""))
    if not fw or not os.path.isdir(fw):
        errors.append(f"framework_path 不存在或非目錄：{fw}")
    elif not os.path.isfile(os.path.join(fw, "rules", "boot-sequence.md")):
        warnings.append(f"framework_path 看起來不像框架（缺 rules/boot-sequence.md）：{fw}")

    agent = cfg.get("agent", {})
    models = agent.get("models", {})
    for k in ("default", "enhanced"):
        if _is_placeholder(models.get(k)):
            errors.append(f"agent.models.{k} 仍是佔位值，請在 ~/.loop/profile.yaml 或 config 填入實際模型。")
    bc = agent.get("build_cmd") or ""
    exe = shlex.split(bc)[0] if bc.strip() else ""
    if exe and not exe.startswith("{") and shutil.which(exe) is None:
        warnings.append(f"build_cmd 的執行檔在 PATH 找不到（'{exe}'）：{bc}")

    if not in_git_repo():
        warnings.append("當前目錄不是 git repo（工作區需要 git 安全網；建議 git init）。")
    if not cfg.get("phases"):
        (errors if stage == "execute" else warnings).append("config 沒有 phases 定義。")

    loop_dir = os.path.dirname(cfg.get("control", "")) or "."
    req = os.path.join(loop_dir, "REQUIREMENTS.md")
    if stage == "plan" and not os.path.exists(req):
        errors.append(f"找不到 {req}（請先完成階段①需求）。")
    if stage == "execute" and not os.path.exists(cfg.get("control", "")):
        errors.append(f"找不到 {cfg.get('control')}（請先完成階段②生成規劃書）。")
    return errors, warnings


def report_preflight(cfg, stage, emit):
    """印出健檢結果;回傳 True=可繼續(無 error)。"""
    errors, warnings = preflight(cfg, stage)
    for w in warnings:
        emit(f"  ⚠️  {w}")
    for e in errors:
        emit(f"  ❌ {e}")
    if errors:
        emit(f"  ✋ preflight 有 {len(errors)} 個錯誤,請修正後再跑（stage={stage}）。")
    return not errors


# ─────────────── 震盪歷史持久化（重啟接續，不歸零） ───────────────
def fail_history_path(cfg):
    return os.path.join(cfg["runtime"]["state_dir"], "fail_history")


def load_fail_history(cfg, maxlen):
    dq = deque(maxlen=maxlen)
    p = fail_history_path(cfg)
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    dq.append(line)
    return dq


def save_fail_history(cfg, dq):
    p = fail_history_path(cfg)
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(dq) + ("\n" if dq else ""))


# ─────────────── 跨專案總覽（~/.loop/index.md 自動 upsert） ───────────────
def update_index(cfg, status):
    """以(repo 絕對路徑, workspace 名稱)為 key,upsert 一行到 index。
    context-cheap:只存索引,不存內文。同一 repo 可有多個 workspace(多份需求)各佔一行。"""
    try:
        idx = os.path.expanduser(cfg.get("index") or "~/.loop/index.md")
        os.makedirs(os.path.dirname(idx) or ".", exist_ok=True)
        repo = os.path.abspath(".")
        name = os.path.basename(repo)
        ws = cfg.get("_workspace") or "-"
        control = cfg.get("control", "")
        has_ctl = bool(control) and os.path.exists(control)
        phase = get_val(control, "current_phase") if has_ctl else "-"
        stuck = get_val(control, "stuck_level") if has_ctl else "-"
        ts = datetime.now().strftime("%F %T")
        key = f"| {repo} | {ws} |"
        row = f"| {name} | {repo} | {ws} | {phase or '-'} | {stuck or '-'} | {status} | {ts} |"
        header = ["# Loop 專案總覽（自動維護）", "",
                  "| 專案 | repo | workspace | phase | stuck | 狀態 | 更新 |",
                  "|------|------|-----------|-------|-------|------|------|"]
        body = []
        if os.path.exists(idx):
            with open(idx, encoding="utf-8") as f:
                for line in f:
                    line = line.rstrip("\n")
                    if not line.startswith("| "):
                        continue
                    if line.startswith("| 專案 ") or set(line) <= set("|-: "):
                        continue
                    if key in line:
                        continue  # 移除同 (repo, workspace) 舊行
                    body.append(line)
        body.append(row)
        with open(idx, "w", encoding="utf-8") as f:
            f.write("\n".join(header + body) + "\n")
    except OSError:
        pass


# ─────────────── 主迴圈 ───────────────
def main():
    ap = argparse.ArgumentParser(description="階段③:執行收斂迴圈")
    add_common_args(ap)
    args = ap.parse_args()
    apply_quiet_flag(args.quiet)
    ws = resolve_workspace(args.workspace)

    cfg = load_config()
    cfg["_workspace"] = ws
    rc = _run_execute(cfg)
    status = {0: "done", 1: "stopped", 2: "human_required"}.get(rc, "stopped")
    update_index(cfg, status)
    return rc


def _run_execute(cfg):
    lock_path = os.path.join(cfg["runtime"]["state_dir"], "run.lock")
    try:
        acquire_run_lock(lock_path)
    except WorkspaceBusy as e:
        print(f"✋ {e}", flush=True)
        return 1
    try:
        return _run_execute_locked(cfg)
    finally:
        release_run_lock(lock_path)


def _run_execute_locked(cfg):
    rt = cfg["runtime"]
    control = cfg["control"]
    osc = cfg["oscillation"]
    log_path = rt["log_file"]

    def hb(msg=""):
        print(msg, flush=True)

    def log_line(msg=""):
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(msg + "\n")

    def log_both(msg=""):
        hb(msg)
        log_line(msg)

    os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
    if not report_preflight(cfg, "execute", log_both):
        return 1

    log_line("")
    log_line(f"########## LOOP 啟動 {datetime.now():%F %T} ##########")
    hb(f"Loop 啟動。框架={cfg['framework_path']}  詳細輸出：{log_path}（tail -f 觀看）\n")

    # 把框架 commit 快照寫進 CONTROL（供追溯）
    fw = cfg["framework_path"]
    if os.path.isdir(fw) and shutil.which("git"):
        try:
            r = subprocess.run(["git", "-C", fw, "rev-parse", "--short", "HEAD"],
                               capture_output=True, text=True)
            if r.returncode == 0 and r.stdout.strip():
                set_val(control, "framework_ref", r.stdout.strip())
        except OSError:
            pass

    prompts = cfg["agent"]["prompts"]
    base_prompt = fmt_prompt(prompts.get("base"), control=control, framework=fw)
    escalation_prompt = fmt_prompt(prompts.get("escalation"), control=control, framework=fw)

    state_dir = rt["state_dir"]
    os.makedirs(state_dir, exist_ok=True)
    fail_history = load_fail_history(cfg, osc["osc_window"])  # 持久化：重啟接續，不歸零
    if fail_history:
        log_both(f"  ↺ 從 .loop_state 接續震盪歷史（{len(fail_history)} 筆）。")
    prev_pass = None

    for i in range(1, rt["max_rounds"] + 1):
        rotate_log_if_needed(cfg)
        with_git_lock(cfg, inspect_and_fix_blank, cfg, log_both)

        if os.path.exists(control):
            if is_done(cfg, control):
                log_both(f"✅ 停止條件成立，於第 {i-1} 輪後完成。LOOP COMPLETE")
                return 0
            if human_needed(cfg, control):
                log_both("🧑‍⚖️ 偵測到 human_required：已凍結互卡任務，需你介入裁決。loop 停止。")
                return 2

        tier = get_val(control, "current_model_tier") or "default"
        models = cfg["agent"]["models"]
        model = models["enhanced"] if tier == "enhanced" else models["default"]
        prompt = base_prompt + ("\n" + escalation_prompt if tier == "enhanced" else "")
        cmd = build_cmd(cfg, model, prompt)

        ts = datetime.now().strftime("%F %T")
        hb(f"▶ Round {i} 開始  ({ts})  模型階層={tier}")
        log_line(f"\n════════════ Round {i}  ({ts})  tier={tier} model={model} ════════════")

        rc, killed = run_agent(cmd, cfg)
        if killed:
            hb(f"  Round {i} 被 watchdog 中斷（{killed}），清理後重跑下一輪。")
            with_git_lock(cfg, git_guard, cfg, i, log_both)
            set_val(control, "last_round_result", "NA")
            set_val(control, "last_round_mode", "中斷")
            time.sleep(rt["interval_seconds"])
            continue
        hb(f"  Round {i} 結束 (rc={rc})")
        with_git_lock(cfg, git_guard, cfg, i, log_both)

        # 讀本輪結果，更新震盪偵測
        phase = get_val(control, "current_phase")
        cur_pass = as_int(get_val(control, f"p{phase}_consecutive_pass"))
        mode = get_val(control, "last_round_mode") or ""
        result = get_val(control, "last_round_result") or ""
        progressed = (prev_pass is not None and cur_pass > prev_pass)

        is_fail_verify = ("驗證" in mode) and (result == "FAIL")
        stuck_level = as_int(get_val(control, "stuck_level"))
        rounds_since = as_int(get_val(control, "rounds_since_progress"))
        enhanced_used = as_int(get_val(control, "enhanced_rounds_used"))

        if progressed:
            rounds_since = 0
            fail_history.clear()
            save_fail_history(cfg, fail_history)
            if stuck_level != 0:
                log_both("  ↩ 有進展，stuck 解除、換回預設模型。")
            stuck_level, enhanced_used = 0, 0
            set_val(control, "current_model_tier", "default")
            set_val(control, "human_required", "false")
        elif is_fail_verify:
            rounds_since += 1
            fail_history.append(fail_fingerprint(control))
            save_fail_history(cfg, fail_history)
            if stuck_level == 1:
                enhanced_used += 1

        oscillating = detect_oscillation(fail_history, osc["osc_window"], osc["osc_distinct_max"])
        if stuck_level == 0 and (oscillating or rounds_since >= osc["stall_threshold"]):
            stuck_level = 1
            set_val(control, "current_model_tier", "enhanced")
            enhanced_used = 0
            why = "震盪 A↔B" if oscillating else f"連續 {rounds_since} 輪無進展"
            log_both(f"  ⬆ 偵測到卡住（{why}）→ 換【增強模型】重試。")
        elif stuck_level == 1 and enhanced_used >= osc["enhanced_max_rounds"]:
            stuck_level = 2
            log_both(f"  ⬆⬆ 增強模型試了 {enhanced_used} 輪仍卡 → 升級【人類】。"
                     f" 下一輪請 agent 開 BLOCKING Issue 並凍結互卡任務。")
        elif stuck_level == 2 and rounds_since >= (osc["stall_threshold"] + osc["human_stop_after"]):
            log_both("  ⛔ 升級人類後仍無進展（硬性保險觸發）→ 停下交人類。")
            set_val(control, "stuck_level", "2")
            set_val(control, "rounds_since_progress", str(rounds_since))
            return 2

        set_val(control, "rounds_since_progress", str(rounds_since))
        set_val(control, "stuck_level", str(stuck_level))
        set_val(control, "enhanced_rounds_used", str(enhanced_used))
        prev_pass = cur_pass

        time.sleep(rt["interval_seconds"])

    log_both(f"⛔ 已達 max_rounds={rt['max_rounds']}，停止（尚未完成，請檢查 {control}）。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
