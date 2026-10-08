# -*- coding: utf-8 -*-
"""
Window Dock —— Windows 玻璃 Dock 与桌面虚拟分类
================================================================
运行环境：Windows + Python + PyQt5；当前验证环境为 Windows 11 x64、Python 3.14
特点：
  * 屏幕四边停靠，真毛玻璃（自己抓屏模糊）+ 液态玻璃高光
  * macOS 风格鼠标放大（鱼眼）效果，点击有回弹动画
  * 托盘与右键菜单管理，支持固定入口、分类规则和手动拖入
  * 一键设置开机自启动（写入注册表 HKCU Run）
  * 配置文件：%USERPROFILE%\\.BigFishDock\\config.json
  * 日志文件：%USERPROFILE%\\.BigFishDock\\dock.log

调试：命令行运行  python dock.py --preview 预览.png  可以导出一张预览图
     命令行运行  python dock.py --reset          清空所有已固定的图标
"""

import ctypes
import json
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import copy
from ctypes import wintypes
from organizer import default_state, normalize_path, separator_positions
from desktop_visibility import icons_visible, set_icons_visible

# ----------------------------------------------------------------------------
# 基本常量
# ----------------------------------------------------------------------------
APP_NAME = "BigFishDock"            # 配置目录名 + 注册表自启动项名
APP_TITLE = "大肥鱼dock栏"           # 显示给用户看的名字
MAIN_WINDOW_MARKER = "BigFishDock.MainDock"
VERSION = "1.1.39"
LEGACY_APP_NAME = "LiquidGlassDock"  # 旧名字，用来迁移配置和清理旧自启动项

# 打包成 exe 之后（PyInstaller），__file__ 指向临时解包目录，不能用；
# 这时程序目录就是 exe 自己所在的目录。
IS_FROZEN = bool(getattr(sys, "frozen", False))
if IS_FROZEN:
    SCRIPT_PATH = os.path.abspath(sys.executable)
    APP_DIR = os.path.dirname(SCRIPT_PATH)
else:
    SCRIPT_PATH = os.path.abspath(__file__)
    APP_DIR = os.path.dirname(SCRIPT_PATH)
# MSIX 宿主启动的子进程可能重定向 AppData，导致手动启动与登录启动各用一份配置。
# 用户主目录下的独立目录不参与 AppData 重定向，也不会随程序更新被替换。
CONFIG_DIR = os.path.join(os.path.expanduser("~"), "." + APP_NAME)
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
LOG_PATH = os.path.join(CONFIG_DIR, "dock.log")
APPDATA_CONFIG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP_NAME)
LEGACY_CONFIG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), LEGACY_APP_NAME)

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

DEFAULT_CONFIG = {
    "organizer": default_state(),  # 虚拟分类配置，不改变桌面文件的位置
    "show_desktop_icons": True,  # 保留旧配置键；桌面显示方式由 desktop_display 管理。
    "desktop_display": "managed",
    "items": [],          # [{"path": "...", "name": "..."}]
    "icon_size": 52,      # 沿用上游的图标基准尺寸（像素）
    "magnify": True,      # 鼠标放大效果
    "glass": True,        # 毛玻璃（背景模糊）效果
    "running_dots": True, # 运行中的程序显示小圆点
    "show_name": True,    # 鼠标悬停时在图标上方显示程序名称
    "transparency": 40,   # 玻璃通透度 0~100（越大越透）
    "theme": "auto",      # 沿用上游默认外观，已有配置保持原样
    "layer": "bottom",    # 窗口层级：bottom=置底（不挡窗口）/ top=置顶
    "blur_mode": "smart", # 背景抓取频率：smart/fast/normal/slow/off
    "blur_px": 6,         # 毛玻璃模糊程度（缩小的倍数，越大越糊）
    "bump_level": "mid",  # 悬停放大程度：low/mid/high，沿用旧配置键
    "lang": "zh",         # 界面语言：zh=中文 / en=English
    "reorder": True,      # 默认允许拖动排序；超过系统拖动阈值后才进入拖动
    "sep_split": True,    # 分隔符隔断模式：夹在两图标之间的分隔符会切开玻璃背景
    "position": "bottom", # 位置：bottom/top/left/right，custom 保留旧水平自定义高度
    "custom_bottom": 200, # 自定义位置时，距屏幕底部多少像素
    "autostart": False,   # 开机自启动
    "bottom_margin": 6,   # 距离任务栏上方的高度
}

ICON_SIZES = [("小", 42), ("中", 52), ("大", 62), ("特大", 74)]

# 玻璃通透度（数值越大越透，越能看见背后的模糊画面）
TRANSPARENCIES = [("默认", 40), ("通透", 60), ("很通透", 80)]

# 语言
LANGS = [("简体中文", "zh"), ("English", "en")]

# 颜色模式
THEMES = [("跟随系统", "auto"), ("浅色", "light"), ("深色", "dark"), ("光感", "gloss")]

# 窗口层级
LAYERS = [("置底（不挡任何窗口，推荐）", "bottom"), ("置顶（始终看得见）", "top")]

# 窗口位置
POSITIONS = [("屏幕底部（默认）", "bottom"), ("屏幕顶部", "top"),
             ("屏幕左侧", "left"), ("屏幕右侧", "right"), ("自定义…", "custom")]

# 背景抓取频率（毫秒）。静态壁纸不需要频繁抓，智能模式平时几乎不干活。
BLUR_MODES = [("智能（省电，推荐）", "smart"), ("实时（每秒一次）", "fast"),
              ("普通（每 3 秒）", "normal"), ("省电（每 10 秒）", "slow"),
              ("停止抓取（静态壁纸，只抓一次）", "off")]
BLUR_INTERVAL = {"smart": 8000, "fast": 1000, "normal": 3000, "slow": 10000, "off": 0}

# 毛玻璃模糊程度（数值 = 缩小的倍数，越大越模糊）
BLUR_LEVELS = [("低（更清晰）", 3), ("中（默认）", 6), ("高（更朦胧）", 11)]

# 沿用旧档位配置；现在控制局部放大，而非玻璃鼓包。
BUMP_LEVELS = [("low", "低（轻微）", 1.32),
               ("mid", "中（默认）", 1.42),
               ("high", "高（明显）", 1.52)]

# ----------------------------------------------------------------------------
# 语言：托盘里可以中英切换。英文直接查表，查不到就原样返回中文。
# ----------------------------------------------------------------------------
LANG = {"cur": "zh"}

EN = {
    # 主菜单
    "显示 / 隐藏 Dock": "Show / Hide Dock",
    "显示桌面图标": "Show desktop icons",
    "添加图标…": "Add Icon…",
    "添加分隔符": "Add Separator",
    "分隔符隔断背景": "Split Background at Separators",
    "图标顺序可拖动": "Draggable Icon Order",
    "移除图标": "Remove Icon",
    "—— 分隔符 ——": "—— Separator ——",
    "（还没有固定任何图标）": "(nothing pinned yet)",
    # 图标大小
    "图标大小": "Icon Size",
    "小": "Small",
    "中": "Medium",
    "大": "Large",
    "特大": "Extra Large",
    "%s（%d 像素）": "%s (%d px)",
    "自定义…（当前 %d 像素）": "Custom… (%d px now)",
    # 颜色模式
    "颜色模式": "Color Mode",
    "跟随系统": "Follow System",
    "浅色": "Light",
    "深色": "Dark",
    "光感": "Glossy",
    # 层级
    "窗口层级": "Window Layer",
    "置底（不挡任何窗口，推荐）": "Bottom (recommended)",
    "置顶（始终看得见）": "Top (always visible)",
    # 位置
    "窗口位置": "Window Position",
    "屏幕底部（默认）": "Screen Bottom (default)",
    "屏幕顶部": "Screen Top",
    "屏幕左侧": "Screen Left",
    "屏幕右侧": "Screen Right",
    "自定义…": "Custom…",
    "调整自定义高度…（当前距底部 %d 像素）": "Custom Height… (%d px from bottom)",
    # 背景抓取
    "背景抓取频率": "Background Capture",
    "智能（省电，推荐）": "Smart (power saving)",
    "实时（每秒一次）": "Realtime (every second)",
    "普通（每 3 秒）": "Normal (every 3 s)",
    "省电（每 10 秒）": "Low power (every 10 s)",
    "停止抓取（静态壁纸，只抓一次）": "Never (static wallpaper)",
    "立即刷新一次背景": "Refresh Background Now",
    # 悬停动画
    "悬停动画": "Hover Animation",
    "启用悬停放大": "Enable Hover Magnification",
    "放大程度：%s": "Magnification: %s",
    "低（轻微）": "Low (subtle)",
    "中（默认）": "Medium (default)",
    "高（明显）": "High (obvious)",
    # 毛玻璃
    "毛玻璃（背景模糊）": "Frosted Glass",
    "启用毛玻璃效果": "Enable Frosted Glass",
    "模糊程度：%s": "Blur: %s",
    "低（更清晰）": "Low (clearer)",
    "高（更朦胧）": "High (hazier)",
    "模糊程度：自定义…（当前 %d）": "Blur: Custom… (%d now)",
    # 其它开关
    "运行中的程序显示小圆点": "Show Running Dots",
    "悬停时显示程序名称": "Show App Name on Hover",
    "玻璃通透度": "Glass Transparency",
    "默认": "Default",
    "通透": "Clear",
    "很通透": "Very Clear",
    "%s（%d%%）": "%s (%d%%)",
    "开机自动启动": "Start with Windows",
    # 语言本身
    "语言 / Language": "语言 / Language",
    "简体中文": "简体中文",
    "English": "English",
    # 底部
    "使用说明": "User Guide",
    "打开配置文件夹": "Open Config Folder",
    "退出": "Quit",
    # 对话框与提示
    "选择要固定到 Dock 的程序（可多选）": "Choose programs to pin (multi-select)",
    "程序与快捷方式 (*.exe *.lnk *.bat *.cmd *.url *.msc *.ps1);;所有文件 (*.*)":
        "Programs & shortcuts (*.exe *.lnk *.bat *.cmd *.url *.msc *.ps1);;All files (*.*)",
    "已添加 %d 个图标到 Dock": "Added %d icon(s) to the dock",
    "毛玻璃模糊强度：\n（3 ~ 30，数字越大越模糊、越朦胧）":
        "Blur strength:\n(3 ~ 30, bigger = hazier)",
    "玻璃条距离屏幕底部多少像素？\n（Dock 始终水平居中，数字越大越往上）":
        "How many pixels from the bottom of the screen?\n(the dock stays horizontally centered)",
    "请输入图标像素大小：\n（建议 32 ~ 160，数字越大图标越大）":
        "Icon size in pixels:\n(32 ~ 160 recommended)",
    "已开启开机自启动": "Autostart enabled",
    "已取消开机自启动": "Autostart disabled",
    "设置失败，请查看日志：\n": "Failed, please check the log:\n",
    "请在托盘菜单里操作：添加图标 / 移除图标。": "Use the tray menu: Add Icon / Remove Icon.",
    "请在右下角托盘图标上右键 → 添加图标": "Right-click the tray icon → Add Icon",
    "Dock 已经在运行了（请看右下角托盘）。": "The dock is already running (see the tray).",
}


def T(s):
    """把界面文字翻成当前语言。"""
    if LANG["cur"] == "en":
        return EN.get(s, s)
    return s


def set_lang(v):
    LANG["cur"] = "en" if str(v) == "en" else "zh"

# SetWindowPos 用的常量
HWND_TOPMOST = -1
HWND_BOTTOM = 1
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010


# ----------------------------------------------------------------------------
# 日志
# ----------------------------------------------------------------------------
def log(msg):
    try:
        if not os.path.isdir(CONFIG_DIR):
            os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        pass


def _excepthook(etype, value, tb):
    log("未捕获异常:\n" + "".join(traceback.format_exception(etype, value, tb)))


sys.excepthook = _excepthook


# ----------------------------------------------------------------------------
# 配置读写
# ----------------------------------------------------------------------------
def migrate_legacy():
    """新位置首次使用时复制旧配置；保留原件，不覆盖已经迁移或修改过的配置。"""
    if os.path.exists(CONFIG_PATH):
        return
    try:
        for directory in (APPDATA_CONFIG_DIR, LEGACY_CONFIG_DIR):
            old = os.path.join(directory, "config.json")
            if os.path.exists(old):
                os.makedirs(CONFIG_DIR, exist_ok=True)
                tmp = CONFIG_PATH + ".migrate"
                shutil.copy2(old, tmp)
                os.replace(tmp, CONFIG_PATH)
                log("已从旧目录迁移配置: " + old)
                return
    except Exception:
        log("迁移配置失败: " + traceback.format_exc())


def load_config():
    migrate_legacy()
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            for k in DEFAULT_CONFIG:
                if k in data:
                    cfg[k] = data[k]
    except Exception:
        pass
    if not isinstance(cfg.get("items"), list):
        cfg["items"] = []
    if str(cfg.get("theme")) == "fog":
        cfg["theme"] = "gloss"        # 旧的"雾透模式"改名成"光感"
    clean = []
    for it in cfg["items"]:
        if not isinstance(it, dict):
            continue
        if it.get("sep"):
            clean.append({"sep": True})
        elif it.get("path"):
            clean.append({"path": it["path"],
                          "name": it.get("name") or os.path.splitext(os.path.basename(it["path"]))[0]})
    cfg["items"] = clean
    return cfg


def save_config(cfg):
    try:
        if not os.path.isdir(CONFIG_DIR):
            os.makedirs(CONFIG_DIR, exist_ok=True)
        tmp = CONFIG_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        os.replace(tmp, CONFIG_PATH)
    except Exception:
        log("保存配置失败: " + traceback.format_exc())


# ----------------------------------------------------------------------------
# Windows 系统相关的小工具（全部用 ctypes，不需要额外库）
# ----------------------------------------------------------------------------
user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32
shell32 = ctypes.windll.shell32
comctl32 = ctypes.windll.comctl32

# --- 屏幕捕获排除（抓背景时把自己藏起来） --------------------------------
WDA_NONE = 0x0
WDA_EXCLUDEFROMCAPTURE = 0x11


# --- 图标提取（尽量拿高分辨率图标） --------------------------------------
class BITMAP(ctypes.Structure):
    _fields_ = [
        ("bmType", wintypes.LONG),
        ("bmWidth", wintypes.LONG),
        ("bmHeight", wintypes.LONG),
        ("bmWidthBytes", wintypes.LONG),
        ("bmPlanes", wintypes.WORD),
        ("bmBitsPixel", wintypes.WORD),
        ("bmBits", ctypes.c_void_p),
    ]


class ICONINFO(ctypes.Structure):
    _fields_ = [
        ("fIcon", wintypes.BOOL),
        ("xHotspot", wintypes.DWORD),
        ("yHotspot", wintypes.DWORD),
        ("hbmMask", wintypes.HBITMAP),
        ("hbmColor", wintypes.HBITMAP),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]


# IID_IImageList
_IID_IIMAGELIST = _GUID(0x46EB5926, 0x582E, 0x4017,
                        (ctypes.c_ubyte * 8)(0x9F, 0xDF, 0xE8, 0x99, 0x8D, 0xAA, 0x09, 0x50))

try:
    # SHGetImageList 在 shell32 里只有序号 727，没有名字导出，只能按序号取：
    # 注意写法是 (序号, 库)，不是把序号当第二个参数传
    _SHGetImageList = ctypes.WINFUNCTYPE(
        ctypes.c_long, ctypes.c_int, ctypes.POINTER(_GUID),
        ctypes.POINTER(ctypes.c_void_p))((727, shell32))
    _SHGetImageList.restype = ctypes.c_long
    _SHGetImageList.argtypes = [ctypes.c_int, ctypes.POINTER(_GUID),
                                ctypes.POINTER(ctypes.c_void_p)]
except Exception:
    _SHGetImageList = None
    log("SHGetImageList 绑定失败: " + traceback.format_exc())


class SHFILEINFOW(ctypes.Structure):
    _fields_ = [("hIcon", wintypes.HICON),
                ("iIcon", ctypes.c_int),
                ("dwAttributes", wintypes.DWORD),
                ("szDisplayName", wintypes.WCHAR * 260),
                ("szTypeName", wintypes.WCHAR * 80)]


