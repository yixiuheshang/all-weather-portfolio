@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo 正在启动全天候再平衡面板...
echo.

rem Windows 上 `python` 常被微软商店占位程序抢走，双击就会闪退。
rem 优先用官方启动器 `py`，再回退到 python。
set "PY_CMD="
where py >nul 2>&1 && set "PY_CMD=py"
if not defined PY_CMD (
  where python >nul 2>&1 && set "PY_CMD=python"
)

if not defined PY_CMD (
  echo [错误] 找不到 Python。
  echo 请安装 Python 3.10+ ，或在终端运行: py --version
  echo.
  pause
  exit /b 1
)

%PY_CMD% "%~dp0run.py"
if errorlevel 1 (
  echo.
  echo 启动失败。常见原因:
  echo   1. 点了 python 实际是微软商店占位 — 请用 py，或关闭
  echo      设置 ^> 应用 ^> 高级应用设置 ^> 应用执行别名 里的 python.exe
  echo   2. 未安装 streamlit:  %PY_CMD% -m pip install -r "%~dp0requirements.txt"
  echo.
  pause
  exit /b 1
)
