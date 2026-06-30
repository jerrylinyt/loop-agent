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


def changed_files_between(before: str, after: str) -> list[str]:
    if not before or not after or before == after or not in_git_repo():
        return []
    try:
        r = subprocess.run(["git", "diff", "--name-only", before, after], capture_output=True, text=True)
        return sorted([x for x in r.stdout.strip().splitlines() if x])
    except OSError as e:
        logger.warning(f"Failed to get changed files between {before} and {after}: {e}")
        return []


def expand_control_files(cfg: dict) -> list[str]:
    files = []
    for pat in cfg.get("control_files", []):
        matched = glob.glob(pat)
        files.extend(matched if matched else [pat])
    return files


def control_file_looks_broken(path: str) -> bool:
    if not os.path.exists(path):
        return False
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.strip():
                    return not line.lstrip().startswith("#")
        return True # 全空或全是註解
    except OSError as e:
        logger.warning(f"Error checking if control file is broken {path}: {e}")
        return True


def inspect_and_fix_blank(cfg: dict, log_both) -> bool:
    """檢查核心狀態檔案是否完整。若破損（全空或被刪除），嘗試往回找 5 個 commit 還原。
    若皆失敗，回傳 False 讓引擎停機。"""
    if not in_git_repo():
        return True
    max_lookback = 5
    
    for cf in expand_control_files(cfg):
        is_tracked = subprocess.run(["git", "ls-files", "--error-unmatch", cf], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
        is_missing = is_tracked and not os.path.exists(cf)
        is_broken = os.path.exists(cf) and control_file_looks_broken(cf)
        
        if is_missing or is_broken:
            reason = "被無故刪除" if is_missing else "被清空或只剩註解"
            log_both(f"  ⚠️ 偵測到核心狀態檔 {cf} {reason}，嘗試從歷史紀錄復原...")
            recovered = False
            for i in range(max_lookback + 1):
                ref = "HEAD" if i == 0 else f"HEAD~{i}"
                try:
                    subprocess.run(["git", "checkout", ref, "--", cf],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    if os.path.exists(cf) and not control_file_looks_broken(cf):
                        log_both(f"  🩹 {cf} 成功從 {ref} 復原！")
                        recovered = True
                        break
                except OSError:
                    pass
                    
            if not recovered:
                log_both(f"  🚨 致命錯誤：狀態檔 {cf} 無法從最近 {max_lookback} 個 Commit 中復原！")
                return False
                
    return True


def git_guard(cfg: dict, round_no: int, log_both):
    if not in_git_repo():
        return
    try:
        for cf in expand_control_files(cfg):
            if os.path.exists(cf) and control_file_looks_broken(cf):
                log_both(f"[guard] {cf} 疑似被清空 → 提交前先從 HEAD 還原")
                subprocess.run(["git", "checkout", "HEAD", "--", cf])
        if subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True).stdout.strip():
            log_both(f"[guard] 補一次安全 commit（round {round_no}）")
            subprocess.run(["git", "add", "-A"])
            subprocess.run(["git", "commit", "-m", f"loop-autocommit: round {round_no}"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as e:
        logger.error(f"Failed during git guard: {e}")