def extract_shell_hicon(path, size=256):
    """用 Windows 外壳的"超大图标"列表取图标。

    文件夹、URL 快捷方式、商店应用这些没法用 PrivateExtractIconsW 抠图标，
    只能问外壳要。QFileIconProvider 只给 32/40 像素，放大会糊，
    这里直接取 256 像素那一档（取不到再退 48 / 32）。
    """
    if _SHGetImageList is None:
        return None
    try:
        SHGFI_SYSICONINDEX = 0x000004000
        info = SHFILEINFOW()
        r = shell32.SHGetFileInfoW(ctypes.c_wchar_p(path), 0, ctypes.byref(info),
                                   ctypes.sizeof(info), SHGFI_SYSICONINDEX)
        if not r:
            return None
        comctl32.ImageList_GetIcon.restype = wintypes.HICON
        comctl32.ImageList_GetIcon.argtypes = [ctypes.c_void_p, ctypes.c_int, wintypes.UINT]
        # SHIL_JUMBO=4(256px) → SHIL_EXTRALARGE=2(48px) → SHIL_LARGE=0(32px)
        for shil in (4, 2, 0):
            himl = ctypes.c_void_p()
            if _SHGetImageList(shil, ctypes.byref(_IID_IIMAGELIST), ctypes.byref(himl)) != 0:
                continue
            if not himl:
                continue
            try:
                hicon = comctl32.ImageList_GetIcon(himl, int(info.iIcon), 0x1)
                if hicon:
                    return int(hicon)
            finally:
                table = ctypes.cast(himl, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
                release = ctypes.WINFUNCTYPE(wintypes.ULONG, ctypes.c_void_p)(table[2])
                release(himl)
    except Exception:
        log("extract_shell_hicon 失败 %s: %s" % (path, traceback.format_exc()))
    return None


def extract_hicon(path, size=256):
    """用 PrivateExtractIconsW 从 exe/dll/ico 里取出指定尺寸的 HICON。"""
    try:
        fn = user32.PrivateExtractIconsW
    except AttributeError:
        return None
    try:
        fn.restype = wintypes.UINT
        fn.argtypes = [wintypes.LPCWSTR, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                       ctypes.POINTER(wintypes.HICON), ctypes.POINTER(wintypes.UINT),
                       wintypes.UINT, wintypes.UINT]
        hicon = wintypes.HICON(0)
        n = fn(path, 0, size, size, ctypes.byref(hicon), None, 1, 0)
        if n and hicon.value:
            return hicon.value
    except Exception:
        log("extract_hicon 失败 %s: %s" % (path, traceback.format_exc()))
    return None


def hicon_to_qimage(hicon):
    """HICON -> QImage（带透明通道）。"""
    from PyQt5.QtGui import QImage
    from PyQt5.QtCore import Qt
    info = ICONINFO()
    if not user32.GetIconInfo(wintypes.HICON(int(hicon)), ctypes.byref(info)):
        return None
    hdc = None
    memdc = None
    hdib = None
    try:
        if not info.hbmColor:
            return None
        bm = BITMAP()
        if not gdi32.GetObjectW(wintypes.HGDIOBJ(int(info.hbmColor)), ctypes.sizeof(BITMAP), ctypes.byref(bm)):
            return None
        w, h = int(bm.bmWidth), int(bm.bmHeight)
        if w <= 0 or h <= 0:
            return None
        bmi = BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.biWidth = w
        bmi.biHeight = -h          # 负数 = 从上到下的行序
        bmi.biPlanes = 1
        bmi.biBitCount = 32
        bmi.biCompression = 0      # BI_RGB
        hdc = user32.GetDC(None)
        bits = ctypes.c_void_p()
        hdib = gdi32.CreateDIBSection(wintypes.HDC(hdc), ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
        if not hdib:
            return None
        memdc = gdi32.CreateCompatibleDC(wintypes.HDC(hdc))
        old = gdi32.SelectObject(wintypes.HDC(memdc), wintypes.HGDIOBJ(hdib))
        user32.DrawIconEx(wintypes.HDC(memdc), 0, 0, wintypes.HICON(int(hicon)), w, h, 0, None, 3)  # DI_NORMAL
        buf = ctypes.string_at(bits, w * h * 4)
        img = QImage(buf, w, h, w * 4, QImage.Format_ARGB32_Premultiplied).copy()
        gdi32.SelectObject(wintypes.HDC(memdc), old)
        return img.convertToFormat(QImage.Format_ARGB32)
    except Exception:
        log("hicon_to_qimage 失败: " + traceback.format_exc())
        return None
    finally:
        try:
            if hdib:
                gdi32.DeleteObject(wintypes.HGDIOBJ(hdib))
            if memdc:
                gdi32.DeleteDC(wintypes.HDC(memdc))
            if hdc:
                user32.ReleaseDC(None, wintypes.HDC(hdc))
            if info.hbmColor:
                gdi32.DeleteObject(wintypes.HGDIOBJ(info.hbmColor))
            if info.hbmMask:
                gdi32.DeleteObject(wintypes.HGDIOBJ(info.hbmMask))
            user32.DestroyIcon(wintypes.HICON(int(hicon)))
        except Exception:
            pass


def resolve_lnk_target(path):
    """尽力从 .lnk 快捷方式里解析出真实目标路径（解析失败返回 None）。"""
    if not path.lower().endswith(".lnk"):
        return None
    try:
        with open(path, "rb") as f:
            data = f.read()
    except Exception:
        return None
    candidates = []
    for enc in ("utf-16-le", "mbcs", "latin-1"):
        try:
            text = data.decode(enc, "ignore")
        except Exception:
            continue
        for m in re.finditer(r"[A-Za-z]:\\[^\x00-\x1f\"<>|*?\r\n]{2,240}", text):
            s = m.group(0).strip()
            if s.lower().endswith((".exe", ".dll", ".ico")):
                candidates.append(s)
        if candidates:
            break
    for c in candidates:
        if os.path.exists(c):
            return c
    return candidates[0] if candidates else None


# --- 正在运行的进程 ------------------------------------------------------
class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", wintypes.WCHAR * 260)]


def get_running_exe_names():
    """返回当前正在运行的进程的可执行文件名集合（小写）。

    用 CreateToolhelp32Snapshot 一次拿全，比逐个 OpenProcess 快十倍以上
    （后者要 6ms 左右，每几秒跑一次会造成动画微卡顿）。
    """
    names = set()
    try:
        TH32CS_SNAPPROCESS = 0x00000002
        kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if not snap or int(snap) == -1:
            return names
        try:
            entry = PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
            ok = kernel32.Process32FirstW(wintypes.HANDLE(snap), ctypes.byref(entry))
            while ok:
                name = entry.szExeFile
                if name:
                    names.add(name.lower())
                ok = kernel32.Process32NextW(wintypes.HANDLE(snap), ctypes.byref(entry))
        finally:
            kernel32.CloseHandle(wintypes.HANDLE(snap))
    except Exception:
        log("get_running_exe_names 失败: " + traceback.format_exc())
    return names


# --- 开机自启动 ----------------------------------------------------------
def pythonw_path():
    """返回 pythonw.exe 的绝对路径（用它启动才不会弹出黑色控制台窗口）。"""
    exe = sys.executable or ""
    d = os.path.dirname(exe)
    cand = os.path.join(d, "pythonw.exe")
    if os.path.exists(cand):
        return cand
    return exe


def autostart_command():
    """开机自启动要执行的命令行。打包成 exe 后直接就是 exe 自己。"""
    if IS_FROZEN:
        return '"%s"' % SCRIPT_PATH
    return '"%s" "%s"' % (pythonw_path(), SCRIPT_PATH)


def set_autostart(enable):
    import winreg
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE)
    except Exception:
        return False
    try:
        if enable:
            cmd = autostart_command()
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)
            log("已设置开机自启动: " + cmd)
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
                log("已取消开机自启动")
            except FileNotFoundError:
                pass
        return True
    except Exception:
        log("设置开机自启动失败: " + traceback.format_exc())
        return False
    finally:
        winreg.CloseKey(key)


def get_autostart():
    import winreg
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_QUERY_VALUE)
        try:
            val, _ = winreg.QueryValueEx(key, APP_NAME)
            return bool(val)
        except FileNotFoundError:
            return False
        finally:
            winreg.CloseKey(key)
    except Exception:
        return False


def system_is_light():
    """读注册表判断 Windows 当前是不是浅色模式（读不到就当作深色）。"""
    import winreg
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
                             0, winreg.KEY_QUERY_VALUE)
    except Exception:
        return False
    try:
        for name in ("SystemUsesLightTheme", "AppsUseLightTheme"):
            try:
                v, _ = winreg.QueryValueEx(key, name)
                return bool(int(v))
            except FileNotFoundError:
                continue
        return False
    except Exception:
        return False
    finally:
        winreg.CloseKey(key)


def start_menu_dirs():
    out = []
    for p in (os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs"),
              os.path.join(os.environ.get("ProgramData", ""), r"Microsoft\Windows\Start Menu\Programs")):
        if p and os.path.isdir(p):
            out.append(p)
    return out


# ----------------------------------------------------------------------------
# PyQt5 部分
# ----------------------------------------------------------------------------
import PyQt5
from PyQt5.QtCore import (Qt, QTimer, QPoint, QPointF, QRectF, QSize, QFileInfo,
                          QSharedMemory, QEvent, pyqtSignal, QRect)
from PyQt5.QtGui import (QColor, QIcon, QImage, QPainter, QPainterPath, QPixmap,
                         QLinearGradient, QRadialGradient, QPen, QBrush, QFont,
                         QFontMetrics, QGuiApplication, QCursor, QTransform)
from PyQt5.QtWidgets import (QApplication, QWidget, QSystemTrayIcon,
                             QAction, QActionGroup, QFileDialog, QMessageBox,
                             QFileIconProvider, QToolTip, QInputDialog)
from organizer_service import OrganizerService
from organizer_ui import CategoryPanel, CategoryManager, set_entry_image_loader, _entry_menu_position
from organizer_artwork import category_pixmap, set_native_icons
from menu_ui import ThemedMenu
from trash_artwork import trash_pixmap, computer_pixmap
from dock_search import DockSearch
from file_actions import FileActions
from entry_drag import EntryDrag

# Qt 5 的安装路径探测在中文虚拟环境中可能损坏，显式保留 Unicode 插件路径。
_qt_platforms = os.path.join(os.path.dirname(PyQt5.__file__), "Qt5", "plugins", "platforms")
if os.path.isdir(_qt_platforms):
    os.environ.setdefault("QT_QPA_PLATFORM_PLUGIN_PATH", _qt_platforms)


class IconProvider(object):
    """负责把文件路径变成好看的图标（会缓存）。"""

    def __init__(self):
        self.provider = QFileIconProvider()
        self.cache = {}

    def get(self, path, px):
        key = (path.lower(), int(px))
        if key in self.cache:
            return self.cache[key]
        pm = None
        # 1) exe / dll / ico：直接抠出大图标，最清晰
        real = path
        if path.lower().endswith(".lnk"):
            t = resolve_lnk_target(path)
            if t:
                real = t
        if real.lower().endswith((".exe", ".dll", ".ico")) and os.path.exists(real):
            hicon = extract_hicon(real, max(64, int(px)))
            if hicon:
                img = hicon_to_qimage(hicon)
                if img is not None and not img.isNull():
                    # 预乘格式是 Qt 平滑缩放/合成的快路径（每帧都要缩放图标，
                    # 不转的话那一步会慢好几倍）
                    if img.format() != QImage.Format_ARGB32_Premultiplied:
                        img = img.convertToFormat(QImage.Format_ARGB32_Premultiplied)
                    pm = QPixmap.fromImage(img)
        # 2) 兜底一：问 Windows 外壳要"超大图标"（文件夹、URL 快捷方式、商店应用都靠这个，
        #    能拿到 256 像素，比 QFileIconProvider 的 32/40 像素清楚得多）
        if pm is None or pm.isNull():
            hicon = extract_shell_hicon(path, 256)
            if hicon:
                img = hicon_to_qimage(hicon)
                if img is not None and not img.isNull():
                    if img.format() != QImage.Format_ARGB32_Premultiplied:
                        img = img.convertToFormat(QImage.Format_ARGB32_Premultiplied)
                    pm = QPixmap.fromImage(img)
        # 3) 兜底二：交给 Qt 自带的方式
        if pm is None or pm.isNull():
            try:
                ic = self.provider.icon(QFileInfo(path))
                if not ic.isNull():
                    pm = ic.pixmap(QSize(int(px), int(px)))
            except Exception:
                pm = None
        if pm is None or pm.isNull():
            pm = QPixmap(int(px), int(px))
            pm.fill(Qt.transparent)
        else:
            img = pm.toImage()
            if img.format() != QImage.Format_ARGB32_Premultiplied:
                img = img.convertToFormat(QImage.Format_ARGB32_Premultiplied)
            # 源图太大就先缩到合适尺寸：外壳给的"超大图标"是 256 像素，
            # 而实际只会画到 60~90 像素，每帧从 256 缩下来很慢
            cap = max(96, int(px * 1.6))
            if img.width() > cap:
                img = img.scaled(cap, cap, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            pm = QPixmap.fromImage(img)
        self.cache[key] = pm
        return pm

    def clear(self):
        self.cache.clear()


def namespace_image(name):
    """向外壳取分类文件夹的原生大图标；PIDL 和接口均在本次调用中释放。"""
    ole = ctypes.windll.ole32
    initialized = ole.CoInitialize(None) >= 0
    pidl = ctypes.c_void_p()
    try:
        parse = shell32.SHParseDisplayName
        parse.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p,
                          ctypes.POINTER(ctypes.c_void_p), wintypes.DWORD,
                          ctypes.POINTER(wintypes.DWORD)]
        parse.restype = ctypes.c_long
        if parse(name, None, ctypes.byref(pidl), 0, None) < 0 or not pidl:
            return None
        info = SHFILEINFOW()
        if not shell32.SHGetFileInfoW(pidl, 0, ctypes.byref(info), ctypes.sizeof(info), 0x4008):
            return None
        if _SHGetImageList is None:
            return None
        return image_list_image(info.iIcon)
    except Exception:
        log("分类系统图标提取失败: " + traceback.format_exc())
    finally:
        if pidl:
            ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
            ole.CoTaskMemFree(pidl)
        if initialized:
            ole.CoUninitialize()
    return None


def image_list_image(index):
    if _SHGetImageList is None:
        return None
    for level in (4, 2, 0):
        image_list = ctypes.c_void_p()
        if _SHGetImageList(level, ctypes.byref(_IID_IIMAGELIST), ctypes.byref(image_list)) != 0 or not image_list:
            continue
        try:
            comctl32.ImageList_GetIcon.restype = wintypes.HICON
            comctl32.ImageList_GetIcon.argtypes = [ctypes.c_void_p, ctypes.c_int, wintypes.UINT]
            handle = comctl32.ImageList_GetIcon(image_list, index, 1)
            if handle:
                return hicon_to_qimage(handle)
        finally:
            table = ctypes.cast(image_list, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
            release = ctypes.WINFUNCTYPE(wintypes.ULONG, ctypes.c_void_p)(table[2])
            release(image_list)
    return None


def stock_image(stock_id):
    class StockInfo(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("hIcon", wintypes.HICON),
                    ("iSysImageIndex", ctypes.c_int), ("iIcon", ctypes.c_int),
                    ("szPath", wintypes.WCHAR * 260)]
    info = StockInfo()
    info.cbSize = ctypes.sizeof(info)
    if shell32.SHGetStockIconInfo(stock_id, 0x4000, ctypes.byref(info)) < 0:
        return None
    return image_list_image(info.iSysImageIndex)


_CATEGORY_ART_READY = False


def prepare_category_artwork(provider):
    global _CATEGORY_ART_READY
    if _CATEGORY_ART_READY:
        return
    images = {}
    names = {"documents": "shell:Personal", "images": "shell:My Pictures",
             "media": "shell:My Music", "work": "shell:Libraries",
             "star": "shell:Favorites"}
    for key, name in names.items():
        image = namespace_image(name)
        if image is not None and not image.isNull():
            images[key] = QPixmap.fromImage(image)
    images["folders"] = provider.get(os.environ.get("WINDIR", r"C:\Windows"), 256)
    images["code"] = provider.get(os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "System32", "WindowsPowerShell", "v1.0", "powershell.exe"), 256)
    # SIID_ZIPFILE=105，取系统压缩目录图标，不为分类创建真实文件。
    image = stock_image(105)
    images["archives"] = QPixmap.fromImage(image) if image is not None else images["folders"]
    image = stock_image(55)
    images["other"] = QPixmap.fromImage(image) if image is not None else images["folders"]
    set_native_icons(images)
    _CATEGORY_ART_READY = True


