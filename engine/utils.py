import os
import time
import argparse
import subprocess
import shutil
import hashlib
import logging
from collections import Counter
from datetime import datetime

from git_utils import in_git_repo, changed_files
from state import get_val, as_int

logger = logging.getLogger(__name__)

# ─────────────── 單一啟動鎖 ───────────────
class WorkspaceBusy(Exception):
    pass


def lock_stale_seconds(cfg: dict) -> int:
    """殘留鎖門檻:取『幾個 round_timeout』為基準（搭配心跳,正常跑的鎖不會到此）。"""
    rt = cfg.get("runtime", {})
    return max(3600, 3 * int(rt.get("round_timeout_seconds", 1800) or 1800))


def acquire_run_lock(path: str, stale_seconds: int = 3600) -> str:
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
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"pid={os.getpid()} started={datetime.now():%F %T}")
    except OSError as e:
        logger.error(f"Failed to acquire run lock {path}: {e}")
    return path


def release_run_lock(path: str):
    try:
        os.remove(path)
    except OSError:
        pass


def touch_run_lock(path: str):
    try:
        os.utime(path, None)
    except OSError:
        pass


# ─────────────── CLI 共用參數與 Workspace ───────────────
def add_common_args(ap: argparse.ArgumentParser) -> argparse.ArgumentParser:
    ap.add_argument("--workspace", "-w", default=None,
                    help="選擇 .loop/<name>/ 這個 workspace（預設 default 或 $LOOP_WORKSPACE）")
    ap.add_argument("--quiet", "-q", action="store_true",
                    help="關閉主控台直接輸出 agent 詳細內容（等同 LOOP_QUIET=1）")
    return ap


def resolve_workspace(explicit: str | None = None) -> str:
    name = explicit or os.environ.get("LOOP_WORKSPACE") or "default"
    if "LOOP_CONFIG" not in os.environ:
        os.environ["LOOP_CONFIG"] = os.path.join(".loop", name, "loop.config.yaml")
    return name


def apply_quiet_flag(quiet: bool):
    if quiet:
        os.environ["LOOP_QUIET"] = "1"


# ─────────────── Log Rotation ───────────────
def rotate_log_if_needed(cfg: dict):
    rt = cfg["runtime"]
    path = rt["log_file"]
    max_bytes = rt["log_rotate_max_mb"] * 1024 * 1024
    if not os.path.exists(path) or os.path.getsize(path) < max_bytes:
        return
    keep = rt["log_rotate_keep"]
    try:
        for i in range(keep - 1, 0, -1):
            src, dst = f"{path}.{i}", f"{path}.{i+1}"
            if os.path.exists(src):
                os.replace(src, dst)
        os.replace(path, f"{path}.1")
    except OSError as e:
        logger.warning(f"Failed to rotate log: {e}")


# ─────────────── 跨專案總覽 (Index) ───────────────
def update_index(cfg: dict, status: str):
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
    except OSError as e:
        logger.warning(f"Failed to update index: {e}")


# ─────────────── 開跑前健檢 (Preflight) ───────────────
def _is_placeholder(v) -> bool:
    return (not v) or ("<" in str(v) and ">" in str(v))


