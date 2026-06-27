import os
import re
import logging
from collections import deque
from git_utils import git_head

logger = logging.getLogger(__name__)

# ─────────────── CONTROL 讀寫（單行，不載入 LLM context） ───────────────
def get_val(control: str, key: str) -> str | None:
    if not os.path.exists(control):
        return None
    pat = re.compile(rf"^\s*{re.escape(key)}\s*:\s*(.*?)\s*$")
    try:
        with open(control, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                m = pat.match(line)
                if m:
                    return m.group(1).split("#", 1)[0].strip().strip('"')
    except OSError as e:
        logger.warning(f"Failed to read {control}: {e}")
    return None


def set_val(control: str, key: str, value: str):
    if not os.path.exists(control):
        return
    pat = re.compile(rf"^(\s*{re.escape(key)}\s*:\s*).*?(\s*(#.*)?)$")
    out, hit = [], False
    try:
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
    except OSError as e:
        logger.error(f"Failed to write to {control}: {e}")


def as_int(v, d=0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return d


# ─────────────── 震盪歷史持久化（重啟接續，不歸零） ───────────────
def fail_history_path(cfg: dict) -> str:
    return os.path.join(cfg["runtime"]["state_dir"], "fail_history")


def load_fail_history(cfg: dict, maxlen: int) -> deque:
    dq = deque(maxlen=maxlen)
    p = fail_history_path(cfg)
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        dq.append(line)
        except OSError as e:
            logger.warning(f"Failed to load fail history: {e}")
    return dq


def save_fail_history(cfg: dict, dq: deque):
    p = fail_history_path(cfg)
    try:
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write("\n".join(dq) + ("\n" if dq else ""))
    except OSError as e:
        logger.error(f"Failed to save fail history: {e}")


# ─── 進度/活動持久化（跨 phase 正確判進展 + 無活動偵測；重啟接續，不歸零） ───
def progress_signature(cfg: dict, control: str) -> str:
    """本輪『活動簽章』= current_phase + 各 phase consecutive_pass 總和 + HEAD commit。
    連續多輪簽章不變 = agent 沒提交任何東西、計數器也沒動（空轉/反覆被 watchdog 中斷/CLI 壞掉）。"""
    phase = get_val(control, "current_phase") or ""
    total_pass = 0
    for ph in (cfg.get("phases") or []):
        total_pass += as_int(get_val(control, f"p{ph.get('id')}_consecutive_pass"))
    return f"{phase}|{total_pass}|{git_head()}"


def progress_path(cfg: dict) -> str:
    return os.path.join(cfg["runtime"]["state_dir"], "progress")


def load_progress(cfg: dict) -> dict:
    data = {}
    p = progress_path(cfg)
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                for line in f:
                    if ":" in line:
                        k, v = line.split(":", 1)
                        data[k.strip()] = v.strip()
        except OSError as e:
            logger.warning(f"Failed to load progress: {e}")
    return data


def save_progress(cfg: dict, **kw):
    p = progress_path(cfg)
    try:
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            for k, v in kw.items():
                f.write(f"{k}: {v}\n")
    except OSError as e:
        logger.error(f"Failed to save progress: {e}")


def rounds_log_path(cfg: dict) -> str:
    return os.path.join(cfg["runtime"]["state_dir"], "rounds.jsonl")


def append_round_record(cfg: dict, record: dict) -> None:
    """Append 一行逐輪紀錄到 rounds.jsonl。Best-effort：失敗只記 warning，絕不中斷主迴圈。"""
    p = rounds_log_path(cfg)
    try:
        os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
        import json
        line = json.dumps(record, ensure_ascii=False)
        with open(p, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except (OSError, TypeError, ValueError) as e:
        logger.warning(f"Failed to append round record: {e}")

