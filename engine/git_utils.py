import os
import glob
import subprocess
import logging
import shutil

logger = logging.getLogger(__name__)

def in_git_repo() -> bool:
    if shutil.which("git") is None:
        return False
    try:
        return subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        ).returncode == 0
    except OSError:
        return False


def changed_files() -> list[str]:
    if not in_git_repo():
        return []
    try:
        r = subprocess.run(["git", "diff", "--name-only", "HEAD~1", "HEAD"],
                           capture_output=True, text=True)
        return sorted([x for x in r.stdout.strip().splitlines() if x])
    except OSError as e:
        logger.warning(f"Failed to get changed files: {e}")
        return []


def git_head() -> str:
    """目前 HEAD commit hash(無 git/無 commit 回 '')。供『無活動偵測』判斷 agent 本輪有沒有真的提交。"""
    if not in_git_repo():
        return ""
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else ""
    except OSError as e:
        logger.warning(f"Failed to get git head: {e}")
        return ""


def expand_control_files(cfg: dict) -> list[str]:
    files = []
    for pat in cfg.get("control_files", []):
        matched = glob.glob(pat)
        files.extend(matched if matched else [pat])
    return files


def control_file_looks_broken(path: str, min_bytes: int) -> bool:
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
    except OSError as e:
        logger.warning(f"Error checking if control file is broken {path}: {e}")
        return True


def inspect_and_fix_blank(cfg: dict, log_both):
    """程式兜底：只還原『整檔被清空』的主控檔。內容級審查交給 agent BOOT STEP G0。"""
    if not in_git_repo():
        return
    min_bytes = cfg["runtime"]["control_min_bytes"]
    for cf in expand_control_files(cfg):
        if os.path.exists(cf) and control_file_looks_broken(cf, min_bytes):
            try:
                subprocess.run(["git", "checkout", "HEAD", "--", cf],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if control_file_looks_broken(cf, min_bytes):
                    subprocess.run(["git", "checkout", "HEAD~1", "--", cf],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                log_both(f"  🩹 {cf} 整檔空白 → 已還原（程式兜底；內容級審查由 agent G0 負責）。")
            except OSError as e:
                logger.error(f"Failed to checkout broken control file {cf}: {e}")


def git_guard(cfg: dict, round_no: int, log_both):
    if not in_git_repo():
        return
    min_bytes = cfg["runtime"]["control_min_bytes"]
    try:
        for cf in expand_control_files(cfg):
            if os.path.exists(cf) and control_file_looks_broken(cf, min_bytes):
                log_both(f"[guard] {cf} 疑似被清空 → 提交前先從 HEAD 還原")
                subprocess.run(["git", "checkout", "HEAD", "--", cf])
        if subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True).stdout.strip():
            log_both(f"[guard] 補一次安全 commit（round {round_no}）")
            subprocess.run(["git", "add", "-A"])
            subprocess.run(["git", "commit", "-m", f"loop-autocommit: round {round_no}"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as e:
        logger.error(f"Failed during git guard: {e}")