def normalize_entry_image(image):
    """部分网页图标在 256px 画布中只有十几像素，先去掉异常留白再居中缩放。"""
    image = image.convertToFormat(QImage.Format_ARGB32)
    width, height = image.width(), image.height()
    alpha = image.constBits().asstring(image.byteCount())[3::4]
    occupied = [(y, alpha[y * width:(y + 1) * width]) for y in range(height)
                if any(alpha[y * width:(y + 1) * width])]
    if occupied:
        left = min(next(x for x, value in enumerate(row) if value) for _, row in occupied)
        right = max(width - 1 - next(x for x, value in enumerate(reversed(row)) if value) for _, row in occupied)
        top, bottom = occupied[0][0], occupied[-1][0]
        if right - left + 1 < width * .5 and bottom - top + 1 < height * .5:
            crop = QRect(left, top, right - left + 1, bottom - top + 1).adjusted(-2, -2, 2, 2)
            image = image.copy(crop.intersected(image.rect()))
            image = image.scaled(112, 112, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    if image.width() > 128 or image.height() > 128:
        # 56px 内容图标保留两倍像素，避免缓存都持有 256px 原图。
        image = image.scaled(128, 128, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return image


def entry_image(path):
    """供后台面板图标任务使用，上游的大图标提取返回 QImage 后再交给界面。"""
    ole = ctypes.windll.ole32
    initialized = ole.CoInitialize(None) >= 0
    try:
        real = resolve_lnk_target(path) or path if path.lower().endswith(".lnk") else path
        handle = None
        if real.lower().endswith((".exe", ".dll", ".ico")) and os.path.exists(real):
            handle = extract_hicon(real, 128)
        if not handle:
            handle = extract_shell_hicon(path, 256)
        image = hicon_to_qimage(handle) if handle else None
        return normalize_entry_image(image) if image is not None else None
    finally:
        if initialized:
            ole.CoUninitialize()


class Dock(QWidget):
    """悬浮在桌面底部的 Dock 图标栏。"""

    running_ready = pyqtSignal(object)     # 后台线程扫描完进程后回传结果

    def __init__(self, cfg, tray=None, preview=False):
        super(Dock, self).__init__(None)
        self.cfg = cfg
        self.tray = tray
        self.preview = preview
        self.icons = IconProvider()
        self._exe_cache = {}
        self._category_signature = None
        self.organizer = None
        self.desktop_manager = None
        self.recycle_bin = None
        self.file_actions = FileActions(self)
        self.entry_drag = EntryDrag(self)
        self.category_panel = None
        self.category_manager = None
        self.search_bar = None
        self._drop_index = -1
        self.setAcceptDrops(True)

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool
                            | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setMouseTracking(True)
        self.setWindowTitle(APP_TITLE)

        self.base_icon = int(cfg["icon_size"])
        self.ui_mult = self._ui_mult()
        self.icon_size = self._scaled(self.base_icon)
        self.font_pt = max(8, int(round(9 * self.ui_mult)))
        self.prepare_label_font()
        self.pad_x = int(self.icon_size * 0.36)
        self.pad_y = int(self.icon_size * 0.34)
        self.gap_ratio = 0.26
        self.max_scale = 1.42
        self.corner_n = 4.0            # 超椭圆圆角指数（越大越"方"，2=正圆）
        self.mouse_x = -99999.0
        self.mouse_smooth = -99999.0   # 保留预览入口的鼠标状态
        self.stretch = 0.0             # 当前局部放大进度，不再驱动玻璃鼓包
        self.stretch_target = 0.0
        self.label_alpha = 0.0         # 名称气泡的淡入淡出
        self.spec_x = -99999.0
        self.spec_alpha = 0.0
        self.spec_target = 0.0
        self.hover_index = -1
        self.pressed = -1
        self.drag_idx = -1
        self.drag_moved = False
        self.drag_from_x = 0.0
        self.drag_start_pos = QPoint()
        self._drag_snapshot = None
        self.items = []
        self.cur = []
        self.tgt = []
        self.pops = []
        self.rects = []
        self.running = set()
        self.backdrop = None          # 模糊后的背景画面
        self.backdrop_ok = None       # 是否支持屏幕捕获排除
        self._hover_backdrop_pending = False
        self._sys_light = system_is_light()   # 缓存的系统深浅色状态
        self.label_below = False      # 名称是否画在玻璃条下方（贴屏幕顶部时为 True）
        self._last_move_calc = 0.0    # 上次重算目标尺寸的时间（鼠标事件节流用）
        self._frame_time = None      # 动画按实际经过时间插值，掉帧不改变速度
        self._split_flags = []
        self._logged_once = False

        self.timer = QTimer(self)
        self.timer.setInterval(16)     # ~60fps
        self.timer.timeout.connect(self._tick)

        self.proc_timer = QTimer(self)
        self.proc_timer.setInterval(8000)
        self.proc_timer.timeout.connect(self.refresh_running)
        self.running_ready.connect(self._apply_running)
        self._proc_busy = False

        self.geo_timer = QTimer(self)
        self.geo_timer.setInterval(2500)
        self.geo_timer.timeout.connect(self.check_position)

        # 定期重新抓一次背后的画面，让毛玻璃里的内容保持新鲜。
        # 具体间隔由"背景抓取频率"设置决定，智能模式下平时几乎不抓，
        # 只在显示、鼠标靠近、改设置时抓一次。
        self.blur_timer = QTimer(self)
        self.blur_timer.setInterval(BLUR_INTERVAL["smart"])
        self.blur_timer.timeout.connect(self.refresh_backdrop)

        self._build_items()
        self.reposition()

    def is_light(self):
        """当前是不是浅色系（文字/小圆点用深色）。光感模式也算浅色系。"""
        t = str(self.cfg.get("theme", "auto"))
        if t in ("light", "gloss", "fog"):
            return True
        if t == "dark":
            return False
        return bool(self._sys_light)

    def theme_colors(self):
        """按当前模式返回整套配色与外观参数。

        公共字段：
          tint / tint_scale / tint_floor  玻璃底色和它的浓度曲线
          grad / hl                       竖向渐变与顶部高光（会被合成为一条）
          border / border_w               描边颜色与粗细
          corner                          圆角半径占条高的比例
          tile / tile_*                   图标是否带圆角底板（iOS 那种）
        """
        t = str(self.cfg.get("theme", "auto"))
        if t in ("gloss", "fog"):
            # ── 光感模式：玻璃上有一道明显的光照（上方光源 + 顶边亮线 + 斜向光斑） ──
            #     不做白色图标底板，图标保持原样，整体是"湿润的玻璃"质感
            return dict(
                light=True,
                gloss=True,
                tint=QColor(238, 243, 252),
                tint_scale=0.62,          # 比浅色模式透一点，光才透得出来
                tint_floor=36,
                fg=QColor(40, 46, 62),
                # 上亮 → 中暗 → 下亮的经典光泽曲线
                grad=[(0.00, 150), (0.18, 96), (0.52, 40), (0.80, 30), (1.00, 74)],
                hl=[(0.00, 118), (0.42, 34), (1.00, 0)],
                border=QColor(255, 255, 255, 178),
                border_w=1.2,
                corner=0.44,
                spec=150,                          # 跟随鼠标的高光更强（就是"光照"）
                spec_wide=1.9,                     # 光斑更宽更柔
                shadow=QColor(255, 255, 255, 190),
                label_bg=QColor(250, 251, 255, 234),
                label_border=QColor(255, 255, 255, 176),
                label_fg=QColor(34, 40, 56, 246),
                tile=False,
            )
        if self.is_light():
            return dict(
                light=True,
                tint=QColor(247, 247, 251),        # 玻璃底色（偏白）
                tint_scale=0.70,
                tint_floor=45,
                fg=QColor(34, 34, 44),             # 小圆点/提示文字
                grad=[(0.00, 88), (0.30, 48), (0.72, 26), (1.00, 60)],
                hl=[(0.00, 150), (0.55, 48), (1.00, 0)],
                border=QColor(88, 88, 104, 46),
                border_w=1.0,
                corner=0.40,
                spec=86,
                shadow=QColor(255, 255, 255, 150),
                label_bg=QColor(250, 250, 253, 238),
                label_border=QColor(80, 80, 96, 42),
                label_fg=QColor(28, 28, 38, 244),
                tile=False,
            )
        return dict(
            light=False,
            tint=QColor(16, 16, 20),
            tint_scale=1.0,
            tint_floor=0,
            fg=QColor(255, 255, 255),
            grad=[(0.00, 30), (0.28, 12), (0.70, 6), (1.00, 18)],
            hl=[(0.00, 76), (0.55, 20), (1.00, 0)],
            border=QColor(255, 255, 255, 78),
            border_w=1.0,
            corner=0.40,
            spec=70,
            shadow=QColor(0, 0, 0, 130),
            label_bg=QColor(16, 16, 20, 228),
            label_border=QColor(255, 255, 255, 62),
            label_fg=QColor(255, 255, 255, 242),
            tile=False,
        )

    def apply_theme_follow(self):
        """跟随系统模式下，定期检查系统有没有切换深浅色。"""
        if str(self.cfg.get("theme", "auto")) != "auto":
            return
        cur = system_is_light()
        if cur != self._sys_light:
            self._sys_light = cur
            if self.search_bar:
                self.search_bar.update_theme()
            self.update()

    # ---------------- 尺寸与布局 ----------------
    def _ui_mult(self):
        """Windows 缩放适配。

        Qt 在某些机器上不会自动启用高 DPI 缩放，这时窗口坐标就等于物理像素，
        图标会显得偏小。这里用 Windows 自己的缩放比例补一次：
            目标物理尺寸 = 配置值 × Windows缩放
        如果 Qt 已经缩放过了（devicePixelRatio>1），就不再重复放大。
        """
        try:
            qt = float(QGuiApplication.primaryScreen().devicePixelRatio())
        except Exception:
            qt = 1.0
        if qt <= 0.01:
            qt = 1.0
        try:
            dpi = float(user32.GetDpiForSystem())
        except Exception:
            dpi = 96.0
        win = max(1.0, dpi / 96.0)
        m = win / qt
        return m if 0.1 < m < 4.0 else 1.0

    def _scaled(self, v):
        return max(20, int(round(v * self.ui_mult)))

    def bar_h(self):
        return self.icon_size + self.pad_y * 2

    def sep_width(self):
        """分隔符竖条本身的宽度（很窄）。"""
        return max(7.0, self.icon_size * 0.17)

    def sep_gap_width(self):
        """隔断模式下，被切开的玻璃条之间留出的空隙宽度。"""
        return max(14.0, self.icon_size * 0.42)

    def is_split_sep(self, i):
        """第 i 项是不是"隔断分隔符"：本身是分隔符，且左右两边都还有图标。

        结果在 _compute_split_flags() 里一次算好，避免每次查询都切片扫描列表
        （鼠标事件里会频繁调用，性能关键）。
        """
        flags = getattr(self, "_split_flags", None)
        if not flags or not (0 <= i < len(flags)):
            return False
        return flags[i]

    def _compute_split_flags(self):
        n = len(self.items)
        first_icon = -1
        last_icon = -1
        for i, it in enumerate(self.items):
            if not it.get("sep"):
                if first_icon < 0:
                    first_icon = i
                last_icon = i
        on = bool(self.cfg.get("sep_split", True))
        self._split_flags = [
            bool((on or self.items[i].get("system_separator")) and self.items[i].get("sep")
                 and first_icon >= 0 and first_icon < i < last_icon)
            for i in range(n)
        ]

    def item_slot_width(self, i):
        """第 i 项在排版里占的宽度。"""
        if not (0 <= i < len(self.items)):
            return float(self.icon_size)
        if not self.items[i].get("sep"):
            return float(self.icon_size)
        if self.is_split_sep(i):
            return self.sep_gap_width()
        return self.sep_width()

    def is_vertical(self):
        return self.cfg.get("position", "bottom") in ("left", "right")

    def axis_length(self):
        """排布和动画沿主轴计算；竖排复用原横排的鱼眼插值。"""
        return self.height() if self.is_vertical() else self.width()

    def axis_transform(self):
        # 主轴 x 映射到屏幕 y，侧向 y 映射到屏幕 x；只转换几何，不旋转图标。
        return QTransform(0, 1, 1, 0, 0, 0) if self.is_vertical() else QTransform()

    def window_to_axis(self, point):
        return QPointF(point.y(), point.x()) if self.is_vertical() else QPointF(point)

    def window_rect(self, rect):
        return self.axis_transform().mapRect(rect)

    def side_label_width(self):
        return int(220 * self.ui_mult)

    def head_room(self):
        # 为朝屏幕内部放大的图标和名称预留透明区域；顶部/左侧镜像到下方。
        if self.bump_down():
            return 0
        room = int(max(self.icon_size * 0.55, self.bump_max())) + 8
        if self.cfg.get("show_name", True) and not self.label_below:
            room += (self.side_label_width() if self.is_vertical() else self.label_height()) + 8
        return room

    def bump_down(self):
        """顶部/左侧向正侧向放大，底部/右侧向负侧向放大。"""
        return bool(self.label_below)

    def bump_max(self):
        return self.icon_size * (self.hover_scale() - 1.0)

    def hover_scale(self):
        """旧低/中/高设置改为局部放大强度，默认峰值 1.42 倍。"""
        level = str(self.cfg.get("bump_level", "mid"))
        return next((scale for key, _, scale in BUMP_LEVELS if key == level), self.max_scale)

    def foot_room(self):
        """玻璃条【下方】留出的透明空间。

        顶部/左侧图标向正侧向放大，名称也在同侧，
        所以下方要一次留够；否则会被窗口边缘切掉。
        """
        if not self.bump_down():
            return 0
        grow = int(max(self.icon_size * 0.62, self.bump_max())) + 8   # 包含点击回弹的空间
        room = grow
        if self.cfg.get("show_name", True):
            label_room = self.side_label_width() if self.is_vertical() else self.label_height()
            room = max(room, int(label_room + grow + 6))
        return room

    def label_top_y(self, bar):
        """名称放在放大区之外，避免图标经过时推着气泡上下移动。"""
        if self.label_below:
            return bar.bottom() + self.icon_size * 0.32 + 8.0
        return 2.0

    def prepare_label_font(self):
        """窗口出现前完成中文文字引擎的首次绘制，避免第一次悬停时阻塞动画。"""
        self._label_font = QFont("Microsoft YaHei UI", self.font_pt)
        self._label_metrics = QFontMetrics(self._label_font)
        sample = QImage(240, 48, QImage.Format_ARGB32_Premultiplied)
        sample.fill(Qt.transparent)
        painter = QPainter(sample)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        painter.setFont(self._label_font)
        painter.drawText(sample.rect(), Qt.AlignCenter, "应用 文档 · 0123 Aa")
        painter.end()

    def label_height(self):
        fm = self._label_metrics
        return float(fm.height() + 10)

    def side_room(self):
        """为局部鱼眼增加的总宽度预留主轴两端空间，不在动画中改变窗口尺寸。"""
        return int(self.icon_size * 0.55) + 4

    def side_expand(self):
        # 底座与图标使用同一份插值结果，避免两套动画互相拉扯。
        return sum(max(0.0, width - self.icon_size)
                   for item, width in zip(self.items, self.cur)
                   if not item.get("sep")) / 2.0

    def bar_rect_f(self):
        """底座保持固定高度，仅随附近图标增宽，整排中心不变。"""
        e = self.side_expand()
        left = self.side_room() - e
        return QRectF(left, float(self.head_room()),
                      float(self.axis_length()) - 2.0 * left, float(self.bar_h()))

    def total_size(self):
        n = len(self.items)
        if n == 0:
            w = max(330, int(self.icon_size * 5.1))
        else:
            gap = self.icon_size * self.gap_ratio
            body = sum(self.item_slot_width(i) for i in range(n))
            w = int(self.pad_x * 2 + body + (n - 1) * gap)
        # 左右各留一条透明带，给"外扩"用
        h = int(self.bar_h() + self.head_room() + self.foot_room())
        length = w + self.side_room() * 2
        return QSize(h, length) if self.is_vertical() else QSize(length, h)

    def _build_items(self):
        self.layout_position()
        self.items = []
        self.pressed = self.drag_idx = -1
        for config_index, it in enumerate(self.cfg["items"]):
            if it.get("sep"):
                self.items.append({"sep": True, "path": "", "name": "",
                                   "pixmap": None, "exe": "", "config_index": config_index})
                continue
            path = it["path"]
            if path not in self._exe_cache:
                self._exe_cache[path] = self._exe_name(path)
            self.items.append({
                "path": path,
                "name": it.get("name") or os.path.splitext(os.path.basename(path))[0],
                "pixmap": self.icons.get(path, max(96, int(self.icon_size * 2.0))),
                "exe": self._exe_cache[path],
                "config_index": config_index,
            })
        if self.organizer is not None:
            groups = self.organizer.groups()
            self._category_signature = self._organizer_signature(groups)
            categories = list(self.organizer.state["categories"])
            categories.append({"id": "__uncategorized__", "name": "未分类", "icon": "other"})
            separators = separator_positions(self.organizer.state)
            screen = self.screen() or QApplication.primaryScreen()
            available = ((screen.availableGeometry().height() if self.is_vertical()
                          else screen.availableGeometry().width()) if screen else 1920) - self.search_extent(expanded=True)
            separator_width = self.sep_gap_width() if self.cfg.get("sep_split", True) else self.sep_width()
            system_room = self.icon_size * 2.7 + self.sep_gap_width() + self.icon_size * self.gap_ratio
            slots = max(2, int((available - 100 - system_room) / (self.icon_size * 1.35)) - len(self.items))
            while True:
                shown = list(categories) if len(categories) <= slots else categories[:slots - 1]
                if len(shown) < len(categories):
                    shown.append({"id": "__more__", "name": "更多分类", "icon": "other"})
                lines = sum(category["id"] in separators for category in shown[:-1])
                lines += bool(self.items and "__before_categories__" in separators)
                needed = (100 + system_room + (len(self.items) + len(shown)) * self.icon_size * 1.35
                          + lines * (separator_width + self.icon_size * self.gap_ratio))
                if needed <= available or slots <= 2:
                    break
                slots -= 1
            if ("__before_categories__" in separators and self.items
                    and not self.items[-1].get("sep")):
                self.items.append({"sep": True, "path": "", "name": "", "pixmap": None,
                                   "exe": "", "config_index": None, "category_separator": True,
                                   "separator_after": "__before_categories__"})
            for position, category in enumerate(shown):
                cid = category["id"]
                count = len(groups.get(cid, []))
                self.items.append({"path": "", "name": category["name"] + (" · %d" % count if cid != "__more__" else ""),
                                   "pixmap": self._category_artwork(category),
                                   "exe": "", "category": cid, "config_index": None})
                if cid in separators and position < len(shown) - 1:
                    # 只在配置的位置划区，继续沿用原有分隔符绘制与动画。
                    self.items.append({"sep": True, "path": "", "name": "", "pixmap": None,
                                       "exe": "", "config_index": None, "category_separator": True,
                                       "separator_after": cid})
        if self.items:
            self.items.append({"sep": True, "system_separator": True, "path": "", "name": "",
                               "pixmap": None, "exe": "", "config_index": None})
        self.items.append({"computer": True, "path": "", "name": "此电脑", "exe": "",
                           "pixmap": computer_pixmap(max(96, int(self.icon_size * 2)), self.is_light()),
                           "config_index": None})
        self.items.append({"trash": True, "path": "", "name": "回收站", "exe": "",
                           "pixmap": None, "config_index": None})
        self._trash_changed(repaint=False)
        n = len(self.items)
        self.cur = []
        self.tgt = []
        self.pops = [0.0] * n
        self._compute_split_flags()
        if n == 0:
            self.stretch_target = 0.0
            self.stretch = 0.0
        self.resize(self.total_size())
        self._recalc(uniform=True)
        self.refresh_running()

    @staticmethod
    def _exe_name(path):
        real = path
        if path.lower().endswith(".lnk"):
            real = resolve_lnk_target(path) or path
        base = os.path.basename(real)
        return base.lower()

    def setup_recycle_bin(self):
        from recycle_bin import RecycleBin
        self.recycle_bin = RecycleBin(self)
        self.recycle_bin.changed.connect(self._trash_changed)
        self.recycle_bin.error.connect(lambda message: self.organizer_message("回收站", message))
        QApplication.instance().aboutToQuit.connect(self.recycle_bin.stop)
        self._trash_changed()

    def _trash_changed(self, repaint=True):
        service = self.recycle_bin
        count = service.count if service else None
        for item in self.items:
            if not item.get("trash"):
                continue
            item["name"] = ("正在处理…" if service and service.busy else
                            "回收站" if count is None else "回收站 · 空" if count == 0 else
                            "回收站 · %d 项" % count)
            pixmap = trash_pixmap(max(96, int(self.icon_size * 2)), bool(count), self.is_light())
            if item["pixmap"] is None or item["pixmap"].cacheKey() != pixmap.cacheKey():
                item["pixmap"] = pixmap
                item.pop("_scaled", None)
        if repaint:
            self.update(self.repaint_rect())

    def _recalc(self, uniform=False, light=False):
        n = len(self.items)
        if not n:
            self.tgt, self.cur, self.rects = [], [], []
            return
        S = float(self.icon_size)
        gap = S * self.gap_ratio
        rest = []
        x = self.side_room() + float(self.pad_x)
        for i in range(n):
            width = self.item_slot_width(i)
            rest.append(x + width / 2.0)
            x += width + gap
        pointer = self.mouse_x
        # 将当前排布上的鼠标映射回静态排布。图标让位后仍指向原目标，
        # 不拿不断移动的中心反复求解，避免停住鼠标后尺寸来回振荡。
        if not uniform and len(self.rects) == n and pointer > -9000:
            centers = [rect[0] for rect in self.rects]
            if pointer <= centers[0]:
                pointer = rest[0] + pointer - centers[0]
            elif pointer >= centers[-1]:
                pointer = rest[-1] + pointer - centers[-1]
            else:
                for i in range(1, n):
                    if pointer <= centers[i]:
                        fraction = (pointer - centers[i-1]) / (centers[i] - centers[i-1])
                        pointer = rest[i-1] + fraction * (rest[i] - rest[i-1])
                        break
        radius = S * 2.1
        active = not uniform and self.cfg['magnify'] and pointer > -9000
        amplitude = self.hover_scale() - 1.0
        self.tgt = []
        for i, item in enumerate(self.items):
            width = self.item_slot_width(i)
            if active and not item.get('sep'):
                distance = abs(pointer - rest[i])
                if distance < radius:
                    width = S * (1.0 + amplitude * .5 * (1.0 + math.cos(math.pi * distance / radius)))
            self.tgt.append(width)
        # 不再按总宽度归一化，远处图标始终保持原尺寸。
        if uniform or len(self.cur) != n:
            self.cur = list(self.tgt)
        if not light:
            self._layout()
            self.update(self.repaint_rect())

    def repaint_rect(self):
        """需要重绘的区域。比整个窗口小一圈，能明显省下绘制开销。

        注意：只要开着名称显示，就必须**无条件**把名称那一条也圈进来。
        名称画在玻璃条外面的透明区，如果只在"名称正在显示"时才重绘那一块，
        淡出的最后一帧就不会被擦掉，屏幕上的旧名称会一直残留。
        """
        if self.is_vertical():
            # 包含水平名称气泡与侧向放大区，淡出最后一帧也必须擦除。
            return self.rect()
        bar = self.bar_rect_f()
        grow = self.icon_size * 0.68 + 4
        r = QRectF(bar).adjusted(-self.side_room() - 3,
                               -grow if not self.bump_down() else -3,
                               self.side_room() + 3,
                               grow if self.bump_down() else 4)
        if self.cfg.get("show_name", True):
            th = self.label_height()
            ly = self.label_top_y(bar)
            r = r.united(QRectF(0.0, ly, float(self.width()), th))
        return r.toAlignedRect()

    # ---------------- 外形 ----------------
    def _corner_sets_for(self, r):
        """缓存的超椭圆（苹果式连续曲率）圆角采样点。

        普通圆角用的是正圆，圆弧和直边的接缝处曲率会突变，看着有一点"折"；
        超椭圆的曲率在接缝处正好为 0，所以过渡是连续的 —— 这就是苹果圆角更顺滑的原因。
        每段的圆角完全一样，所以只算一次缓存起来（性能关键）。
        """
        key = (round(r, 2), round(self.corner_n, 2))
        if getattr(self, "_corn_key", None) != key:
            e = 2.0 / max(2.01, self.corner_n)
            sets = {}
            for name, t0, t1 in (("tr", -math.pi / 2.0, 0.0), ("br", 0.0, math.pi / 2.0),
                                 ("bl", math.pi / 2.0, math.pi), ("tl", math.pi, math.pi * 1.5)):
                lst = []
                for i in range(1, 17):
                    t = t0 + (t1 - t0) * (i / 16.0)
                    cc, ss = math.cos(t), math.sin(t)
                    lst.append((math.copysign(abs(cc) ** e, cc),
                                math.copysign(abs(ss) ** e, ss)))
                sets[name] = lst
            self._corn_key = key
            self._corn_sets = sets
        return self._corn_sets

    def _add_corner_cached(self, path, cx, cy, r, name):
        for dx, dy in self._corn_sets[name]:
            path.lineTo(cx + dx * r, cy + dy * r)

    def corner_ratio(self):
        """圆角半径占条高的比例。光感模式更圆一些。"""
        t = str(self.cfg.get("theme", "auto"))
        return 0.44 if t in ("gloss", "fog") else 0.40

    def corner_radius(self):
        return max(8.0, min(self.bar_h() * self.corner_ratio(), self.bar_h() / 2.0))

    def shape_segments(self):
        """把玻璃背景按"隔断分隔符"切成若干段，返回 [(x_left, x_right), ...]。

        只有夹在两个图标中间的分隔符才会隔断；放在最左/最右的不生效。
        """
        bar = self.bar_rect_f()
        n = len(self.items)
        if n == 0 or not self.rects:
            return [(bar.left(), bar.right())]
        segs = []
        start = bar.left()
        gap_w = self.sep_gap_width()
        for i in range(n):
            if not self.is_split_sep(i):
                continue
            if i >= len(self.rects):
                continue
            c = self.rects[i][0]
            segs.append((start, c - gap_w / 2.0))
            start = c + gap_w / 2.0
        segs.append((start, bar.right()))
        # 太窄的段直接丢掉，避免画出怪东西
        return [(a, b) for (a, b) in segs if b - a > 12.0]

    def _one_shape(self, x_l, x_r, top0, bot):
        """保留原连续圆角和玻璃材质，悬停不再把边缘顶出鼓包。"""
        width = x_r - x_l
        if width <= 2.0:
            return None
        r = min(self.corner_radius(), width / 2.0 - .5, (bot - top0) / 2.0)
        self._corner_sets_for(r)
        path = QPainterPath()
        path.moveTo(x_l + r, top0)
        path.lineTo(x_r - r, top0)
        self._add_corner_cached(path, x_r - r, top0 + r, r, 'tr')
        path.lineTo(x_r, bot - r)
        self._add_corner_cached(path, x_r - r, bot - r, r, 'br')
        path.lineTo(x_l + r, bot)
        self._add_corner_cached(path, x_l + r, bot - r, r, 'bl')
        path.lineTo(x_l, top0 + r)
        self._add_corner_cached(path, x_l + r, top0 + r, r, 'tl')
        path.closeSubpath()
        return path

    def shape_paths(self):
        """整条玻璃的全部形状（隔断模式下会是好几段）。"""
        bar = self.bar_rect_f()
        top0 = bar.top()
        bot = bar.bottom()
        out = []
        for (a, b) in self.shape_segments():
            pa = self._one_shape(a, b, top0, bot)
            if pa is not None:
                out.append(pa)
        return out

    def shape_path(self):
        """兼容用：返回第一段形状（没有隔断时就等于整条）。"""
        ps = self.shape_paths()
        return ps[0] if ps else QPainterPath()

    def _layout(self):
        if not self.items:
            self.rects = []
            return
        bar = self.bar_rect_f()
        base_y = bar.top() + self.pad_y if self.bump_down() else bar.bottom() - self.pad_y
        gap = float(self.icon_size) * self.gap_ratio
        widths = [self.cur[i] if i < len(self.cur) else self.item_slot_width(i)
                  for i in range(len(self.items))]
        # 固定间距、整排居中，放大的尺寸自然推开相邻图标与分隔符。
        # 所有坐标和底座宽度来自同一帧，既不挤小远处图标，也不额外摊开间距。
        length = sum(widths) + gap * (len(widths) - 1)
        x = (self.axis_length() - length) / 2.0
        self.rects = []
        for item, width in zip(self.items, widths):
            self.rects.append((x + width / 2.0, width, width, base_y, bool(item.get('sep'))))
            x += width + gap

    # ---------------- 位置 ----------------
    def search_extent(self, expanded=False):
        if self.organizer is None:
            return 0
        return int(round((220 if expanded and not self.is_vertical() else 40) * self.ui_mult)) + 12

    def sync_search_geometry(self):
        if self.search_bar is None:
            return
        width = int(round(40 * self.ui_mult))
        height = int(round(40 * self.ui_mult))
        bar = self.window_rect(QRectF(self.side_room(), self.head_room(),
                                     self.axis_length() - 2 * self.side_room(), self.bar_h())).toAlignedRect()
        area = (self.screen() or QApplication.primaryScreen()).availableGeometry()
        if self.is_vertical():
            x = self.x() + bar.center().x() - width // 2
            y = self.y() - height - 12
        else:
            x = self.x() + self.width() + 12
            y = self.y() + bar.center().y() - height // 2
        x = max(area.left() + 6, min(x, area.right() + 1 - width - 6))
        y = max(area.top() + 6, min(y, area.bottom() + 1 - height - 6))
        self.search_bar.set_anchor(QRect(x, y, width, height))

    def layout_position(self):
        """返回玻璃靠屏幕边的侧向位置，并决定放大朝哪一侧。"""
        scr = QGuiApplication.primaryScreen()
        geo = scr.availableGeometry() if scr else None
        if geo is None:
            return 100, QRectF(0, 0, 1920, 1080)
        mode = str(self.cfg.get("position", "bottom"))
        margin = int(self.cfg.get("bottom_margin", 6))
        if mode in ("left", "right"):
            self.label_below = mode == "left"
            bar_side = geo.left() + margin if mode == "left" else geo.right() + 1 - margin - self.bar_h()
            return bar_side, geo
        if mode == "top":
            bar_top = geo.top() + margin
        elif mode == "custom":
            off = int(self.cfg.get("custom_bottom", 200))
            bar_top = geo.bottom() + 1 - off - self.bar_h()
        else:
            bar_top = geo.bottom() + 1 - margin - self.bar_h()
        # 上方空间不够放名称时，把名称改放到玻璃条下面
        need_above = int(self.icon_size * 0.55) + 8
        if self.cfg.get("show_name", True):
            need_above += int(self.label_height() + 8)
        self.label_below = bool(bar_top - geo.top() < need_above)
        return bar_top, geo

    def target_pos(self):
        bar_top, geo = self.layout_position()
        if self.is_vertical():
            x = bar_top - self.head_room()
            y = geo.top() + (geo.height() - self.height() + self.search_extent()) // 2
            return QPoint(int(x), int(y))
        x = geo.left() + (geo.width() - self.width() - self.search_extent()) // 2
        # 提前留出搜索展开的空间，点击时主 Dock 不移动，也不重算鱼眼布局。
        x = min(x, geo.right() + 1 - self.width() - self.search_extent(expanded=True) - 8)
        y = bar_top - self.head_room()
        return QPoint(int(x), int(y))

    def reposition(self):
        # 必须先算位置（这一步会决定名称放上面还是下面），
        # 再按算好的结果调整窗口大小，最后才移动。
        # 顺序反了的话，换位置的第一次会用到旧的名称方向，位置就会错一格。
        self.layout_position()
        want = self.total_size()
        if want != self.size():
            self.resize(want)
        self.move(self.target_pos())
        # 窗口尺寸 / 名称方向可能变了，图标坐标必须跟着重算，
        # 否则会出现"玻璃条位置对了、图标还停在旧位置"的现象
        self.cur = []
        self.tgt = []
        self._recalc(uniform=True)

        self.sync_search_geometry()

    def set_position(self, mode):
        if self.search_bar:
            self.search_bar.collapse(animate=False)
        if self.category_panel:
            self.category_panel.hide()
        self.cfg["position"] = mode
        save_config(self.cfg)
        # 换轴时清除旧鼠标坐标与拖动状态，避免第一次悬停沿旧方向放大。
        self.timer.stop()
        self.mouse_x = self.mouse_smooth = self.spec_x = -99999.0
        self.stretch = self.stretch_target = self.spec_alpha = self.spec_target = self.label_alpha = 0.0
        self.hover_index = self.pressed = self.drag_idx = self._drop_index = -1
        self.setCursor(Qt.ArrowCursor)
        self.backdrop = None
        self._build_items()
        self.reposition()
        self.refresh_backdrop()
        self.update()

    def add_position_menu(self, menu):
        positions = menu.addMenu(T("窗口位置"))
        if isinstance(menu, ThemedMenu):
            positions.menuAction().setIcon(menu.glyph("location"))
        group = QActionGroup(positions)
        group.setExclusive(True)
        for label, mode in POSITIONS:
            if mode == "custom":
                continue
            action = positions.addAction(T(label))
            action.setCheckable(True)
            action.setChecked(self.cfg.get("position", "bottom") == mode)
            group.addAction(action)
            action.triggered.connect(lambda _=False, value=mode: self.set_position(value))

    def apply_layer(self):
        """把窗口放到指定层级。

        置底用 HWND_BOTTOM：Dock 会退到所有普通窗口的下面（和桌面同级），
        这样最大化窗口、全屏应用都不会被它挡住；因为有定时重设，
        其它窗口激活改变 z 序后它会自动再沉下去。
        """
        if self.preview or not self.isVisible():
            return
        if self.search_bar and (self.search_bar.expanded or self.search_bar._reveal > 0):
            # 输入期间保持搜索窗口的焦点和层级，收起后再恢复置底策略。
            return
        try:
            user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND,
                                            ctypes.c_int, ctypes.c_int,
                                            ctypes.c_int, ctypes.c_int, ctypes.c_uint]
            user32.SetWindowPos.restype = wintypes.BOOL
            hwnd = wintypes.HWND(int(self.winId()))
            layer = str(self.cfg.get("layer", "bottom"))
            target = HWND_TOPMOST if layer == "top" else HWND_BOTTOM
            user32.SetWindowPos(hwnd, wintypes.HWND(target), 0, 0, 0, 0,
                                SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE)
            if self.search_bar and self.search_bar.isVisible() and not self.search_bar.expanded:
                user32.SetWindowPos(wintypes.HWND(int(self.search_bar.winId())), wintypes.HWND(target),
                                    0, 0, 0, 0, SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE)
        except Exception:
            log("apply_layer 失败: " + traceback.format_exc())

    def check_position(self):
        if not self.isVisible():
            return
        was_below = self.label_below
        self.layout_position()          # 顺带更新 label_below
        size = self.total_size()
        changed = size != self.size()
        if changed:
            self.resize(size)
        want = self.target_pos()
        moved = want != self.pos()
        if moved:
            self.move(want)
        # 尺寸或名称方向变了，图标坐标要重算（否则图标会停在旧位置）
        if changed or self.label_below != was_below:
            self.cur = []
            self.tgt = []
            self._recalc(uniform=True)
        self.apply_theme_follow()
        self.apply_layer()
        if changed or moved or self.label_below != was_below:
            self.sync_search_geometry()
            self.refresh_backdrop()

    # ---------------- 运行状态 ----------------
    def _tracked_executables(self):
        return {item["exe"] for item in self.items
                if item.get("exe", "").endswith((".exe", ".com", ".scr"))}

    def refresh_running(self):
        """扫描"哪些程序正在运行"。

        枚举系统进程放在后台线程，避免与界面动画争用主线程；
        扫完用信号把结果传回来，只更新相关应用的标记。
        """
        needed = (not self.preview and self.isVisible()
                  and self.cfg["running_dots"] and bool(self._tracked_executables()))
        if not needed:
            self.proc_timer.stop()
            if self.running:
                self.running = set()
                if self.isVisible():
                    self.update(self.repaint_rect())
            return
        if not self.proc_timer.isActive():
            self.proc_timer.start()
        if getattr(self, "_proc_busy", False):
            return
        self._proc_busy = True
        threading.Thread(target=self._scan_procs, daemon=True).start()

    def _scan_procs(self):
        try:
            names = get_running_exe_names()
        except Exception:
            names = set()
        try:
            self.running_ready.emit(names)
        except Exception:
            pass

    def _apply_running(self, names):
        self._proc_busy = False
        # 其他应用的进程变化不影响 Dock，不因此唤醒绘制。
        names = (set(names) & self._tracked_executables()
                 if self.cfg["running_dots"] and self.isVisible() else set())
        if names != self.running:
            self.running = names
            if self.isVisible():
                self.update(self.repaint_rect())

    # ---------------- 动画 ----------------
    def _tick(self):
        now = time.perf_counter()
        dt = now - self._frame_time if self._frame_time is not None else .016
        self._frame_time = now
        moving = False
        # 无超调的时间插值：入场稍快、离开稍柔和；鼠标中途改向直接接续当前状态。
        for i in range(len(self.cur)):
            delta = self.tgt[i] - self.cur[i]
            if abs(delta) > .06:
                tau = .060 if delta > 0 else .085
                self.cur[i] += delta * (1.0 - math.exp(-dt / tau))
                moving = True
            elif delta:
                self.cur[i] = self.tgt[i]
                moving = True
        for i in range(len(self.pops)):
            if self.pops[i] > 0:
                self.pops[i] = max(0.0, self.pops[i] - dt / .18)
                moving = True
        for current, target, tau, epsilon in (
                ('spec_alpha', self.spec_target, .080, .008),
                ('label_alpha', 1.0 if 0 <= self.hover_index < len(self.items) else 0.0, .060, .008)):
            value = getattr(self, current)
            delta = target - value
            if abs(delta) > epsilon:
                setattr(self, current, value + delta * (1.0 - math.exp(-dt / tau)))
                moving = True
            elif delta:
                setattr(self, current, target)
                moving = True
        self.stretch = max((max(0.0, width / self.icon_size - 1.0)
                            for item, width in zip(self.items, self.cur) if not item.get('sep')), default=0.0) / (self.hover_scale() - 1.0)
        if moving:
            self._layout()
        else:
            self.timer.stop()
            self._frame_time = None
            if self._hover_backdrop_pending:
                self._hover_backdrop_pending = False
                if str(self.cfg.get("blur_mode", "smart")) != "off":
                    self.refresh_backdrop()
        # 无放大时鼠标仍可移动柔光；最后一帧也负责擦除已淡出的内容。
        self.update(self.repaint_rect())

    def _kick(self):
        if not self.preview and not self.isVisible():
            return
        if not self.timer.isActive():
            self._frame_time = time.perf_counter()
            self.timer.start()

    # ---------------- 鼠标 ----------------
    def enterEvent(self, e):
        if QApplication.activePopupWidget() is not None:
            return
        # 弹窗关闭可能只有 Enter 而没有 MouseMove，必须更新坐标，不能重新点亮旧位置。
        local = self.mapFromGlobal(e.globalPos() if hasattr(e, "globalPos") else QCursor.pos())
        pos = self.window_to_axis(local)
        bar = self.bar_rect_f()
        idx = self._hit(local)
        near = self.rect().contains(local) and ((bar.top() - 12 <= pos.y() <= bar.bottom() + 12) or idx >= 0)
        self.hover_index = idx if near else -1
        self.mouse_x = self.mouse_smooth = self.spec_x = float(pos.x()) if near else -99999.0
        self.spec_target = self.stretch_target = 1.0 if near else 0.0
        self.setCursor(Qt.PointingHandCursor if self.hover_index >= 0 else Qt.ArrowCursor)
        self._recalc(light=True)
        if self.cfg["glass"] and str(self.cfg.get("blur_mode", "smart")) != "off":
            # 动画先使用已有底图，停稳后合并补抓一次，不占用移入事件和首帧。
            self._hover_backdrop_pending = True
        self._kick()
        super(Dock, self).enterEvent(e)

    def _clear_hover(self):
        """弹窗接管鼠标时也收回旧高亮，不能只等待系统发送 Leave。"""
        self.mouse_x = -99999.0
        self.spec_target = 0.0
        self.stretch_target = 0.0
        self.hover_index = -1
        self.pressed = -1
        self.setCursor(Qt.ArrowCursor)
        QToolTip.hideText()
        self._recalc()
        self._kick()

    def leaveEvent(self, e):
        self._clear_hover()
        super(Dock, self).leaveEvent(e)

    def mouseMoveEvent(self, e):
        if QApplication.activePopupWidget() is not None:
            return
        pos = self.window_to_axis(e.pos())
        self.mouse_x = float(pos.x())
        self.spec_x = float(pos.x())
        # 沿 Dock 拖动排序，拖离玻璃条或按 Shift 时进入虚拟入口拖动。
        if self.pressed >= 0 and e.buttons() & Qt.LeftButton:
            it = self.items[self.pressed]
            if (it.get("path") and not it.get("sep")
                    and (not self.cfg.get("reorder", True) or e.modifiers() & Qt.ShiftModifier
                         or not self.bar_rect_f().adjusted(-16, -30, 16, 30).contains(pos))
                    and (e.pos() - self.drag_start_pos).manhattanLength() > QApplication.startDragDistance()):
                paths = [it["path"]]
                icon = it.get("pixmap") or QPixmap()
                self.pressed = self.drag_idx = -1
                def cancel():
                    self._entry_drag_target(paths, QPoint(), "clear", "pinned")
                    self._restore_drag_order()
                    self._clear_hover()
                def drop(point):
                    if self._entry_drag_target(paths, point, "drop", "pinned"):
                        self._drag_snapshot = None
                        self._clear_hover()
                    else:
                        cancel()
                self.entry_drag.begin(self, paths, icon, e.globalPos(),
                                      lambda point: self._entry_drag_target(paths, point, "hover", "pinned"), drop, cancel)
                return
        # 拖动排序模式：按住左键移动 = 排序
        if self.drag_idx >= 0 and (e.buttons() & Qt.LeftButton):
            if (e.pos() - self.drag_start_pos).manhattanLength() >= QApplication.startDragDistance():
                self.drag_moved = True
            if self.drag_moved:
                if (self.items[self.drag_idx].get("category")
                        and not self.bar_rect_f().adjusted(-16, -30, 16, 30).contains(pos)):
                    return
                if QWidget.keyboardGrabber() is not self:
                    self.grabKeyboard()
                now = time.perf_counter()
                if now - self._last_move_calc < .008:
                    return
                self._last_move_calc = now
                self._drag_reorder(float(pos.x()))
                self.hover_index = self.drag_idx      # 名称气泡跟着被拖的图标
                self._recalc(light=True)
                self._kick()
                super(Dock, self).mouseMoveEvent(e)
                return
        # 只有鼠标进到玻璃条或放大图标附近才触发；名称留白不触发，
        # 免得鼠标从上面路过时整条乱动。
        bar = self.bar_rect_f()
        idx = self._hit(e.pos())
        near = (bar.top() - 12 <= pos.y() <= bar.bottom() + 12) or idx >= 0
        self.stretch_target = 1.0 if (self.items and near) else 0.0
        self.spec_target = 1.0 if near else 0.0
        if not near:
            # 侧边名称预留区较宽，鼠标经过透明留白时不驱动鱼眼或柔光。
            self.mouse_x = self.spec_x = -99999.0
        if idx != self.hover_index:
            self.hover_index = idx
            QToolTip.hideText()
            # 只有悬停目标变了才设置鼠标形状（SetCursor 是系统调用，别每次都调）
            self.setCursor(Qt.PointingHandCursor if idx >= 0 else Qt.ArrowCursor)
            self._recalc(light=True)
        else:
            # 高刷新率鼠标每秒能上报上千次移动，没必要每次运动都全量重算；
            # 限制到约 120Hz，剩下的交给 60fps 的动画帧去插值，肉眼看不出差别。
            now = time.perf_counter()
            if now - self._last_move_calc >= 0.008:
                self._last_move_calc = now
                self._recalc(light=True)
        self._kick()
        super(Dock, self).mouseMoveEvent(e)

    def _hit(self, pos):
        if not self.rects:
            return -1
        pos = self.window_to_axis(pos)
        y = float(pos.y())
        x = float(pos.x())
        for i, r in enumerate(self.rects):
            if r[4]:            # 分隔符不响应鼠标
                continue
            cx, w, h, by = r[0], r[1], r[2], r[3]
            if abs(x - cx) > w / 2.0:
                continue
            if self.bump_down():
                # by 是图标顶边
                if (by - 6) <= y <= (by + h + 10):
                    return i
            else:
                # by 是图标底边
                if (by - h - 4) <= y <= (by + 10):
                    return i
        return -1

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.drag_start_pos = QPoint(e.pos())
            self._drag_snapshot = {"items": [dict(item) for item in self.cfg["items"]],
                                   "categories": list(self.organizer.state["categories"]) if self.organizer else [],
                                   "separators": separator_positions(self.organizer.state) if self.organizer else []}
            self.pressed = self._hit(e.pos())
            # 弹窗关闭后的点击不一定先经过 MouseMove，点击反馈直接绑定此次命中的入口。
            self.hover_index = self.pressed
            self.mouse_x = self.spec_x = float(self.window_to_axis(e.pos()).x()) if self.pressed >= 0 else -99999.0
            self.spec_target = self.stretch_target = 1.0 if self.pressed >= 0 else 0.0
            self._recalc(light=True)
            self._kick()
            self.drag_idx = -1
            self.drag_moved = False
            self.drag_from_x = float(self.window_to_axis(e.pos()).x())
            if ((self.cfg.get("reorder", True) or (self.pressed >= 0 and self.items[self.pressed].get("category"))) and self.pressed >= 0
                    and not self.items[self.pressed].get("sep")
                    and not self.items[self.pressed].get("trash")
                    and not self.items[self.pressed].get("computer")):
                if self.items[self.pressed].get("category") in ("__uncategorized__", "__more__"):
                    return
                self.drag_idx = self.pressed
                self.drag_from_x = float(self.window_to_axis(e.pos()).x())
        super(Dock, self).mousePressEvent(e)

    def _restore_drag_order(self):
        snapshot, self._drag_snapshot = self._drag_snapshot, None
        self.pressed = self.drag_idx = -1
        self.drag_moved = False
        if QWidget.keyboardGrabber() is self:
            self.releaseKeyboard()
        if not snapshot:
            return
        changed = self.cfg["items"] != snapshot["items"]
        self.cfg["items"] = snapshot["items"]
        if self.organizer and (self.organizer.state["categories"] != snapshot["categories"]
                               or separator_positions(self.organizer.state) != snapshot["separators"]):
            self.organizer.update_categories(snapshot["categories"], snapshot["separators"])
        if changed:
            save_config(self.cfg)
        self._build_items()
        self.reposition()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape and self.drag_idx >= 0:
            self._restore_drag_order()
            self._clear_hover()
            event.accept()
            return
        super().keyPressEvent(event)

    def _drag_reorder(self, x):
        # 快速跨过多项时直接追到当前指针所在位置，不要求每个邻居收到一次鼠标事件。
        for _ in range(len(self.items)):
            previous = self.drag_idx
            self._drag_reorder_step(x)
            if self.drag_idx == previous:
                break

    def _drag_reorder_step(self, x):
        """拖动排序：跟紧邻的图标/分隔符「一步一步」交换位置。

        带迟滞（要多越过邻居中心 30% 图标宽度才换），所以不会在临界点反复横跳；
        换位后也不重置图标尺寸，避免忽大忽小的闪烁。
        """
        category_drag = self.items[self.drag_idx].get("category") if self.drag_idx >= 0 else None
        n = len(self.items) if category_drag else len(self.cfg["items"])
        if self.drag_idx < 0 or n < 2:
            return
        margin = self.icon_size * 0.30
        # 找左右两边最近的"非自己"条目（分隔符也参与，这样才能被拖到分隔符后面）
        left = None
        for i in range(self.drag_idx - 1, -1, -1):
            if category_drag and self.items[i].get("sep"):
                continue
            if i != self.drag_idx:
                left = i
                break
        right = None
        for i in range(self.drag_idx + 1, n):
            if category_drag and self.items[i].get("sep"):
                continue
            right = i
            break
        target = -1
        if left is not None and x < self.rects[left][0] - margin:
            target = left
        elif right is not None and x > self.rects[right][0] + margin:
            target = right
        if target < 0 or target == self.drag_idx:
            return
        if category_drag and self.items[target].get("category") in (None, "__uncategorized__", "__more__"):
            return
        if category_drag:
            # 分类跨越分隔符时交换图标位置，保留划区，避免出现连续竖线。
            self.items[self.drag_idx], self.items[target] = self.items[target], self.items[self.drag_idx]
        else:
            it = self.items.pop(self.drag_idx)
            self.items.insert(target, it)
        if category_drag:
            visible = {entry["separator_after"] for entry in self.items if entry.get("category_separator")}
            separators = [key for key in separator_positions(self.organizer.state)
                          if key not in visible]
            anchor = "__before_categories__"
            for entry in self.items:
                if entry.get("category"):
                    anchor = entry["category"]
                elif entry.get("category_separator"):
                    separators.append(anchor)
                    entry["separator_after"] = anchor
            self.organizer.state["dock_separators"] = separators
            order = [entry["category"] for entry in self.items if entry.get("category") not in (None, "__uncategorized__", "__more__")]
            categories = self.organizer.state["categories"]
            by_id = {c["id"]: c for c in categories}
            self.organizer.state["categories"] = [by_id[cid] for cid in order] + [c for c in categories if c["id"] not in order]
        else:
            ci = self.cfg["items"].pop(self.drag_idx)
            self.cfg["items"].insert(target, ci)
            for i, entry in enumerate(self.items[:n]):
                entry["config_index"] = i
        self.drag_idx = target
        self.pressed = target
        # 顺序变了，"哪些分隔符要隔断背景"必须跟着重算，
        # 否则把图标拖到分隔符两边时不会出现隔断效果
        self._compute_split_flags()
        self._recalc()          # 不重置尺寸，保持放大状态，避免闪烁
        self._kick()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            if QWidget.keyboardGrabber() is self:
                self.releaseKeyboard()
            if self.drag_idx >= 0:
                if self.drag_moved:
                    position = self.window_to_axis(e.pos())
                    if not self.bar_rect_f().adjusted(-16, -30, 16, 30).contains(position):
                        entry = self.items[self.drag_idx]
                        if entry.get("path") and self._entry_drag_target([entry["path"]], e.globalPos(), "drop", "pinned"):
                            self.drag_idx = self.pressed = -1
                            self._drag_snapshot = None
                            self._clear_hover()
                        else:
                            self._restore_drag_order()
                            self._clear_hover()
                        e.accept()
                        return
                    self._drag_reorder(float(self.window_to_axis(e.pos()).x()))
                    category_drag = self.items[self.drag_idx].get("category")
                    self.drag_idx = -1
                    self.pressed = -1
                    self._drag_snapshot = None
                    if category_drag:
                        self.organizer.update_categories(self.organizer.state["categories"])
                    else:
                        save_config(self.cfg)      # 拖完把新顺序存下来
                    self._kick()
                    super(Dock, self).mouseReleaseEvent(e)
                    return
                self.drag_idx = -1
            idx = self._hit(e.pos())
            if idx >= 0 and idx == self.pressed:
                self.pops[idx] = 1.0
                self._kick()
                if self.items[idx].get("trash"):
                    if self.recycle_bin:
                        self.recycle_bin.open()
                elif self.items[idx].get("computer"):
                    self.launch("shell:MyComputerFolder")
                elif self.items[idx].get("category"):
                    self.open_category(self.items[idx]["category"])
                else:
                    self.launch(self.items[idx]["path"])
            self.pressed = -1
            self._drag_snapshot = None
        super(Dock, self).mouseReleaseEvent(e)

    def launch(self, path):
        log("启动: " + path)
        try:
            low = path.lower()
            if low.endswith(".exe") and os.path.exists(path):
                subprocess.Popen([path], cwd=os.path.dirname(path), close_fds=True)
            else:
                os.startfile(path)
        except Exception:
            log("启动失败，尝试 os.startfile: " + traceback.format_exc())
            try:
                os.startfile(path)
            except Exception:
                log("启动彻底失败: " + traceback.format_exc())

    def contextMenuEvent(self, e):
        idx = self._hit(e.pos())
        m = ThemedMenu(self, light=self.is_light(), colors=self.theme_colors())
        file_commands, file_paths = {}, []
        if idx >= 0 and self.items[idx].get("trash") and self.recycle_bin:
            m.addAction(m.glyph("open"), "打开回收站").triggered.connect(self.recycle_bin.open)
            empty = m.addAction(m.glyph("remove"), "清空回收站…")
            empty.setEnabled(self.recycle_bin.count != 0 and not self.recycle_bin.busy)
            empty.triggered.connect(self.recycle_bin.empty)
            m.addSeparator()
        elif idx >= 0 and self.items[idx].get("computer"):
            m.addAction(m.glyph("open"), "打开此电脑").triggered.connect(
                lambda: self.launch("shell:MyComputerFolder"))
            m.addSeparator()
        elif idx >= 0 and self.items[idx].get("category"):
            cid = self.items[idx]["category"]
            m.addAction(m.glyph("open"), "打开分类").triggered.connect(lambda: self.open_category(cid))
            self.add_organizer_actions(m)
            m.addSeparator()
        elif idx >= 0 and not self.items[idx].get("sep"):
            it = self.items[idx]
            a = QAction("打开 " + it["name"], m)
            a.setIcon(m.glyph("open"))
            a.triggered.connect(lambda _=False, p=it["path"]: self.launch(p))
            m.addAction(a)
            m.addSeparator()
            file_paths = [it["path"]]
            file_commands = self.file_actions.add_menu(m, file_paths)
            m.addSeparator()
            if self.organizer is not None:
                sub = m.addMenu("放入分类")
                for c in self.organizer.state["categories"]:
                    sub.addAction(c["name"]).triggered.connect(lambda _=False, cid=c["id"], path=it["path"]: self.organizer.assign_paths([path], cid))
        elif self.organizer is not None:
            self.add_organizer_actions(m)
        self.add_desktop_icons_action(m)
        self.add_position_menu(m)
        m.addSeparator()
        hide_action = m.addAction(m.glyph("show"), "隐藏 Dock")
        hide_action.setToolTip("可从托盘菜单重新显示")
        hide_action.triggered.connect(self.hide)
        m.addAction(m.glyph("exit"), "退出").triggered.connect(QApplication.instance().quit)
        m.setToolTipsVisible(True)
        anchor = self.menu_anchor(idx)
        screen = QApplication.screenAt(anchor.center()) or QApplication.primaryScreen()
        preferred = {"bottom": "above", "top": "below", "left": "right", "right": "left"}.get(
            self.cfg.get("position", "bottom"), "below" if self.bump_down() else "above")
        m.ensurePolished()
        self._clear_hover()
        chosen = m.exec_(_entry_menu_position(anchor, m.sizeHint(), screen.availableGeometry(), preferred))
        m.deleteLater()
        if chosen in file_commands:
            self.file_actions.perform(file_commands[chosen], file_paths)

    def menu_anchor(self, index):
        """Dock 菜单按可见图标展开，透明动画区不参与定位。"""
        if 0 <= index < len(self.rects):
            cx, width, height, base, _ = self.rects[index]
            local = self.window_rect(QRectF(cx - width / 2, base if self.bump_down() else base - height,
                                            width, height)).adjusted(-6, -6, 6, 6)
        else:
            local = self.window_rect(self.bar_rect_f())
        rect = local.toAlignedRect().intersected(self.rect())
        return QRect(self.mapToGlobal(rect.topLeft()), rect.size())

    def setup_organizer(self, directories=None):
        prepare_category_artwork(self.icons)
        set_entry_image_loader(entry_image)
        self.organizer = OrganizerService(self.cfg["organizer"], lambda: save_config(self.cfg), self, directories)
        self.category_panel = CategoryPanel(self.organizer, self.launch, self.pin_path, self.is_light(),
                                            menu_theme=self.theme_colors, file_actions=self.file_actions,
                                            drag_session=self.entry_drag, drag_target=self._entry_drag_target)
        self.search_bar = DockSearch(self)
        self.organizer.changed.connect(self._organizer_changed)
        self.organizer.error.connect(lambda message: self.organizer_message("整理提示", message))
        self.organizer.completed.connect(lambda count: self.organizer_message("整理完成", "已分类 %d 个项目，原文件位置保持不变。" % count))
        QApplication.instance().aboutToQuit.connect(self.organizer.stop)
        self._build_items()
        self.reposition()
        self.organizer.start()
        if self.isVisible():
            self.search_bar.show()

    def _organizer_changed(self):
        # 只更新分类入口，避免文件变化时重取独立应用图标。
        groups = self.organizer.groups()
        if self.desktop_manager:
            self.desktop_manager.update(groups, self.organizer.state["categories"])
        signature = self._organizer_signature(groups)
        if signature == self._category_signature:
            return
        old = self._category_signature
        if (old and signature[0] == old[0]
                and tuple(c[:3] for c in signature[1]) == tuple(c[:3] for c in old[1])
                and signature[3:] == old[3:]):
            # 数量变化只更新名称，不重建图标或排布，避免打断鼠标动画。
            categories = {c["id"]: c for c in self.organizer.state["categories"]}
            categories["__uncategorized__"] = {"id": "__uncategorized__", "name": "未分类", "icon": "other"}
            for item in self.items:
                cid = item.get("category")
                if cid in categories:
                    category = categories[cid]
                    item["name"] = category["name"] + " · %d" % len(groups.get(cid, []))
            self._category_signature = signature
            self.update(self.repaint_rect())
            return
        self._build_items()
        self.reposition()
        # 智能模式没有周期抓屏，分类增删改变窗口范围后立即更新底图。
        self.refresh_backdrop()
        self._kick()

    def _category_artwork(self, category):
        return category_pixmap(category.get("icon", "other"), max(96, int(self.icon_size * 2)), self.is_light())

    def _organizer_signature(self, groups):
        return (self.is_light(), tuple((c["id"], c["name"], c.get("icon"), len(groups.get(c["id"], [])))
                                     for c in self.organizer.state["categories"]), len(groups.get("__uncategorized__", [])),
                tuple(separator_positions(self.organizer.state)), bool(self.cfg.get("sep_split", True)))

    def organizer_message(self, title, message):
        log(title + ": " + message)
        if self.tray is not None:
            self.tray.showMessage(title, message, QSystemTrayIcon.Information, 2500)

    def _entry_drag_target(self, paths, point, stage, kind="category"):
        index = self._hit(self.mapFromGlobal(point)) if stage != "clear" else -1
        entry = self.items[index] if index >= 0 else {}
        category = entry.get("category")
        valid_category = category and category not in ("__uncategorized__", "__more__")
        highlight = index if valid_category or entry.get("trash") else -1
        if highlight != self._drop_index:
            self._drop_index = highlight
            self.update()
        if stage == "clear":
            return
        local = self.window_to_axis(self.mapFromGlobal(point))
        on_dock = index >= 0 or self.bar_rect_f().contains(local)
        panel = self.category_panel
        on_panel = panel and panel.isVisible() and panel.rect().contains(panel.mapFromGlobal(point))
        panel_content = on_panel and panel.view.viewport().rect().contains(panel.view.viewport().mapFromGlobal(point))
        panel_category = panel.category_id if panel_content else None
        if panel_category in ("__uncategorized__", "__more__"):
            panel_category = None
        if stage == "hover":
            if valid_category:
                return "归入 %s" % entry["name"].split(" · ")[0]
            if panel_category:
                return "归入当前分类"
            if entry.get("trash"):
                return "放开后确认移入回收站"
            if on_dock and index < 0:
                return "固定至 Dock"
            if on_dock or on_panel:
                return "此处不能放置 · Esc 取消"
            return "移除固定入口 · 原文件保留" if kind == "pinned" else "移除分类入口 · 原文件保留"
        self._drop_index = -1
        self.update()
        if valid_category or panel_category:
            self.organizer.assign_paths(paths, category if valid_category else panel_category)
        elif entry.get("trash"):
            if panel:
                panel.hide()
            return self.file_actions.perform("delete", paths)
        elif on_dock and index < 0:
            for path in paths:
                self.pin_path(path)
        elif on_dock or on_panel:
            return False
        elif kind == "pinned":
            selected = {normalize_path(path) for path in paths}
            self.cfg["items"] = [item for item in self.cfg["items"]
                                 if not item.get("path") or normalize_path(item["path"]) not in selected]
            save_config(self.cfg)
            self._build_items()
            self.reposition()
        else:
            self.organizer.exclude_paths(paths)
        return True

    def pin_path(self, path):
        if not any(normalize_path(it.get("path", "")) == normalize_path(path) for it in self.cfg["items"] if it.get("path")):
            self.cfg["items"].append({"path": path, "name": os.path.splitext(os.path.basename(path))[0]})
            save_config(self.cfg)
            self.reload()

    def open_category(self, cid):
        if self.search_bar:
            self.search_bar.collapse()
        if self.organizer is None:
            return
        if cid == "__more__":
            menu = ThemedMenu(self, light=self.is_light(), colors=self.theme_colors())
            groups = self.organizer.groups()
            for c in self.organizer.state["categories"] + [{"id": "__uncategorized__", "name": "未分类"}]:
                menu.addAction(c["name"] + " · %d" % len(groups.get(c["id"], []))).triggered.connect(lambda _=False, key=c["id"]: self.open_category(key))
            menu.addSeparator()
            menu.addAction("管理分类与分隔符…").triggered.connect(self.manage_categories)
            bar = self.bar_rect_f()
            point = self.axis_transform().map(QPointF(bar.center().x(), bar.bottom() if self.bump_down() else bar.top()))
            self._clear_hover()
            menu.exec_(self.mapToGlobal(point.toPoint()))
            menu.deleteLater()
            return
        # 锚点使用所点分类和可见玻璃边缘，透明的动画预留区不能拉开面板间距。
        bar = self.bar_rect_f()
        index = next((i for i, item in enumerate(self.items) if item.get("category") == cid), None)
        center = self.rects[index][0] if index is not None else bar.center().x()
        bounds = next((path.boundingRect() for segment, path in zip(self.shape_segments(), self.shape_paths())
                       if segment[0] <= center <= segment[1]), bar)
        top, bottom = bounds.top(), bounds.bottom()
        local = self.window_rect(QRectF(center - self.icon_size / 2, top,
                                       self.icon_size, bottom - top)).toAlignedRect()
        anchor = QRect(self.mapToGlobal(local.topLeft()), local.size())
        self._clear_hover()
        self.category_panel.open_category(cid, anchor, not self.bump_down(), self.is_light(),
                                          dock_edge=self.cfg.get("position", "bottom"))

    def manage_categories(self):
        if self.search_bar:
            self.search_bar.collapse()
        if self.category_panel:
            self.category_panel.hide()
        self.category_manager = CategoryManager(self.organizer, self.is_light(), self, dock_config=self.cfg)
        self.category_manager.exec_()
        self.category_manager.deleteLater()
        self.category_manager = None

    def add_organizer_actions(self, menu):
        scan = menu.addAction("一键整理桌面")
        scan.triggered.connect(self.organizer.request_scan)
        manage = menu.addAction("管理分类与分隔符…")
        manage.triggered.connect(self.manage_categories)
        action = menu.addAction("自动整理桌面变化")
        if isinstance(menu, ThemedMenu):
            scan.setIcon(menu.glyph("automatic"))
            manage.setIcon(menu.glyph("settings"))
        action.setCheckable(True)
        action.setChecked(self.organizer.state.get("automatic", True))
        action.triggered.connect(self.organizer.set_automatic)

    def add_desktop_icons_action(self, menu):
        sub = menu.addMenu("桌面图标")
        group = QActionGroup(sub)
        for mode, label in (("managed", "仅显示未归类项目"),
                            ("all", "显示全部图标"), ("hidden", "隐藏全部图标")):
            action = sub.addAction(label)
            action.setCheckable(True)
            action.setChecked(self.cfg.get("desktop_display", "managed") == mode)
            group.addAction(action)
            action.triggered.connect(lambda _=False, value=mode: self.set_desktop_display(value))
        sub.setToolTipsVisible(True)
        sub.actions()[0].setToolTip("已归类项目和回收站在 Dock 中显示；桌面保留未分类和已移出分类的项目。退出 Dock 后恢复完整桌面。")

    def set_desktop_display(self, mode):
        try:
            if self.desktop_manager:
                self.desktop_manager.set_mode(mode)
            else:
                set_icons_visible(mode != "hidden")
        except OSError as error:
            self.desktop_display_error(str(error))
            return False
        self.cfg["desktop_display"] = mode
        self.cfg["show_desktop_icons"] = mode != "hidden"
        save_config(self.cfg)
        return True

    def desktop_display_error(self, message):
        log("桌面显示提示：" + message)
        self.organizer_message("桌面显示提示", message)
        if self.desktop_manager:
            self.cfg["desktop_display"] = "all"
            self.cfg["show_desktop_icons"] = True
            save_config(self.cfg)

    def set_desktop_icons_visible(self, visible):
        return self.set_desktop_display("all" if visible else "hidden")

    def dragEnterEvent(self, event):
        if (self.organizer or self.recycle_bin) and any(u.isLocalFile() for u in event.mimeData().urls()):
            event.setDropAction(Qt.CopyAction)
            event.accept()

    def dragMoveEvent(self, event):
        idx = self._hit(event.pos())
        cid = self.items[idx].get("category") if idx >= 0 else None
        trash = idx >= 0 and self.items[idx].get("trash") and self.recycle_bin and not self.recycle_bin.busy
        self._drop_index = idx if cid or trash else -1
        self.update()
        if cid in ("__uncategorized__", "__more__"):
            event.ignore()
        elif cid or idx < 0 or trash:
            event.setDropAction(Qt.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self._drop_index = -1
        self.update()

    def dropEvent(self, event):
        idx = self._hit(event.pos())
        cid = self.items[idx].get("category") if idx >= 0 else None
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if idx >= 0 and self.items[idx].get("trash") and self.recycle_bin:
            if not self.recycle_bin.recycle(paths):
                event.ignore()
                return
        elif cid and cid not in ("__uncategorized__", "__more__"):
            self.organizer.assign_paths(paths, cid)
        elif idx < 0:
            for path in paths:
                self.pin_path(path)
        else:
            event.ignore()
            return
        self._drop_index = -1
        event.setDropAction(Qt.CopyAction)
        # 文件操作由回收服务负责；不能让拖出端再次执行 MoveAction 删除原文件。
        event.accept()
        self.update()

    # ---------------- 绘制 ----------------
    @staticmethod
    def _stop_alpha(stops, t):
        """在一条渐变的色标里插值取值。"""
        if t <= stops[0][0]:
            return float(stops[0][1])
        for i in range(1, len(stops)):
            p0, a0 = stops[i - 1]
            p1, a1 = stops[i]
            if t <= p1:
                if p1 <= p0:
                    return float(a1)
                return a0 + (a1 - a0) * (t - p0) / (p1 - p0)
        return float(stops[-1][1])

    def merged_grad_stops(self, c):
        """把"竖向渐变"和"顶部高光"合并成一条渐变。

        两者都是白色的竖向渐变，合成一条之后每段只要裁切一次、填充一次，
        能省掉一次昂贵的路径裁切光栅化（性能关键）。
        """
        hl_span = 0.42
        out = []
        for f in (0.0, 0.10, 0.20, 0.28, 0.42, 0.70, 1.0):
            a1 = self._stop_alpha(c["grad"], f)
            a2 = self._stop_alpha(c["hl"], f / hl_span) if f <= hl_span else 0.0
            m = 1.0 - (1.0 - a1 / 255.0) * (1.0 - a2 / 255.0)
            out.append((f, int(round(m * 255))))
        return out

    def icon_scaled(self, it, size):
        """取"已经缩放到目标尺寸"的图标（按 2 像素一档缓存）。

        每帧都对 256×256 的原始图标做一次平滑缩放很贵；缓存之后大部分帧
        变成 1:1 贴图，只有尺寸跨档时才重新缩一次。
        """
        q = max(4, int(round(size / 2.0)) * 2)
        cache = it.get("_scaled")
        if cache is None:
            cache = {}
            it["_scaled"] = cache
        pm = cache.get(q)
        if pm is not None:
            return pm
        src = it.get("pixmap")
        if src is None or src.isNull():
            return None
        if q == src.width() and q == src.height():
            pm = src                      # 尺寸刚好一样，直接用（省一次缩放）
        else:
            # 一定要缩放到目标尺寸：源图可能比目标小（文件夹图标以前常常只有 40 像素），
            # 直接返回源图的话画出来会又小又偏（是按左上角贴的，不是按格子居中）
            pm = src.scaled(q, q, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        # 缓存满了就淘汰最旧的一个，不要整体清空 ——
        # 整体清空会让那一帧所有图标都重新缩放，滑动时每隔十几帧卡一下（抽搐感来源之一）
        if len(cache) >= 6:
            cache.pop(next(iter(cache)), None)
        cache[q] = pm
        return pm

    def _paint_glass_piece(self, p, path, path_rect, bar, c, tint_a, stops):
        """画一段玻璃（隔断模式下会有好几段，每段都有自己的圆角）。

        整段只做一次 setClipPath —— 复杂路径的裁切光栅化是这里最贵的操作，
        之前每层各裁一次，一帧要裁好几遍，这就是鼠标滑动时占用偏高的主因。
        """
        p.save()
        p.setClipPath(path)
        if self.cfg["glass"] and self.backdrop is not None:
            # 只画这一段所在的那块区域，避免整窗重绘浪费性能
            p.drawPixmap(path_rect, self.backdrop, path_rect)
            if tint_a > 0:
                col = QColor(c["tint"])
                col.setAlpha(tint_a)
                p.fillRect(path_rect, col)
        else:
            col = QColor(c["tint"])
            col.setAlpha(min(255, tint_a + 20))
            p.fillRect(path_rect, col)

        # 竖向渐变 + 顶部高光（已经合并成一条渐变，省一次裁切+填充）
        # 注：实测这里用 QLinearGradient 直接填充比"缓存贴图再拉伸"更快，
        # 因为 Qt 的线性渐变填充走的是优化过的快路径。
        g = QLinearGradient(QPointF(0, path_rect.top()), QPointF(0, path_rect.bottom()))
        for pos, a in stops:
            g.setColorAt(pos, QColor(255, 255, 255, a))
        p.fillRect(path_rect, QBrush(g))

        # 跟着鼠标走的柔光（液态感的关键）
        # 只填"柔光实际照到的那一块"：半径外的颜色本来就是全透明，
        # 限制填充范围不改变画面，但能省掉几倍的像素量。
        if self.spec_alpha > 0.01:
            wide = float(c.get("spec_wide", 1.2))
            radius = bar.height() * wide
            if path_rect.left() - radius <= self.spec_x <= path_rect.right() + radius:
                rad = QRadialGradient(QPointF(self.spec_x, bar.center().y()), radius)
                a = int(c["spec"] * self.spec_alpha)
                rad.setColorAt(0.0, QColor(255, 255, 255, a))
                rad.setColorAt(0.55, QColor(255, 255, 255, int(a * 0.35)))
                rad.setColorAt(1.0, QColor(255, 255, 255, 0))
                box = QRectF(self.spec_x - radius, path_rect.top(),
                             radius * 2.0, path_rect.height()).intersected(path_rect)
                if not box.isEmpty():
                    p.fillRect(box, QBrush(rad))

        # 光感模式：再补一道斜向的"光扫过玻璃"的光带，就是那种带光照的观感
        # （同样只填光带实际覆盖的那一段，右边全透明的地方不浪费像素）
        if c.get("gloss"):
            gx0 = path_rect.left()
            gy0 = path_rect.top()
            sweep_w = path_rect.height() * 1.5
            sweep = QLinearGradient(QPointF(gx0, gy0),
                                    QPointF(gx0 + sweep_w, path_rect.bottom()))
            sweep.setColorAt(0.00, QColor(255, 255, 255, 0))
            sweep.setColorAt(0.13, QColor(255, 255, 255, 132))
            sweep.setColorAt(0.30, QColor(255, 255, 255, 28))
            sweep.setColorAt(0.52, QColor(255, 255, 255, 0))
            sbox = QRectF(gx0, path_rect.top(), sweep_w,
                          path_rect.height()).intersected(path_rect)
            if not sbox.isEmpty():
                p.fillRect(sbox, QBrush(sweep))
        p.restore()

        # 描边（不需要裁切）
        pen = QPen(c["border"])
        pen.setWidthF(float(c.get("border_w", 1.0)))
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)

        bar = self.bar_rect_f()
        paths = self.shape_paths()
        prects = [pa.boundingRect() for pa in paths]
        path = paths[0] if paths else QPainterPath()
        path_rect = prects[0] if prects else bar

        # 玻璃整体：自己抓屏 + 自己模糊，模糊区域完全跟随玻璃形状，
        # 四个角天生透明，不会有方形轮廓。
        #
        # 通透度作用于【整块玻璃】：
        #   tp<=40 时整块玻璃保持不透明，只是压在背景上的深色变淡（偏实 → 默认）
        #   tp>40  时整块玻璃（模糊画面 + 深色 + 高光 + 描边）一起变淡，
        #           于是无论背后是亮壁纸还是深色窗口，都能明显看出"更通透"了
        tp = max(0, min(100, int(self.cfg.get("transparency", 40))))
        c = self.theme_colors()
        base_a = 235.0 * (100 - tp) / 100.0
        # 各模式用各自的"底色浓度曲线"：深色 1.0 倍、浅色 0.70+45、雾透 0.40+24
        tint_a = int(round(min(255.0, base_a * c["tint_scale"] + c["tint_floor"])))
        glass_a = 1.0 - max(0.0, tp - 40.0) / 60.0 * 0.58
        glass_a = max(0.32, min(1.0, glass_a))

        p.save()
        p.setTransform(self.axis_transform())
        p.setOpacity(glass_a)

        stops = self.merged_grad_stops(c)
        for pa, pr in zip(paths, prects):
            self._paint_glass_piece(p, pa, pr, bar, c, tint_a, stops)

        p.restore()      # 玻璃画完，透明度恢复，下面的名称和图标始终是全不透明的

        # 悬停时的程序名称：放在图标放大区之外，不挡任何东西；
        # 如果 Dock 贴着屏幕顶部，就改画在玻璃条下面，保证看得清。
        if (self.cfg.get("show_name", True) and self.label_alpha > 0.02
                and 0 <= self.hover_index < len(self.items)):
            name = self.items[self.hover_index]["name"]
            f = self._label_font
            fm = self._label_metrics
            if self.is_vertical():
                name = fm.elidedText(name, Qt.ElideRight, self.side_label_width() - 24)
            tw = float(fm.width(name) + 24)
            th = self.label_height()
            cx = self.rects[self.hover_index][0]
            if self.is_vertical():
                visible_bar = self.window_rect(bar)
                gap = self.icon_size * .32 + 8.0
                lx = visible_bar.right() + gap if self.bump_down() else visible_bar.left() - gap - tw
                ly = min(max(cx - th / 2.0, 4.0), self.height() - th - 4.0)
            else:
                lx = min(max(cx - tw / 2.0, 4.0), max(4.0, self.width() - tw - 4.0))
                ly = self.label_top_y(bar)
            lab = QRectF(lx, ly, tw, th)
            lp = QPainterPath()
            rad = min(th / 2.0, 9.0 * self.ui_mult)
            lp.addRoundedRect(lab, rad, rad)
            p.save()
            p.setOpacity(self.label_alpha)
            p.fillPath(lp, c["label_bg"])
            lg = QLinearGradient(lab.topLeft(), lab.bottomLeft())
            lg.setColorAt(0.0, QColor(255, 255, 255, 44 if not c["light"] else 120))
            lg.setColorAt(1.0, QColor(255, 255, 255, 8 if not c["light"] else 30))
            p.fillPath(lp, QBrush(lg))
            p.setPen(QPen(c["label_border"], 1.0))
            p.setBrush(Qt.NoBrush)
            p.drawPath(lp)
            p.setFont(f)
            p.setPen(c["label_fg"])
            p.drawText(lab, Qt.AlignCenter, name)
            p.restore()

        if not self.items:
            hint = T("请在右下角托盘图标上右键 → 添加图标")
            f = self._label_font
            p.setFont(f)
            p.setPen(c["shadow"])
            actual_bar = self.window_rect(bar)
            if self.is_vertical():
                hint = T("添加图标…")
            p.drawText(actual_bar.adjusted(0, 1, 0, 1), Qt.AlignCenter, hint)
            p.setPen(c["fg"])
            p.drawText(actual_bar, Qt.AlignCenter, hint)
            return

        # 图标 / 分隔符（点击时弹一下：平时以底边为支点往上弹，贴屏幕顶部时反过来）
        down = self.bump_down()
        for i, it in enumerate(self.items):
            cx, w, h, by = self.rects[i][0], self.rects[i][1], self.rects[i][2], self.rects[i][3]
            if self.rects[i][4] or it.get("sep"):
                if it.get("system_separator"):
                    continue
                # 分隔符：一根居中的圆头细竖条，长度约为图标区的 44%
                sh = max(9.0, self.icon_size * 0.44)
                swid = max(1.6, self.icon_size * 0.055)
                dc = QColor(c["fg"])
                dc.setAlpha(96 if c["light"] else 120)
                p.setPen(Qt.NoPen)
                p.setBrush(dc)
                cy = (by + self.icon_size / 2.0) if down else (by - self.icon_size / 2.0)
                p.drawRoundedRect(self.window_rect(QRectF(cx - swid / 2.0, cy - sh / 2.0, swid, sh)),
                                  swid / 2.0, swid / 2.0)
                continue
            pop = self.pops[i]
            extra = 1.0 + 0.08 * math.sin(math.pi * pop) if pop > 0.0 else 1.0
            dw = w * extra
            dh = h * extra
            top_y = by if down else (by - dh)
            rect = self.window_rect(QRectF(cx - dw / 2.0, top_y, dw, dh))
            if i == self._drop_index:
                p.setPen(QPen(QColor(80, 160, 255, 230), 2))
                p.setBrush(QColor(80, 160, 255, 40))
                p.drawRoundedRect(rect.adjusted(-5, -5, 5, 5), 14, 14)
            # 运行中的小圆点：始终在图标【下方】，而且是先画它、再画图标，
            # 所以它的层级低于图标 —— 图标放大盖过来时会挡住圆点，而不是压在图标上面。
            if self.cfg["running_dots"] and it["exe"] and it["exe"] in self.running:
                dot = max(3.0, self.icon_size * 0.075)
                dc = QColor(c["fg"])
                dc.setAlpha(210)
                p.setPen(Qt.NoPen)
                p.setBrush(dc)
                if down:
                    # 贴屏幕顶部时图标是从上边缘向下长的，点放在"静止时图标的下边"
                    dy = by + self.icon_size + dot * 1.4
                else:
                    dy = by + dot * 1.6
                p.drawEllipse(self.axis_transform().map(QPointF(cx, dy)), dot, dot)
            pm = self.icon_scaled(it, dw)
            if pm is None:
                pass
            elif c.get("tile"):
                # 雾透模式：图标坐在一块白色圆角底板上（iOS 那种观感）
                tile_r = dw * float(c.get("tile_radius", 0.30))
                tile = QRectF(rect)
                # 柔和投影：先画一块略深、往下偏一点的圆角块
                p.setPen(Qt.NoPen)
                p.setBrush(c["tile_shadow"])
                p.drawRoundedRect(tile.adjusted(dw * 0.02, dh * 0.045,
                                                -dw * 0.02, dh * 0.045),
                                  tile_r, tile_r)
                p.setBrush(c["tile_color"])
                p.drawRoundedRect(tile, tile_r, tile_r)
                # 原图标按比例缩小画在底板正中
                k = float(c.get("tile_icon", 0.60))
                iw = dw * k
                ih = dh * k
                p.drawPixmap(QRectF(tile.center().x() - iw / 2.0,
                                    tile.center().y() - ih / 2.0, iw, ih),
                             pm, QRectF(pm.rect()))
            else:
                # 按精确矩形缩放绘制（缓存图只是"接近目标尺寸"的中间图）。
                # 不能直接 1:1 贴：缓存是按 2 像素分档的，直接贴会让图标尺寸
                # 一跳一跳地变（鼠标滑动时看起来就是"抽搐"）。
                p.drawPixmap(rect, pm, QRectF(pm.rect()))

    # ---------------- 背景模糊（自己实现的真毛玻璃） ----------------
    def _capture_behind(self):
        """抓取 Dock 背后真实的桌面画面。

        关键一步：抓图之前先把本窗口标记成"不参与屏幕捕获"
        (WDA_EXCLUDEFROMCAPTURE)，否则会把 Dock 自己拍进去，形成无限套娃。
        抓完立刻恢复原状，所以你自己截图时 Dock 依然会正常出现。
        返回 (截图, 是否成功)。
        """
        hwnd = wintypes.HWND(int(self.winId()))
        ok = False
        try:
            user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
            user32.SetWindowDisplayAffinity.restype = wintypes.BOOL
            ok = bool(user32.SetWindowDisplayAffinity(hwnd, 0x11))
            if not ok:
                return None, False
            scr = QGuiApplication.primaryScreen()
            dpr = float(scr.devicePixelRatio())
            g = self.frameGeometry()
            x = int(round(g.x() * dpr))
            y = int(round(g.y() * dpr))
            w = max(1, int(round(g.width() * dpr)))
            h = max(1, int(round(g.height() * dpr)))
            return scr.grabWindow(0, x, y, w, h), True
        except Exception:
            log("抓取背景失败: " + traceback.format_exc())
            return None, ok
        finally:
            if ok:
                try:
                    user32.SetWindowDisplayAffinity(hwnd, 0)
                except Exception:
                    pass

    def blur_divisor(self):
        """毛玻璃模糊程度：把背景缩小到 1/div 再放大回来，div 越大越糊。"""
        try:
            return max(2, min(40, int(self.cfg.get("blur_px", 6))))
        except Exception:
            return 6

    def refresh_backdrop(self):
        """抓背景 → 缩小再放大（等于一次大半径模糊）→ 作为玻璃后面的画面。"""
        if self.preview or not self.isVisible():
            return
        if not self.cfg["glass"]:
            # 关掉毛玻璃：完全不抓屏，直接用半透明底色
            self.blur_timer.stop()
            if self.backdrop is not None:
                self.backdrop = None
                self.update()
            return
        pm, ok = self._capture_behind()
        if not ok:
            if self.backdrop_ok is not False:
                self.backdrop_ok = False
                log("本机不支持屏幕捕获排除，毛玻璃降级为普通半透明（不影响使用）")
            self.blur_timer.stop()
            self.update()
            return
        if pm is None or pm.isNull():
            return
        self.backdrop_ok = True
        try:
            scr = QGuiApplication.primaryScreen()
            dpr = float(scr.devicePixelRatio()) or 1.0
            div = self.blur_divisor()
            w, h = max(2, pm.width() // div), max(2, pm.height() // div)
            small = pm.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            small = small.scaled(max(1, w // 2), max(1, h // 2),
                                 Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            # 注意：要还原成"设备像素"尺寸并标好缩放比，
            # 否则在 125%/150%/200% 缩放的屏幕上玻璃里的画面会被拉糊。
            out = small.scaled(max(1, int(round(self.width() * dpr))),
                               max(1, int(round(self.height() * dpr))),
                               Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            out.setDevicePixelRatio(dpr)
            # 背景按实际屏幕抓取，换轴一次后与逻辑玻璃坐标一致；不在动画帧重复转换。
            self.backdrop = out.transformed(self.axis_transform()) if self.is_vertical() else out
        except Exception:
            log("模糊处理失败: " + traceback.format_exc())
            return
        self.update()

    def start_backdrop(self):
        if self.preview or not self.isVisible():
            return
        mode = str(self.cfg.get("blur_mode", "smart"))
        self.blur_timer.setInterval(BLUR_INTERVAL.get(mode, BLUR_INTERVAL["smart"]))
        if not self._logged_once:
            self._logged_once = True
            try:
                scr = QGuiApplication.primaryScreen()
                try:
                    dpi_sys = int(user32.GetDpiForSystem())
                except Exception:
                    dpi_sys = -1
                try:
                    dpi_win = int(user32.GetDpiForWindow(wintypes.HWND(int(self.winId()))))
                except Exception:
                    dpi_win = -1
                log("屏幕=%dx%d 可用=%dx%d 缩放=%s 系统DPI=%d 窗口DPI=%d 倍率=%.2f 图标=%d 窗口=%dx%d 位置=(%d,%d) 毛玻璃=%s 层级=%s 抓取=%s"
                    % (scr.geometry().width(), scr.geometry().height(),
                       scr.availableGeometry().width(), scr.availableGeometry().height(),
                       scr.devicePixelRatio(), dpi_sys, dpi_win, self.ui_mult, self.icon_size,
                       self.width(), self.height(), self.x(), self.y(), self.cfg["glass"],
                       self.cfg.get("layer", "bottom"), mode))
            except Exception:
                pass
        if not self.cfg["glass"]:
            self.backdrop = None
            self.blur_timer.stop()
            self.update()
            return
        self.refresh_backdrop()
        if mode in ("off", "smart"):
            # 智能模式由显示、鼠标进入和布局变化刷新，不做空闲抓屏。
            self.blur_timer.stop()
        elif self.backdrop_ok and not self.blur_timer.isActive():
            self.blur_timer.start()

    def showEvent(self, e):
        # 分类弹窗可能与应用共享默认标题，退出命令必须准确找到主 Dock。
        user32.SetPropW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.HANDLE]
        user32.SetPropW.restype = wintypes.BOOL
        user32.SetPropW(int(self.winId()), MAIN_WINDOW_MARKER, 1)
        super(Dock, self).showEvent(e)
        if self.search_bar:
            self.sync_search_geometry()
            self.search_bar.show()
        if not self.preview:
            self.geo_timer.start()
            self.refresh_running()
        QTimer.singleShot(50, self.start_backdrop)
        QTimer.singleShot(60, self.apply_layer)

    def hideEvent(self, e):
        if self.search_bar:
            self.search_bar.hide()
        if self.category_panel:
            self.category_panel.hide()
        self.blur_timer.stop()
        self.proc_timer.stop()
        self.geo_timer.stop()
        self.timer.stop()
        self._hover_backdrop_pending = False
        self._frame_time = None
        self.mouse_x = self.mouse_smooth = self.spec_x = -99999.0
        self.hover_index = self.pressed = self.drag_idx = self._drop_index = -1
        self.spec_alpha = self.spec_target = self.label_alpha = self.stretch = self.stretch_target = 0.0
        self.pops = [0.0] * len(self.items)
        self._recalc(uniform=True)
        super(Dock, self).hideEvent(e)

    def closeEvent(self, e):
        # 关闭 Dock 窗口 = 退出整个程序
        try:
            QApplication.instance().quit()
        except Exception:
            pass
        super(Dock, self).closeEvent(e)

    def reload(self):
        if self.search_bar:
            self.search_bar.collapse(animate=False)
            self.search_bar.invalidate()
        self.base_icon = int(self.cfg["icon_size"])
        self.ui_mult = self._ui_mult()
        self.icon_size = self._scaled(self.base_icon)
        self.font_pt = max(8, int(round(9 * self.ui_mult)))
        self.prepare_label_font()
        self.pad_x = int(self.icon_size * 0.36)
        self.pad_y = int(self.icon_size * 0.34)
        self.icons.clear()
        self._exe_cache.clear()
        self._build_items()
        self.reposition()
        if self.search_bar:
            self.search_bar.update_theme()
        self.start_backdrop()
        self._kick()

    def refresh_geometry(self):
        """只重新算尺寸和位置（比如开关名称显示、开关隔断时布局变了）。

        reposition() 内部已经会算好位置、调整窗口大小并重算图标坐标，
        这里不用再重复一遍。
        """
        self.reposition()
        self.start_backdrop()
        self._kick()


# ----------------------------------------------------------------------------
# 托盘图标
# ----------------------------------------------------------------------------
_TRAY_ICON_CACHE = []


def make_tray_icon(size=64):
    """托盘图标：优先用程序目录里的 dock.ico（软件图标），拿不到就自己画一个。"""
    if _TRAY_ICON_CACHE:
        return _TRAY_ICON_CACHE[0]
    icon = None
    try:
        p = os.path.join(APP_DIR, "dock.ico")
        if os.path.exists(p):
            ic = QIcon(p)
            if not ic.isNull():
                icon = ic
    except Exception:
        icon = None
    if icon is None:
        # 打包成 exe 后如果没带 ico 文件，就从 exe 自身把图标抠出来
        try:
            if IS_FROZEN:
                pm = IconProvider().get(SCRIPT_PATH, 128)
                if pm is not None and not pm.isNull():
                    icon = QIcon(pm)
        except Exception:
            icon = None
    if icon is None:
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(2, 2, size - 4, size - 4)
        path = QPainterPath()
        path.addRoundedRect(r, size * 0.28, size * 0.28)
        g = QLinearGradient(r.topLeft(), r.bottomRight())
        g.setColorAt(0.0, QColor(110, 195, 255))
        g.setColorAt(1.0, QColor(178, 140, 255))
        p.fillPath(path, QBrush(g))
        p.setPen(QPen(QColor(255, 255, 255, 190), 2))
        p.drawPath(path)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 235))
        d = size * 0.11
        for i in (-1, 0, 1):
            p.drawEllipse(QPointF(size / 2.0 + i * size * 0.26, size / 2.0), d, d)
        p.end()
        icon = QIcon(pm)
    _TRAY_ICON_CACHE.append(icon)
    return icon


class DockTray(QSystemTrayIcon):
    def __init__(self, dock):
        super(DockTray, self).__init__(make_tray_icon())
        self.dock = dock
        self.cfg = dock.cfg
        set_lang(self.cfg.get("lang", "zh"))     # 按配置设好界面语言
        self.menu = ThemedMenu(light=dock.is_light(), colors=dock.theme_colors())
        self.setContextMenu(self.menu)
        self.menu.aboutToShow.connect(self.rebuild)
        self.activated.connect(self._activated)
        self.rebuild()
        self.setToolTip(APP_TITLE + " —— 右键管理图标")

    def _activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.menu.popup(QCursor.pos())

    # ---------- 菜单 ----------
    def rebuild(self):
        m = self.menu
        m.clear()
        d = self.dock
        m.set_theme(d.is_light(), d.theme_colors())

        a = QAction(T("显示 / 隐藏 Dock"), m)
        a.setCheckable(True)
        a.setChecked(d.isVisible())
        a.triggered.connect(lambda: (d.hide() if d.isVisible() else self._show_dock()))
        m.addAction(a)
        d.add_desktop_icons_action(m)
        m.addSeparator()

        if d.organizer is not None:
            d.add_organizer_actions(m)
            m.addSeparator()

        a = QAction(T("添加图标…"), m)
        a.triggered.connect(self.add_icons)
        m.addAction(a)

        a = QAction("配置分隔符…", m)
        a.triggered.connect(d.manage_categories)
        m.addAction(a)

        a = QAction(T("分隔符隔断背景"), m)
        a.setCheckable(True)
        a.setChecked(bool(self.cfg.get("sep_split", True)))
        a.triggered.connect(lambda v: self.set_flag("sep_split", v, geometry=True))
        m.addAction(a)

        a = QAction(T("图标顺序可拖动"), m)
        a.setCheckable(True)
        a.setChecked(bool(self.cfg.get("reorder", True)))
        a.triggered.connect(lambda v: self.set_flag("reorder", v))
        m.addAction(a)

        rm = m.addMenu(T("移除图标"))
        rm.setEnabled(bool(d.items))
        for idx, it in enumerate(d.items):
            if (it.get("category") or it.get("category_separator") or it.get("trash")
                    or it.get("computer") or it.get("system_separator")):
                continue
            label = T("—— 分隔符 ——") if it.get("sep") else it["name"]
            act = QAction(label, rm)
            act.triggered.connect(lambda _=False, i=idx: self.remove_index(i))
            rm.addAction(act)
        if not d.items:
            e = QAction(T("（还没有固定任何图标）"), rm)
            e.setEnabled(False)
            rm.addAction(e)

        m.addSeparator()

        sz = m.addMenu(T("图标大小"))
        grp = QActionGroup(sz)
        grp.setExclusive(True)
        for label, px in ICON_SIZES:
            act = QAction(T("%s（%d 像素）") % (T(label), px), sz)
            act.setCheckable(True)
            act.setChecked(int(self.cfg["icon_size"]) == px)
            act.triggered.connect(lambda _=False, v=px: self.set_icon_size(v))
            grp.addAction(act)
            sz.addAction(act)
        sz.addSeparator()
        cur_px = int(self.cfg["icon_size"])
        act = QAction(T("自定义…（当前 %d 像素）") % cur_px, sz)
        act.setCheckable(True)
        act.setChecked(cur_px not in [v for _, v in ICON_SIZES])
        act.triggered.connect(self.custom_icon_size)
        grp.addAction(act)
        sz.addAction(act)

        th = m.addMenu(T("颜色模式"))
        tgrp = QActionGroup(th)
        tgrp.setExclusive(True)
        for label, val in THEMES:
            act = QAction(T(label), th)
            act.setCheckable(True)
            act.setChecked(str(self.cfg.get("theme", "auto")) == val)
            act.triggered.connect(lambda _=False, v=val: self.set_theme(v))
            tgrp.addAction(act)
            th.addAction(act)

        ly = m.addMenu(T("窗口层级"))
        lgrp = QActionGroup(ly)
        lgrp.setExclusive(True)
        for label, val in LAYERS:
            act = QAction(T(label), ly)
            act.setCheckable(True)
            act.setChecked(str(self.cfg.get("layer", "bottom")) == val)
            act.triggered.connect(lambda _=False, v=val: self.set_layer(v))
            lgrp.addAction(act)
            ly.addAction(act)

        pm = m.addMenu(T("窗口位置"))
        pgrp = QActionGroup(pm)
        pgrp.setExclusive(True)
        for label, val in POSITIONS:
            act = QAction(T(label), pm)
            act.setCheckable(True)
            act.setChecked(str(self.cfg.get("position", "bottom")) == val)
            act.triggered.connect(lambda _=False, v=val: self.set_position(v))
            pgrp.addAction(act)
            pm.addAction(act)
        pm.addSeparator()
        act = QAction(T("调整自定义高度…（当前距底部 %d 像素）")
                      % int(self.cfg.get("custom_bottom", 200)), pm)
        act.triggered.connect(self.ask_custom_position)
        pm.addAction(act)

        bm = m.addMenu(T("背景抓取频率"))
        bgrp = QActionGroup(bm)
        bgrp.setExclusive(True)
        for label, val in BLUR_MODES:
            act = QAction(T(label), bm)
            act.setCheckable(True)
            act.setChecked(str(self.cfg.get("blur_mode", "smart")) == val)
            act.triggered.connect(lambda _=False, v=val: self.set_blur_mode(v))
            bgrp.addAction(act)
            bm.addAction(act)
        bm.addSeparator()
        act = QAction(T("立即刷新一次背景"), bm)
        act.triggered.connect(self.refresh_now)
        bm.addAction(act)

        mm = m.addMenu(T("悬停动画"))
        a = QAction(T("启用悬停放大"), mm)
        a.setCheckable(True)
        a.setChecked(bool(self.cfg["magnify"]))
        a.triggered.connect(lambda v: self.set_flag("magnify", v))
        mm.addAction(a)
        mm.addSeparator()
        mgrp = QActionGroup(mm)
        mgrp.setExclusive(True)
        cur_bump = str(self.cfg.get("bump_level", "mid"))
        for key, label, _k in BUMP_LEVELS:
            act = QAction(T("放大程度：%s") % T(label), mm)
            act.setCheckable(True)
            act.setChecked(cur_bump == key)
            act.triggered.connect(lambda _=False, v=key: self.set_bump(v))
            mgrp.addAction(act)
            mm.addAction(act)

        gm = m.addMenu(T("毛玻璃（背景模糊）"))
        a = QAction(T("启用毛玻璃效果"), gm)
        a.setCheckable(True)
        a.setChecked(bool(self.cfg["glass"]))
        a.triggered.connect(lambda v: self.set_flag("glass", v, glass=True))
        gm.addAction(a)
        gm.addSeparator()
        bgrp = QActionGroup(gm)
        bgrp.setExclusive(True)
        cur_blur = int(self.cfg.get("blur_px", 6))
        for label, val in BLUR_LEVELS:
            act = QAction(T("模糊程度：%s") % T(label), gm)
            act.setCheckable(True)
            act.setChecked(cur_blur == val)
            act.triggered.connect(lambda _=False, v=val: self.set_blur(v))
            bgrp.addAction(act)
            gm.addAction(act)
        act = QAction(T("模糊程度：自定义…（当前 %d）") % cur_blur, gm)
        act.setCheckable(True)
        act.setChecked(cur_blur not in [v for _, v in BLUR_LEVELS])
        act.triggered.connect(self.ask_blur)
        bgrp.addAction(act)
        gm.addAction(act)

        a = QAction(T("运行中的程序显示小圆点"), m)
        a.setCheckable(True)
        a.setChecked(bool(self.cfg["running_dots"]))
        a.triggered.connect(lambda v: self.set_flag("running_dots", v, running=True))
        m.addAction(a)

        a = QAction(T("悬停时显示程序名称"), m)
        a.setCheckable(True)
        a.setChecked(bool(self.cfg.get("show_name", True)))
        a.triggered.connect(lambda v: self.set_flag("show_name", v, geometry=True))
        m.addAction(a)

        tp = m.addMenu(T("玻璃通透度"))
        tgrp = QActionGroup(tp)
        tgrp.setExclusive(True)
        for label, val in TRANSPARENCIES:
            act = QAction(T("%s（%d%%）") % (T(label), val), tp)
            act.setCheckable(True)
            act.setChecked(int(self.cfg.get("transparency", 40)) == val)
            act.triggered.connect(lambda _=False, v=val: self.set_transparency(v))
            tgrp.addAction(act)
            tp.addAction(act)

        m.addSeparator()

        a = QAction(T("开机自动启动"), m)
        a.setCheckable(True)
        a.setChecked(get_autostart())
        a.triggered.connect(self.toggle_autostart)
        m.addAction(a)

        lm = m.addMenu(T("语言 / Language"))
        lgrp2 = QActionGroup(lm)
        lgrp2.setExclusive(True)
        for label, val in LANGS:
            act = QAction(T(label), lm)
            act.setCheckable(True)
            act.setChecked(str(self.cfg.get("lang", "zh")) == val)
            act.triggered.connect(lambda _=False, v=val: self.set_language(v))
            lgrp2.addAction(act)
            lm.addAction(act)

        m.addSeparator()

        a = QAction(T("使用说明"), m)
        a.triggered.connect(self.open_readme)
        m.addAction(a)

        a = QAction(T("打开配置文件夹"), m)
        a.triggered.connect(lambda: os.startfile(CONFIG_DIR))
        m.addAction(a)

        a = QAction(T("退出"), m)
        a.triggered.connect(QApplication.instance().quit)
        m.addAction(a)

    def _show_dock(self):
        self.dock.reposition()
        self.dock.show()
        self.dock.raise_()
        self.dock.start_backdrop()

    def add_icons(self):
        start = ""
        dirs = start_menu_dirs()
        if dirs:
            start = dirs[0]
        files, _ = QFileDialog.getOpenFileNames(
            None,
            T("选择要固定到 Dock 的程序（可多选）"),
            start,
            T("程序与快捷方式 (*.exe *.lnk *.bat *.cmd *.url *.msc *.ps1);;所有文件 (*.*)"))
        if not files:
            return
        added = 0
        for f in files:
            f = os.path.abspath(f)
            if any((not it.get("sep")) and str(it.get("path", "")).lower() == f.lower()
                   for it in self.cfg["items"]):
                continue
            name = os.path.splitext(os.path.basename(f))[0]
            self.cfg["items"].append({"path": f, "name": name})
            added += 1
        save_config(self.cfg)
        self.dock.reload()
        self._show_dock()
        if added:
            self.showMessage(APP_TITLE, T("已添加 %d 个图标到 Dock") % added, make_tray_icon(), 2000)

    def add_separator(self):
        self.cfg["items"].append({"sep": True})
        save_config(self.cfg)
        self.dock.reload()
        self._show_dock()

    def remove_index(self, idx):
        try:
            config_index = self.dock.items[idx].get("config_index")
            if config_index is None:
                return
            self.cfg["items"].pop(config_index)
        except Exception:
            return
        save_config(self.cfg)
        self.dock.reload()

    def set_icon_size(self, px):
        self.cfg["icon_size"] = int(px)
        save_config(self.cfg)
        self.dock.reload()

    def set_bump(self, key):
        self.cfg["bump_level"] = str(key)
        save_config(self.cfg)
        self.dock._recalc(light=True)
        self.dock._kick()

    def set_language(self, val):
        self.cfg["lang"] = "en" if str(val) == "en" else "zh"
        save_config(self.cfg)
        set_lang(self.cfg["lang"])
        self.rebuild()                    # 菜单立刻换成对应语言
        self.dock.update()                # Dock 上的提示文字也跟着换

    def set_blur(self, val):
        self.cfg["blur_px"] = int(val)
        save_config(self.cfg)
        self.dock.refresh_backdrop()      # 立刻按新的模糊程度重抓一次

    def ask_blur(self):
        cur = int(self.cfg.get("blur_px", 6))
        val, ok = QInputDialog.getInt(
            None, APP_TITLE,
            T("毛玻璃模糊强度：\n（3 ~ 30，数字越大越模糊、越朦胧）"),
            cur, 3, 30, 1)
        if ok:
            self.set_blur(val)

    def set_transparency(self, val):
        self.cfg["transparency"] = int(val)
        save_config(self.cfg)
        self.dock.update()

    def set_theme(self, val):
        self.cfg["theme"] = val
        save_config(self.cfg)
        if val == "auto":
            self.dock._sys_light = system_is_light()
        self.dock.update()

    def set_layer(self, val):
        self.cfg["layer"] = val
        save_config(self.cfg)
        self.dock.apply_layer()

    def set_position(self, val):
        if val == "custom":
            self.ask_custom_position()
            return
        self.dock.set_position(val)

    def ask_custom_position(self):
        cur = int(self.cfg.get("custom_bottom", 200))
        val, ok = QInputDialog.getInt(
            None, APP_TITLE,
            T("玻璃条距离屏幕底部多少像素？\n（Dock 始终水平居中，数字越大越往上）"),
            cur, 0, 2000, 5)
        if not ok:
            return
        self.cfg["custom_bottom"] = int(val)
        self.dock.set_position("custom")

    def set_blur_mode(self, val):
        self.cfg["blur_mode"] = val
        save_config(self.cfg)
        self.dock.start_backdrop()

    def refresh_now(self):
        self.dock.refresh_backdrop()

    def custom_icon_size(self):
        cur = int(self.cfg["icon_size"])
        val, ok = QInputDialog.getInt(
            None, APP_TITLE,
            T("请输入图标像素大小：\n（建议 32 ~ 160，数字越大图标越大）"),
            cur, 20, 256, 1)
        if ok:
            self.set_icon_size(val)

    def set_flag(self, key, value, glass=False, running=False, geometry=False):
        self.cfg[key] = bool(value)
        save_config(self.cfg)
        if key == "magnify":
            self.dock._recalc(light=True)
            self.dock._kick()
        if glass:
            self.dock.start_backdrop()
        if running:
            self.dock.refresh_running()
        if geometry:
            self.dock.refresh_geometry()
        self.dock.update()

    def toggle_autostart(self, value):
        ok = set_autostart(bool(value))
        self.cfg["autostart"] = bool(value)
        save_config(self.cfg)
        if ok:
            self.showMessage(APP_TITLE,
                             T("已开启开机自启动") if value else T("已取消开机自启动"),
                             make_tray_icon(), 2000)
        else:
            QMessageBox.warning(None, APP_TITLE, T("设置失败，请查看日志：\n") + LOG_PATH)

    def open_readme(self):
        for name in ("使用说明.txt", "使用说明.md"):
            p = os.path.join(APP_DIR, name)
            if os.path.exists(p):
                os.startfile(p)
                return
        QMessageBox.information(None, APP_TITLE, T("请在托盘菜单里操作：添加图标 / 移除图标。"))


# ----------------------------------------------------------------------------
# 预览模式（用于截图检查外观，不影响正常使用）
# ----------------------------------------------------------------------------
def run_preview(out_path, hover_index=None, size_px=None):
    app = QApplication(sys.argv)
    cfg = load_config()
    if not cfg["items"]:
        demo = []
        for p in (r"C:\Windows\explorer.exe", r"C:\Windows\system32\notepad.exe",
                  r"C:\Windows\system32\mspaint.exe", r"C:\Windows\system32\calc.exe",
                  r"C:\Windows\system32\cmd.exe", r"C:\Windows\system32\mstsc.exe",
                  r"C:\Windows\system32\control.exe"):
            if os.path.exists(p):
                demo.append({"path": p, "name": os.path.splitext(os.path.basename(p))[0]})
        cfg["items"] = demo
    if size_px:
        cfg["icon_size"] = int(size_px)
    dock = Dock(cfg, None, preview=True)
    dock.show()
    app.processEvents()
    if hover_index is not None and 0 <= hover_index < len(dock.items):
        cx = dock.rects[hover_index][0]
        dock.mouse_x = cx
        dock.mouse_smooth = cx
        dock.stretch = 1.0
        dock.stretch_target = 1.0
        dock.spec_x = cx
        dock.spec_alpha = 1.0
        dock.spec_target = 1.0
        dock.hover_index = hover_index
        dock._recalc()
        dock.cur = list(dock.tgt)
        dock._layout()
    app.processEvents()

    # 造一个假的桌面背景，方便看毛玻璃质感
    W, H = 1400, 460
    bg = QImage(W, H, QImage.Format_ARGB32)
    bp = QPainter(bg)
    bp.setRenderHint(QPainter.Antialiasing, True)
    g = QLinearGradient(0, 0, W, H)
    g.setColorAt(0.0, QColor(28, 42, 92))
    g.setColorAt(0.45, QColor(96, 74, 150))
    g.setColorAt(0.75, QColor(196, 108, 140))
    g.setColorAt(1.0, QColor(240, 176, 120))
    bp.fillRect(0, 0, W, H, QBrush(g))
    bp.setBrush(QColor(255, 255, 255, 26))
    bp.setPen(Qt.NoPen)
    for i in range(9):
        bp.drawEllipse(QPointF(W * (0.08 + i * 0.11), H * (0.25 + 0.4 * math.sin(i))), 90, 90)
    bp.end()

    pm = QPixmap(dock.size())
    pm.fill(Qt.transparent)
    dock.render(pm)
    out = QImage(W, H, QImage.Format_ARGB32)
    out.fill(Qt.transparent)
    op = QPainter(out)
    op.drawImage(0, 0, bg)
    x = (W - pm.width()) // 2
    y = H - 46 - pm.height()
    op.drawPixmap(x, y, pm)
    op.end()
    out.save(out_path)
    print("预览已保存:", out_path, "尺寸:", pm.width(), "x", pm.height())
    return 0


# ----------------------------------------------------------------------------
# 主程序
# ----------------------------------------------------------------------------
def main():
    args = sys.argv[1:]
    if "--native-desktop" in args:
        from native_desktop_host import run_native_desktop
        return run_native_desktop(args[args.index("--native-desktop") + 1])

    if "--stop" in args:
        try:
            user32.FindWindowW.restype = wintypes.HWND
            user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
            user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            user32.GetPropW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
            user32.GetPropW.restype = wintypes.HANDLE
            user32.IsWindowVisible.argtypes = [wintypes.HWND]
            user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
            marked, legacy = [], []
            callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            def find_main(candidate, _):
                if user32.GetPropW(candidate, MAIN_WINDOW_MARKER):
                    marked.append(candidate)
                elif user32.IsWindowVisible(candidate):
                    title = ctypes.create_unicode_buffer(256)
                    user32.GetWindowTextW(candidate, title, len(title))
                    if title.value == APP_TITLE:
                        legacy.append(candidate)
                return True
            callback = callback_type(find_main)
            user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
            user32.EnumWindows(callback, 0)
            hwnd = (marked or legacy or [user32.FindWindowW(None, APP_TITLE)])[0]
            if hwnd:
                user32.PostMessageW(hwnd, 0x0010, 0, 0)   # WM_CLOSE
                print("已通知 Dock 退出。")
            else:
                print("没有找到正在运行的 Dock。")
        except Exception:
            print("退出失败：" + traceback.format_exc())
        return 0

    if "--reset" in args:
        cfg = load_config()
        cfg["items"] = []
        save_config(cfg)
        print("已清空 Dock 上固定的图标。")
        return 0

    if "--preview" in args:
        i = args.index("--preview")
        out = args[i + 1] if len(args) > i + 1 else "preview.png"
        hover = None
        if "--hover" in args:
            try:
                hover = int(args[args.index("--hover") + 1])
            except Exception:
                hover = None
        size_px = None
        if "--size" in args:
            try:
                size_px = int(args[args.index("--size") + 1])
            except Exception:
                size_px = None
        return run_preview(out, hover, size_px)

    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)   # 关掉窗口不退出，常驻托盘
    app.setApplicationName(APP_TITLE)

    # 只允许运行一个实例
    shm = QSharedMemory(APP_NAME + "_single_instance")
    if not shm.create(1):
        cfg0 = load_config()
        set_lang(cfg0.get("lang", "zh"))
        QMessageBox.information(None, APP_TITLE, T("Dock 已经在运行了（请看右下角托盘）。"))
        return 0

    cfg = load_config()
    log("配置文件: " + CONFIG_PATH)
    set_lang(cfg.get("lang", "zh"))

    dock = Dock(cfg)
    tray = DockTray(dock)
    dock.tray = tray
    tray.show()
    dock.setup_organizer()
    dock.setup_recycle_bin()

    # 如果配置里开着自启动，就顺手把注册表补/修正一遍（防止你挪动过文件夹）
    if cfg.get("autostart"):
        set_autostart(True)

    if not cfg["items"]:
        tray.showMessage(APP_TITLE,
                         "桌面已启用虚拟分类。点击分类查看内容；右键可一键整理、管理规则。原文件位置保持不变。",
                         make_tray_icon(), 5000)

    from desktop_manager import DesktopManager
    dock.desktop_manager = DesktopManager(SCRIPT_PATH, dock)
    dock.desktop_manager.error.connect(dock.desktop_display_error)
    dock.desktop_manager.ready.connect(lambda: QTimer.singleShot(120, dock.refresh_backdrop)
                                       if dock.isVisible() else None)
    app.aboutToQuit.connect(dock.desktop_manager.stop)
    dock.desktop_manager.update(dock.organizer.groups(), dock.organizer.state["categories"])
    dock.set_desktop_display(cfg.get("desktop_display", "managed"))
    dock.show()
    dock.start_backdrop()
    log("启动完成，共 %d 个图标" % len(dock.items))
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
