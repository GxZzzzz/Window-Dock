# -*- coding: utf-8 -*-
"""管理 Windows 桌面显示与图标布局，不改动文件内容、路径或隐藏属性。"""

import ctypes
import os
import uuid
from contextlib import contextmanager


class _GUID(ctypes.Structure):
    _fields_ = [("data1", ctypes.c_uint32), ("data2", ctypes.c_uint16),
                ("data3", ctypes.c_uint16), ("data4", ctypes.c_ubyte * 8)]


class _VariantValue(ctypes.Union):
    _fields_ = [("integer", ctypes.c_long), ("wide", ctypes.c_longlong),
                ("record", ctypes.c_void_p * 2)]


class _Variant(ctypes.Structure):
    _fields_ = [("vt", ctypes.c_ushort), ("reserved", ctypes.c_ushort * 3),
                ("value", _VariantValue)]


class _ShellState(ctypes.Structure):
    _fields_ = [("flags", ctypes.c_uint32), ("win95", ctypes.c_uint32 * 2),
                ("sort_param", ctypes.c_long), ("sort_direction", ctypes.c_int),
                ("version", ctypes.c_uint32), ("unused", ctypes.c_uint32),
                ("flags2", ctypes.c_uint32)]


_NO_ICONS = 0x1000
_HIDE_ICONS = 1 << 12
_SSF_HIDE_ICONS = 0x4000


def _guid(value):
    return _GUID.from_buffer_copy(uuid.UUID(value).bytes_le)


def _method(pointer, index, *arguments):
    table = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *arguments)(table[index])


def _check(result, operation):
    if result < 0:
        raise OSError("%s失败 (HRESULT 0x%08X)" % (operation, result & 0xffffffff))


@contextmanager
def _desktop_view():
    # 每次操作重新取得桌面视图；不持有 Explorer 句柄，不需要轮询其生命周期。
    ole = ctypes.WinDLL("ole32")
    ole.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    ole.CoInitializeEx.restype = ctypes.c_long
    ole.CoCreateInstance.argtypes = [ctypes.POINTER(_GUID), ctypes.c_void_p,
                                    ctypes.c_uint32, ctypes.POINTER(_GUID),
                                    ctypes.POINTER(ctypes.c_void_p)]
    ole.CoCreateInstance.restype = ctypes.c_long
    initialized = ole.CoInitializeEx(None, 2)
    if initialized < 0 and initialized != -2147417850:  # 已有其他 COM apartment 可继续使用。
        _check(initialized, "初始化桌面接口")
    pointers = []

    def acquire(pointer, index, *ids):
        result = ctypes.c_void_p()
        guids = [_guid(value) for value in ids]
        _check(_method(pointer, index, *([ctypes.POINTER(_GUID)] * len(ids)),
                       ctypes.POINTER(ctypes.c_void_p))(
                           pointer, *[ctypes.byref(g) for g in guids], ctypes.byref(result)),
               "取得桌面接口")
        if not result:
            raise OSError("Windows 桌面视图暂不可用")
        pointers.append(result)
        return result

    try:
        windows = ctypes.c_void_p()
        clsid = _guid("9BA05972-F6A8-11CF-A442-00A0C90A8F39")
        iid = _guid("85CB6900-4D95-11CF-960C-0080C7F4EE85")
        _check(ole.CoCreateInstance(ctypes.byref(clsid), None, 4, ctypes.byref(iid),
                                    ctypes.byref(windows)), "取得 Windows 桌面")
        pointers.append(windows)
        location, empty = _Variant(), _Variant()
        location.vt = 3  # VT_I4，CSIDL_DESKTOP = 0。
        hwnd, dispatch = ctypes.c_long(), ctypes.c_void_p()
        # Windows SDK：IShellWindows.FindWindowSW 15，SWC_DESKTOP 8，SWFO_NEEDDISPATCH 1。
        _check(_method(windows, 15, ctypes.POINTER(_Variant), ctypes.POINTER(_Variant),
                       ctypes.c_int, ctypes.POINTER(ctypes.c_long), ctypes.c_int,
                       ctypes.POINTER(ctypes.c_void_p))(
                           windows, ctypes.byref(location), ctypes.byref(empty), 8,
                           ctypes.byref(hwnd), 1, ctypes.byref(dispatch)), "查找桌面视图")
        if not dispatch:
            raise OSError("Windows 桌面视图暂不可用")
        pointers.append(dispatch)
        provider = acquire(dispatch, 0, "6D5140C1-7436-11CE-8034-00AA006009FA")
        browser = acquire(provider, 3, "4C96BE40-915C-11CF-99D3-00AA004AE837",
                          "000214E2-0000-0000-C000-000000000046")
        view = acquire(browser, 15)
        folder = acquire(view, 0, "1AF3A467-214F-4298-908E-06B03E0B39F9")
        yield folder
    finally:
        for pointer in reversed(pointers):
            _method(pointer, 2)(pointer)
        if initialized >= 0:
            ole.CoUninitialize()


