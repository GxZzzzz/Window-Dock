"""系统回收站入口：Shell 通知触发更新，查询和文件操作共用一个休眠工作线程。"""

import ctypes
from ctypes import wintypes
from concurrent.futures import ThreadPoolExecutor
import os
import sys

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import QWidget

RECYCLE_KEY = "::{645FF040-5081-101B-9F08-00AA002F954E}"
_NOTIFY = 0x8431


class _NotifyEntry(ctypes.Structure):
    _fields_ = [("pidl", ctypes.c_void_p), ("recursive", wintypes.BOOL)]


class _QueryInfo(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("bytes", ctypes.c_longlong),
                ("items", ctypes.c_longlong)]


class RecycleBin(QWidget):
    changed = pyqtSignal()
    error = pyqtSignal(str)
    _done = pyqtSignal(str, object)

    def __init__(self, owner):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint)
        self.owner = owner
        self.count = None
        self.busy = False
        self.stopping = False
        self._query_pending = False
        self._query_again = False
        self._registrations = []
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="RecycleBin")
        self._done.connect(self._finished)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(250)
        self._debounce.timeout.connect(self.refresh)
        self._shell = ctypes.WinDLL("shell32", use_last_error=True)
        shell = self._shell
        shell.SHChangeNotifyRegister.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long,
                                                 ctypes.c_uint, ctypes.c_int,
                                                 ctypes.POINTER(_NotifyEntry)]
        shell.SHChangeNotifyRegister.restype = wintypes.ULONG
        shell.SHChangeNotifyDeregister.argtypes = [wintypes.ULONG]
        shell.SHChangeNotification_Lock.argtypes = [wintypes.HANDLE, wintypes.DWORD,
            ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_long)]
        shell.SHChangeNotification_Lock.restype = wintypes.HANDLE
        shell.SHChangeNotification_Unlock.argtypes = [wintypes.HANDLE]
        shell.SHGetSpecialFolderLocation.argtypes = [wintypes.HWND, ctypes.c_int,
                                                    ctypes.POINTER(ctypes.c_void_p)]
        shell.SHQueryRecycleBinW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(_QueryInfo)]
        shell.SHQueryRecycleBinW.restype = ctypes.c_long
        shell.SHEmptyRecycleBinW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.DWORD]
        shell.SHEmptyRecycleBinW.restype = ctypes.c_long
        base = getattr(sys, "_MEIPASS", os.path.dirname(__file__))
        self._native = ctypes.WinDLL(os.path.join(base, "native_desktop", "WindowDockDesktop.dll"))
        self._native.RecyclePaths.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
        self._native.RecyclePaths.restype = ctypes.c_long
        pidl = ctypes.c_void_p()
        result = shell.SHGetSpecialFolderLocation(None, 10, ctypes.byref(pidl))
        if result >= 0:
            try:
                entry = _NotifyEntry(pidl.value, True)
                registration = shell.SHChangeNotifyRegister(int(self.winId()), 0x8002,
                    0x7FFFFFFF, _NOTIFY, 1, ctypes.byref(entry))
                if registration:
                    self._registrations.append(registration)
            finally:
                ole = ctypes.WinDLL("ole32")
                ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
                ole.CoTaskMemFree(pidl)
        # 空/满切换有时只广播系统图标变化，不携带回收站 PIDL。
        entry = _NotifyEntry(None, True)
        registration = shell.SHChangeNotifyRegister(int(self.winId()), 0x8002, 0x8000,
                                                     _NOTIFY, 1, ctypes.byref(entry))
        if registration:
            self._registrations.append(registration)
        self.refresh()

    def nativeEvent(self, kind, message):
        msg = wintypes.MSG.from_address(int(message))
        if msg.message == _NOTIFY:
            pidls = ctypes.c_void_p()
            event = ctypes.c_long()
            lock = self._shell.SHChangeNotification_Lock(msg.wParam, msg.lParam,
                                                        ctypes.byref(pidls), ctypes.byref(event))
            if lock:
                self._shell.SHChangeNotification_Unlock(lock)
                if not self.stopping:
                    self._debounce.start()
            return True, 0
        return super().nativeEvent(kind, message)

    def _submit(self, kind, work):
        def complete(future):
            try:
                result = future.result()
            except Exception as error:
                result = error
            if not self.stopping:
                self._done.emit(kind, result)
        self._pool.submit(work).add_done_callback(complete)

    def refresh(self):
        if self.stopping:
            return
        if self._query_pending:
            self._query_again = True
            return
        self._query_pending = True
        def query():
            info = _QueryInfo()
            info.size = ctypes.sizeof(info)
            result = self._shell.SHQueryRecycleBinW(None, ctypes.byref(info))
            if result < 0:
                raise OSError("回收站状态读取失败：0x%08X" % (result & 0xFFFFFFFF))
            return info.items
        self._submit("query", query)

    def open(self):
        try:
            os.startfile("shell:RecycleBinFolder")
            self.refresh()
        except OSError as error:
            self.error.emit(str(error))

    def recycle(self, paths):
        if self.busy or self.stopping or not paths:
            return False
        self.busy = True
        self.changed.emit()
        owner = int(self.owner.winId())
        # 保留完整 Unicode 路径；只删除拖入的快捷方式本身，不解析目标。
        paths = list(dict.fromkeys(os.path.abspath(path) for path in paths))
        payload = "\0".join(paths) + "\0\0"
        self._submit("recycle", lambda: self._native.RecyclePaths(owner, payload))
        return True

    def empty(self):
        if self.busy or self.stopping or self.count == 0:
            return
        self.busy = True
        self.changed.emit()
        owner = int(self.owner.winId())
        # flags=0 保留 Windows 的清空确认；绝不自动确认永久删除。
        self._submit("empty", lambda: self._shell.SHEmptyRecycleBinW(owner, None, 0))

    def _finished(self, kind, result):
        if kind == "query":
            self._query_pending = False
            if not isinstance(result, Exception) and result != self.count:
                self.count = result
                self.changed.emit()
            if self._query_again:
                self._query_again = False
                self._debounce.start()
            return
        self.busy = False
        self.changed.emit()
        if isinstance(result, Exception):
            self.error.emit(str(result))
        elif result < 0 and (result & 0xFFFFFFFF) not in (0x800704C7, 0x80270000):
            detail = ("此位置不支持安全回收，已停止操作。" if (result & 0xFFFFFFFF) == 0x80070032
                      else "操作未全部完成（0x%08X），请查看回收站及原文件。" % (result & 0xFFFFFFFF))
            self.error.emit(detail)
        self.refresh()

    def stop(self):
        self.stopping = True
        self._debounce.stop()
        for registration in self._registrations:
            self._shell.SHChangeNotifyDeregister(registration)
        self._registrations.clear()
        self._pool.shutdown(wait=False, cancel_futures=True)