def preflight(cfg: dict, stage: str) -> tuple[list[str], list[str]]:
    errors, warnings = [], []
    fw = os.path.expanduser(cfg.get("framework_path", ""))
    if not fw or not os.path.isdir(fw):
        errors.append(f"framework_path 不存在或非目錄：{fw}")
    elif not os.path.isfile(os.path.join(fw, "rules", "boot-sequence.md")):
        warnings.append(f"framework_path 看起來不像框架（缺 rules/boot-sequence.md）：{fw}")

    agent = cfg.get("agent", {})
    models = agent.get("models", {})
    for k in ("fast", "normal", "thinking"):
        if _is_placeholder(models.get(k)):
            errors.append(f"agent.models.{k} 仍是佔位值，請在專案 config (loop.config.yaml) 填入實際模型。")

    # prompts 由框架 engine/prompts.yaml 提供（cascade 最底層）；缺檔或空白 → agent 收到空指令會空轉
    prompts = agent.get("prompts", {}) or {}
    missing_prompts = [k for k in ("base", "escalation", "git_review", "plan", "plan_gate",
                                   "tree_decompose", "tree_decompose_gate")
                       if not str(prompts.get(k) or "").strip()]
    if missing_prompts:
        errors.append(f"agent.prompts 缺少或空白：{', '.join(missing_prompts)}"
                      f"（應由框架 engine/prompts.yaml 提供，請確認該檔存在且完整）。")

    import shlex
    bc = agent.get("build_cmd") or ""
    exe = shlex.split(bc)[0] if bc.strip() else ""
    if exe and not exe.startswith("{") and shutil.which(exe) is None:
        warnings.append(f"build_cmd 的執行檔在 PATH 找不到（'{exe}'）：{bc}")

    if not in_git_repo():
        warnings.append("當前目錄不是 git repo（工作區需要 git 安全網；建議 git init）。")
    else:
        email = subprocess.run(["git", "config", "user.email"], capture_output=True, text=True)
        if not email.stdout.strip():
            warnings.append("git 沒設定 user.email/user.name → 每輪安全 commit 會無聲失敗、失去還原點。請 git config user.email/user.name。")
            
    if not cfg.get("phases"):
        (errors if stage == "execute" else warnings).append("config 沒有 phases 定義。")

    loop_dir = os.path.dirname(cfg.get("control", "")) or "."
    req = os.path.join(loop_dir, "REQUIREMENTS.md")
    if stage == "plan" and not os.path.exists(req):
        errors.append(f"找不到 {req}（請先完成階段①需求）。")
    if stage == "execute" and not os.path.exists(cfg.get("control", "")):
        errors.append(f"找不到 {cfg.get('control')}（請先完成階段②生成規劃書）。")
    return errors, warnings


def report_preflight(cfg: dict, stage: str, emit) -> bool:
    errors, warnings = preflight(cfg, stage)
    for w in warnings:
        emit(f"  ⚠️  {w}")
    for e in errors:
        emit(f"  ❌ {e}")
    if errors:
        emit(f"  ✋ preflight 有 {len(errors)} 個錯誤,請修正後再跑（stage={stage}）。")
    return not errors


def sync_framework_docs(cfg: dict, log_fn):
    """將框架的 rules/ 與 generators/ 目錄自動同步至專案內的 .loop/ 目錄，並在異動時 commit。"""
    fw_path = cfg.get("framework_path")
    if not fw_path or not os.path.exists(fw_path):
        return
        
    loop_dir = ".loop"
    os.makedirs(loop_dir, exist_ok=True)
    
    for d in ["rules", "generators"]:
        src = os.path.join(fw_path, d)
        dst = os.path.join(loop_dir, d)
        if os.path.exists(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)
            
    # 確認是否有異動
    res = subprocess.run(["git", "status", "--porcelain", ".loop/rules", ".loop/generators"], 
                         capture_output=True, text=True)
    if res.stdout.strip():
        subprocess.run(["git", "add", ".loop/rules", ".loop/generators"])
        subprocess.run(["git", "commit", "-m", "chore: sync updated loop framework docs"])
        if log_fn:
            log_fn("  🔄 自動同步最新框架文件至 .loop/ 並已 Commit。")


# ─────────────── 失敗指紋與震盪偵測 ───────────────
def fail_fingerprint(control: str) -> str:
    fails = get_val(control, "last_round_fail_tasks") or ""
    fails = ",".join(sorted([t.strip() for t in fails.split(",") if t.strip()]))
    files = "|".join(changed_files())
    return hashlib.sha1(f"{fails}||{files}".encode()).hexdigest()[:12]


def detect_oscillation(history: list | set, osc_window: int, osc_distinct_max: int) -> bool:
    if len(history) < osc_window:
        return False
    window = list(history)[-osc_window:]
    counts = Counter(window)
    return len(counts) <= osc_distinct_max and max(counts.values()) >= 2


# ─────────────── 停止條件 ───────────────
def final_phase_id(cfg: dict) -> str | None:
    phases = cfg.get("phases") or []
    if not phases:
        return None
    return phases[-1].get("id")


def is_done(cfg: dict, control: str) -> bool:
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


def human_needed(cfg: dict, control: str) -> bool:
    return get_val(control, cfg["stop_condition"]["human_flag"]) == "true"