def _flags(view):
    flags = ctypes.c_uint32()
    _check(_method(view, 25, ctypes.POINTER(ctypes.c_uint32))(
        view, ctypes.byref(flags)), "读取桌面显示状态")
    return flags.value


def icons_visible():
    with _desktop_view() as view:
        return not bool(_flags(view) & _NO_ICONS)


def set_icons_visible(visible):
    with _desktop_view() as view:
        before = _flags(view)
        shell = ctypes.WinDLL("shell32")
        shell.SHGetSetSettings.argtypes = [ctypes.POINTER(_ShellState), ctypes.c_uint32,
                                           ctypes.c_int]
        shell.SHGetSetSettings.restype = None
        previous = _ShellState()
        shell.SHGetSetSettings(ctypes.byref(previous), _SSF_HIDE_ICONS, False)
        # 掩码仅包含 NOICONS，保留排列方式、网格和其他桌面设置。
        setter = _method(view, 24, ctypes.c_uint32, ctypes.c_uint32)
        _check(setter(view, _NO_ICONS, 0 if visible else _NO_ICONS), "切换桌面图标")
        try:
            state = _ShellState()
            if not visible:
                state.flags = _HIDE_ICONS
            # 持久化 Shell 设置，让 Explorer 重启后继续遵循该显示选择。
            shell.SHGetSetSettings(ctypes.byref(state), _SSF_HIDE_ICONS, True)
            shell.SHGetSetSettings(ctypes.byref(state), _SSF_HIDE_ICONS, False)
            if bool(state.flags & _HIDE_ICONS) == bool(visible):
                raise OSError("Windows 未保存桌面图标显示设置")
            if (not bool(_flags(view) & _NO_ICONS)) != bool(visible):
                raise OSError("Windows 未应用桌面图标显示设置")
        except Exception:
            shell.SHGetSetSettings(ctypes.byref(previous), _SSF_HIDE_ICONS, True)
            setter(view, _NO_ICONS, before & _NO_ICONS)
            raise


@contextmanager
def shell_interface(pointer, iid):
    """取得临时 COM 接口；调用线程负责已有的 apartment。"""
    value = ctypes.c_void_p()
    guid = _guid(iid)
    _check(_method(pointer, 0, ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p))(
        pointer, ctypes.byref(guid), ctypes.byref(value)), "取得桌面视图接口")
    try:
        yield value
    finally:
        if value:
            _method(value, 2)(value)


def shell_item_key(pidl):
    """桌面 PIDL 相对于桌面根；文件按原路径匹配，系统项目按 PIDL 匹配。"""
    shell = ctypes.WinDLL("shell32")
    shell.SHGetPathFromIDListEx.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p,
                                          ctypes.c_uint32, ctypes.c_uint32]
    shell.ILGetSize.argtypes = [ctypes.c_void_p]
    shell.ILGetSize.restype = ctypes.c_uint
    path = ctypes.create_unicode_buffer(32768)
    if shell.SHGetPathFromIDListEx(pidl, path, len(path), 0):
        return os.path.normcase(os.path.abspath(path.value))
    return "shell:" + ctypes.string_at(pidl, shell.ILGetSize(pidl)).hex()


