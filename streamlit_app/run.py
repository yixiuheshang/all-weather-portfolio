import os
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
APP_FILE = Path(__file__).resolve().parent / "app.py"
URL = "http://localhost:8501"


def _pause_if_double_clicked():
    if sys.platform == "win32":
        input("按回车键退出...")


try:
    import streamlit  # noqa: F401
except ImportError:
    print("未安装 streamlit，无法启动面板。请先运行:")
    print(f"  {sys.executable} -m pip install -r \"{Path(__file__).resolve().parent / 'requirements.txt'}\"")
    _pause_if_double_clicked()
    sys.exit(1)


def server_ready():
    try:
        urllib.request.urlopen(URL, timeout=1)
        return True
    except Exception:
        return False


def open_browser_when_ready():
    for _ in range(60):
        if server_ready():
            webbrowser.open(URL)
            print("已打开浏览器", flush=True)
            return
        time.sleep(1)
    print(f"超时，手动打开 {URL}", flush=True)


def main():
    os.chdir(PROJECT_DIR)
    print("正在启动全天候再平衡面板...", flush=True)
    threading.Thread(target=open_browser_when_ready, daemon=True).start()

    # 同一进程启动 Streamlit，避免再弹出第二个控制台；
    # headless 关闭 Streamlit 自带开浏览器，只由上面的线程打开一次。
    from streamlit.web.cli import main as st_main
    sys.argv = [
        "streamlit",
        "run",
        str(APP_FILE),
        "--server.headless=true",
        "--browser.gatherUsageStats=false",
    ]
    st_main()


if __name__ == "__main__":
    main()
