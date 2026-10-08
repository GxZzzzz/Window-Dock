# -*- coding: utf-8 -*-
"""按需调用已安装的压缩软件；Dock 不扫描文件内容，也不驻留压缩进程。"""

import ctypes
from functools import lru_cache
import os
import shutil
import subprocess
import sys


TOOL_NAMES = {"bandizip": "Bandizip", "7zip": "7-Zip"}
ARCHIVE_SUFFIXES = (".zip", ".zipx", ".7z", ".rar", ".tar", ".gz", ".tgz",
                    ".bz2", ".tbz", ".tbz2", ".xz", ".txz", ".iso", ".cab",
                    ".wim", ".lzma", ".zst", ".lz", ".lzh", ".egg", ".alz",
                    ".7z.001", ".zip.001")


def is_archive(path):
    return path.lower().endswith(ARCHIVE_SUFFIXES) and not os.path.isdir(path)


@lru_cache(maxsize=1)
def installed_tools():
    """查注册表和固定位置，后续复用结果，不遍历磁盘。"""
    candidates = {key: [] for key in TOOL_NAMES}
    if sys.platform == "win32":
        import winreg
        registry = (
            ("bandizip", r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\Bandizip.exe", "", None),
            ("7zip", r"SOFTWARE\7-Zip", "Path", "7zG.exe"),
            ("7zip", r"SOFTWARE\7-Zip", "Path64", "7zG.exe"),
            ("7zip", r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\7zFM.exe", "", "7zG.exe"),
            ("7zip", r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\7zG.exe", "", None),
        )
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
                for tool, key, value, sibling in registry:
                    try:
                        with winreg.OpenKey(hive, key, 0, winreg.KEY_READ | view) as entry:
                            path = os.path.expandvars(winreg.QueryValueEx(entry, value)[0]).strip('"')
                        if sibling:
                            path = os.path.join(os.path.dirname(path) if value == "" else path, sibling)
                        candidates[tool].append(path)
                    except OSError:
                        pass
    for tool, exe, folder in (("bandizip", "Bandizip.exe", "Bandizip"), ("7zip", "7zG.exe", "7-Zip")):
        path = shutil.which(exe)
        if path:
            candidates[tool].append(path)
        for variable in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            base = os.environ.get(variable)
            if base:
                candidates[tool].append(os.path.join(base, folder, exe))
    result = {}
    for tool, paths in candidates.items():
        for path in dict.fromkeys(paths):
            if os.path.isfile(path):
                result[tool] = os.path.abspath(path)
                break
    return result


def _archive_name(paths):
    first = paths[0]
    base = os.path.basename(first.rstrip("\\/"))
    if not os.path.isdir(first):
        base = os.path.splitext(base)[0]
    base = base if len(paths) == 1 else "压缩文件"
    parent = os.path.dirname(first)
    filename = os.path.join(parent, base + ".zip")
    count = 2
    # 给新建窗口建议一个空闲名称，不默认修改已有压缩包。
    while os.path.exists(filename):
        filename = os.path.join(parent, "%s (%d).zip" % (base, count))
        count += 1
    return filename


def archive_arguments(tool, operation, paths):
    """全部参数按原始 Unicode 路径传递，格式、密码和目标位置仍由原软件窗口选择。"""
    if operation == "compress":
        name = _archive_name(paths)
        if tool == "bandizip":
            return ["cd", name, *paths]
        return ["a", "-ad", "-tzip", "-spd", name, "--", *paths]
    parent = os.path.dirname(paths[0])
    if tool == "bandizip":
        return ["bx", "-target:dlg", "-o:" + parent, *paths]
    # -an/-ai 将多选压缩包作为档案集合；-ad 保留目标路径、密码与覆盖询问。
    return ["x", "-ad", "-spd", "-an", "-o" + parent,
            *("-ai!" + path for path in paths)]


def launch_archive(executable, arguments, directory):
    env = os.environ.copy()
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        # PyInstaller 的 DLL 搜索目录不能传给外部压缩软件，创建进程后立即恢复。
        prefix = os.path.normcase(os.path.abspath(bundle)).rstrip("\\/")
        env["PATH"] = os.pathsep.join(path for path in env.get("PATH", "").split(os.pathsep)
                                      if not os.path.normcase(os.path.abspath(path)).startswith(prefix + os.sep)
                                      and os.path.normcase(os.path.abspath(path)) != prefix)
    reset = sys.platform == "win32" and bundle
    if reset:
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.SetDllDirectoryW.argtypes = [ctypes.c_wchar_p]
        kernel.SetDllDirectoryW.restype = ctypes.c_int
        kernel.SetDllDirectoryW(None)
    try:
        return subprocess.Popen([executable, *arguments], cwd=directory, env=env, close_fds=True)
    finally:
        if reset:
            kernel.SetDllDirectoryW(bundle)