def view_items(view):
    """读取当前视图的位置，返回值不包含跨进程指针。"""
    count = ctypes.c_int()
    _check(_method(view, 7, ctypes.c_uint, ctypes.POINTER(ctypes.c_int))(
        view, 2, ctypes.byref(count)), "读取桌面项目数量")
    ole = ctypes.WinDLL("ole32")
    ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    result = {}
    for index in range(count.value):
        pidl = ctypes.c_void_p()
        _check(_method(view, 6, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p))(
            view, index, ctypes.byref(pidl)), "读取桌面项目")
        try:
            point = (ctypes.c_long * 2)()
            _check(_method(view, 11, ctypes.c_void_p, ctypes.c_void_p)(
                view, pidl, ctypes.byref(point)), "读取桌面图标位置")
            result[shell_item_key(pidl)] = tuple(point)
        finally:
            ole.CoTaskMemFree(pidl)
    return result


def position_view_items(view, positions):
    """只恢复仍在视图中的项目；不选择项目、不改变文件或排列选项。"""
    count = ctypes.c_int()
    _check(_method(view, 7, ctypes.c_uint, ctypes.POINTER(ctypes.c_int))(
        view, 2, ctypes.byref(count)), "读取桌面项目数量")
    ole = ctypes.WinDLL("ole32")
    ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    pidls, points = [], []
    try:
        for index in range(count.value):
            pidl = ctypes.c_void_p()
            _check(_method(view, 6, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p))(
                view, index, ctypes.byref(pidl)), "读取桌面项目")
            point = positions.get(shell_item_key(pidl))
            if point is None:
                ole.CoTaskMemFree(pidl)
            else:
                pidls.append(pidl.value)
                points.extend(point)
        if pidls:
            ids = (ctypes.c_void_p * len(pidls))(*pidls)
            coords = (ctypes.c_long * len(points))(*points)
            _check(_method(view, 16, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p,
                           ctypes.c_uint)(view, len(pidls), ids, coords, 0xC0000080),
                   "恢复桌面图标位置")  # POSITIONITEM | NOSTATECHANGE | NOTAKEFOCUS。
    finally:
        for pidl in pidls:
            ole.CoTaskMemFree(pidl)


def desktop_snapshot():
    with _desktop_view() as view:
        with shell_interface(view, "000214E3-0000-0000-C000-000000000046") as shell_view:
            hwnd = ctypes.c_void_p()
            _check(_method(shell_view, 3, ctypes.POINTER(ctypes.c_void_p))(
                shell_view, ctypes.byref(hwnd)), "读取桌面窗口")
        user = ctypes.WinDLL("user32")
        user.FindWindowExW.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                       ctypes.c_wchar_p, ctypes.c_wchar_p]
        user.FindWindowExW.restype = ctypes.c_void_p
        icons = user.FindWindowExW(hwnd, None, "SysListView32", None)
        if not icons:
            raise OSError("未找到 Windows 原生桌面图标视图")
        mode, size = ctypes.c_uint(), ctypes.c_int()
        _check(_method(view, 36, ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_int))(
            view, ctypes.byref(mode), ctypes.byref(size)), "读取桌面图标大小")
        return {"host": hwnd.value, "icons": icons, "mode": mode.value,
                "size": size.value, "flags": _flags(view), "positions": view_items(view)}


def restore_stock_view():
    """辅助视图异常退出时，重新显示 Explorer 自己的图标控件。"""
    snapshot = desktop_snapshot()
    user = ctypes.WinDLL("user32")
    user.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
    user.ShowWindow(snapshot["icons"], 5)
