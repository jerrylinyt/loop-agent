import os
import sys
import webbrowser
import subprocess
import time

def main():
    dashboard_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(dashboard_dir)
    
    # We will launch uvicorn using subprocess so we can open the browser
    # Make sure we are in the repo_root or dashboard_dir
    print("啟動 Loop Dashboard...")
    
    # Use uvicorn module directly to ensure it works even if uvicorn is not in PATH
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "dashboard.app:app", "--host", "127.0.0.1", "--port", "8000"],
        cwd=repo_root
    )
    
    # Give it a second to start
    time.sleep(1.5)
    
    url = "http://127.0.0.1:8000"
    print(f"\n✅ 儀表板已啟動！請在瀏覽器開啟: {url}")
    print("（按 Ctrl+C 可關閉伺服器）\n")
    
    try:
        webbrowser.open(url)
        proc.wait()
    except KeyboardInterrupt:
        print("\n正在關閉儀表板...")
        proc.terminate()
        proc.wait()

if __name__ == "__main__":
    main()
