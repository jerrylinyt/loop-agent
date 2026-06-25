import os
import sys
import time
import select
import signal
import shlex
import threading
import subprocess
import logging

logger = logging.getLogger(__name__)

try:
    import pty
    HAVE_PTY = True
except ImportError:           # Windows
    HAVE_PTY = False

def console_echo_enabled(cfg: dict) -> bool:
    if os.environ.get("LOOP_QUIET") == "1":
        return False
    return bool(cfg.get("runtime", {}).get("console_echo", True))

def build_cmd(cfg: dict, model: str, prompt: str) -> list[str]:
    agent = cfg["agent"]
    template = agent.get("build_cmd") or "codex e --model {model} {prompt}"
    extra = [str(a) for a in (agent.get("extra_args") or [])]
    
    # 針對 Windows 上 shlex.split 可能吃掉反斜線的問題做修補
    # posix=False 保留反斜線，適合 Windows
    is_posix = (os.name != "nt")
    tokens = shlex.split(template, posix=is_posix)
    
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
def run_agent(cmd: list[str], cfg: dict) -> tuple[int, str | None]:
    rt = cfg["runtime"]
    round_timeout = rt["round_timeout_seconds"]
    idle_timeout = rt["idle_timeout_seconds"]
    log_path = rt["log_file"]
    echo = console_echo_enabled(cfg)

    if HAVE_PTY:
        return _run_agent_pty(cmd, log_path, round_timeout, idle_timeout, echo)
    return _run_agent_pipe(cmd, log_path, round_timeout, idle_timeout, echo)


def _run_agent_pty(cmd: list[str], log_path: str, round_timeout: int, idle_timeout: int, echo: bool = True) -> tuple[int, str | None]:
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


def _run_agent_pipe(cmd: list[str], log_path: str, round_timeout: int, idle_timeout: int, echo: bool = True) -> tuple[int, str | None]:
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
