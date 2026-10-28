"""生成桌面快捷方式（含图标）。

用法:
    py streamlit_app/install_desktop_shortcut.py             # 安装到桌面
    py streamlit_app/install_desktop_shortcut.py --remove    # 删除桌面快捷方式

做三件事：
1. 把 run-icon.png 转成多尺寸 run-icon.ico（Windows 快捷方式只认 .ico/.exe/.dll）
2. 在桌面创建「全天候再平衡面板.lnk」，指向 run.bat 并使用上面的图标
3. --remove 时清理桌面快捷方式

依赖 pillow（PNG→ICO）。没装 pillow 时退化为「把 PNG 直接嵌进 ICO 容器」，
Vista 以上系统同样识别。
"""
from __future__ import annotations

import argparse
import os
import struct
import subprocess
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
RUN_BAT = APP_DIR / "run.bat"
PNG_ICON = APP_DIR / "run-icon.png"
ICO_FILE = APP_DIR / "run-icon.ico"
SHORTCUT_NAME = "全天候再平衡面板.lnk"


def desktop_dir() -> Path:
    """返回用户实际使用的桌面目录（兼容 OneDrive 重定向与中文路径）。"""
    try:
        import ctypes
        from ctypes import wintypes

        buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
        ctypes.windll.shell32.SHGetFolderPathW(None, 0x0010, None, 0, buf)  # CSIDL_DESKTOPDIRECTORY
        if buf.value:
            return Path(buf.value)
    except Exception:
        pass
    home = Path(os.path.expanduser("~"))
    for c in (
        home / "OneDrive" / "Desktop",
        home / "Desktop",
        Path(os.environ.get("USERPROFILE", home)) / "Desktop",
    ):
        if c.is_dir():
            return c
    return home / "Desktop"


def png_to_ico(png: Path, ico: Path) -> None:
    """标准多尺寸 ICO（首选）。"""
    from PIL import Image

    with Image.open(png) as im:
        im = im.convert("RGBA")
        max_side = max(im.size)
        sizes = [s for s in ((256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)) if s[0] <= max_side]
        im.save(ico, format="ICO", sizes=sizes or [(256, 256)])


def png_wrap_ico(png: Path, ico: Path) -> None:
    """无 pillow 的降级：ICO 容器直接嵌 PNG 数据流（Vista+ 支持）。"""
    data = png.read_bytes()
    w, h = struct.unpack(">II", data[16:24])
    entry = (
        bytes([w if w < 256 else 0, h if h < 256 else 0, 0, 0])
        + struct.pack("<HH", 1, 32)          # 每像素位数 / 色板
        + struct.pack("<II", len(data), 22)  # 数据大小 / 偏移量(6+16)
    )
    ico.write_bytes(struct.pack("<HHH", 0, 1, 1) + entry + data)


def create_shortcut(lnk: Path, target: Path, icon: Path, workdir: Path) -> None:
    ps = f"""
$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut("{lnk}")
$sc.TargetPath = "{target}"
$sc.WorkingDirectory = "{workdir}"
$sc.IconLocation = "{icon},0"
$sc.Description = "全天候再平衡面板"
$sc.Save()
"""
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
        check=True,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--remove", action="store_true", help="删除桌面快捷方式")
    args = ap.parse_args()

    desktop = desktop_dir()
    lnk = desktop / SHORTCUT_NAME

    if args.remove:
        if lnk.exists():
            lnk.unlink()
            print(f"已删除 {lnk}")
        else:
            print(f"桌面上没有 {SHORTCUT_NAME}")
        return 0

    if not RUN_BAT.exists():
        print(f"[错误] 找不到 {RUN_BAT}")
        return 1
    if not PNG_ICON.exists():
        print(f"[错误] 找不到图标源文件 {PNG_ICON}")
        return 1

    try:
        png_to_ico(PNG_ICON, ICO_FILE)
    except ImportError:
        print("[提示] 未安装 pillow，降级生成 ico")
        png_wrap_ico(PNG_ICON, ICO_FILE)
    print(f"图标已生成: {ICO_FILE} ({ICO_FILE.stat().st_size} bytes)")

    create_shortcut(lnk, RUN_BAT, ICO_FILE, APP_DIR)
    print(f"桌面快捷方式: {lnk}")
    print("双击即可启动面板，图标已指向 run-icon.ico")
    return 0


if __name__ == "__main__":
    sys.exit(main())
