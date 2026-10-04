"""连接 Explorer 自己的桌面视图；仅在连接或文件事件时工作。"""

import ctypes as C
from ctypes import wintypes as W
import json
from pathlib import Path
import sys
import threading

from PyQt5.QtCore import QTimer, QEventLoop, pyqtSignal
from PyQt5.QtNetwork import QLocalSocket
from PyQt5.QtWidgets import QApplication, QWidget

from desktop_visibility import _desktop_view, shell_interface, _method, _check

P = C.c_void_p
READY, CLOSED = 0x8351, 0x8352
user = C.WinDLL('user32', use_last_error=True)
kernel = C.WinDLL('kernel32', use_last_error=True)
user.SetWindowsHookExW.argtypes = [C.c_int, P, P, C.c_uint]
user.SetWindowsHookExW.restype = P
user.UnhookWindowsHookEx.argtypes = [P]
user.RegisterWindowMessageW.argtypes = [C.c_wchar_p]
user.GetWindowThreadProcessId.argtypes = [P, C.POINTER(C.c_uint)]
user.PostThreadMessageW.argtypes = [C.c_uint, C.c_uint, C.c_size_t, C.c_ssize_t]
user.SendMessageTimeoutW.argtypes = [P, C.c_uint, C.c_size_t, C.c_ssize_t,
                                    C.c_uint, C.c_uint, C.POINTER(C.c_size_t)]
user.SendMessageTimeoutW.restype = C.c_ssize_t
kernel.OpenProcess.argtypes = [C.c_uint, C.c_int, C.c_uint]
kernel.OpenProcess.restype = P
kernel.CreateEventW.argtypes = [P, C.c_int, C.c_int, C.c_wchar_p]
kernel.CreateEventW.restype = P
kernel.SetEvent.argtypes = [P]
kernel.WaitForMultipleObjects.argtypes = [C.c_uint, C.POINTER(P), C.c_int, C.c_uint]
kernel.CloseHandle.argtypes = [P]


class CopyData(C.Structure):
    _fields_ = [('tag', C.c_size_t), ('length', C.c_uint), ('data', P)]


class NativeDesktop(QWidget):
    ready = pyqtSignal()
    error = pyqtSignal(str)
    explorer_exited = pyqtSignal()
    stats_received = pyqtSignal(object)
    closed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        root = Path(getattr(sys, '_MEIPASS', Path(__file__).parent))
        self.library = C.WinDLL(str(root / 'native_desktop' / 'WindowDockDesktop.dll'))
        self.hook = None
        self.bridge = None
        self.cancel = None
        self.watcher = None
        self.stopping = False
        self.connect_message = user.RegisterWindowMessageW('WindowDock.NativeDesktop.Connect.v1')
        self.winId()  # 仅作 IPC 接收端；从不显示窗口，不占用桌面层级。
        self.timeout = QTimer(self)
        self.timeout.setSingleShot(True)
        self.timeout.setInterval(8000)
        self.timeout.timeout.connect(self._timeout)

    def connect_desktop(self):
        self.stopping = False
        with _desktop_view() as view:
            with shell_interface(view, '000214E3-0000-0000-C000-000000000046') as shell_view:
                hwnd = P()
                _check(_method(shell_view, 3, C.POINTER(P))(shell_view, C.byref(hwnd)), '读取原生桌面窗口')
        pid = C.c_uint()
        thread = user.GetWindowThreadProcessId(hwnd, C.byref(pid))
        self.hook = user.SetWindowsHookExW(3, C.cast(self.library.DesktopConnect, P),
                                          self.library._handle, thread)
        if not self.hook:
            raise C.WinError(C.get_last_error())
        if not user.PostThreadMessageW(thread, self.connect_message, int(self.winId()), 0):
            self._unhook()
            raise C.WinError(C.get_last_error())
        process = kernel.OpenProcess(0x100000, False, pid.value)
        cancel = kernel.CreateEventW(None, True, False, None)
        if not process or not cancel:
            if process:
                kernel.CloseHandle(process)
            if cancel:
                kernel.CloseHandle(cancel)
            self._unhook()
            raise OSError('无法监测 Explorer 生命周期')
        self.cancel = cancel
        # 等待内核对象，不占用 Qt 线程，也没有每秒检查进程的循环。
        def watch():
            result = kernel.WaitForMultipleObjects(2, (P * 2)(cancel, process), False, 0xffffffff)
            if result == 1:
                self.explorer_exited.emit()
            kernel.CloseHandle(process)
            # cancel 由 stop() 在线程离开等待后关闭。
        self.watcher = threading.Thread(target=watch, name='Explorer lifetime', daemon=True)
        self.watcher.start()
        self.timeout.start()

    def _unhook(self):
        if self.hook:
            user.UnhookWindowsHookEx(self.hook)
            self.hook = None

    def _timeout(self):
        self._unhook()
        self.error.emit('原生桌面组件连接超时')

    def nativeEvent(self, event_type, message):
        msg = W.MSG.from_address(int(message))
        if msg.message == READY:
            self.timeout.stop()
            self._unhook()
            hr = C.c_long(msg.lParam).value
            if hr < 0 or not msg.wParam:
                self.error.emit('当前 Windows 原生桌面不支持收纳 (0x%08X)' % (hr & 0xffffffff))
            else:
                self.bridge = int(msg.wParam)
                self.ready.emit()
            return True, 0
        if msg.message == CLOSED:
            self.bridge = None
            self.closed.emit()
            if not self.stopping:
                hr = C.c_long(msg.lParam).value
                self.error.emit('原生桌面收纳已停止 (0x%08X)' % (hr & 0xffffffff))
            return True, 0
        if msg.message == 0x4a:
            data = C.cast(msg.lParam, C.POINTER(CopyData)).contents
            if data.tag == 2 and data.length == 48:
                self.stats_received.emit(list(C.cast(data.data, C.POINTER(C.c_uint64 * 6)).contents))
            return True, 1
        return super().nativeEvent(event_type, message)

    def send(self, tag, payload=b'\0\0'):
        if not self.bridge:
            return
        buffer = C.create_string_buffer(payload)
        data = CopyData(tag, len(payload), C.cast(buffer, P))
        result = C.c_size_t()
        if not user.SendMessageTimeoutW(self.bridge, 0x4a, int(self.winId()), C.addressof(data),
                                       2, 5000, C.byref(result)):
            raise C.WinError(C.get_last_error())
        _check(C.c_long(result.value).value, '应用原生桌面收纳')

    def set_paths(self, paths):
        self.send(1, ('\0'.join(paths) + '\0\0').encode('utf-16-le'))

    def stop(self):
        if self.stopping:
            return
        self.stopping = True
        self.timeout.stop()
        self._unhook()
        if self.cancel:
            kernel.SetEvent(self.cancel)
            self.watcher.join(1)
            if not self.watcher.is_alive():
                kernel.CloseHandle(self.cancel)
            self.cancel = None
        if self.bridge:
            result = C.c_size_t()
            loop = QEventLoop()
            expiry = QTimer()
            expiry.setSingleShot(True)
            expiry.timeout.connect(loop.quit)
            self.closed.connect(loop.quit)
            user.SendMessageTimeoutW(self.bridge, 0x8354, 0, 0, 2, 5000, C.byref(result))
            if self.bridge:
                expiry.start(5500)
                loop.exec_()
            self.closed.disconnect(loop.quit)
            self.bridge = None


def run_native_desktop(endpoint):
    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    socket = QLocalSocket()
    paths = []
    buffer = bytearray()
    attempts = 0
    finished = False
    native = None
    reconnect = QTimer()
    reconnect.setSingleShot(True)
    reconnect.setInterval(500)

    def report(message):
        socket.write((json.dumps(message, ensure_ascii=False) + '\n').encode('utf-8'))
        socket.flush()

    def stop():
        nonlocal finished
        finished = True
        reconnect.stop()
        if native:
            native.stop()
        app.quit()

    def fail(message):
        report({'error': message})
        stop()

    def apply():
        try:
            native.set_paths(paths)
        except OSError as error:
            fail(str(error))

    def ready():
        nonlocal attempts
        attempts = 0
        # 避开 Windows 回调重入；完成分类投递后再通知主 Dock。
        QTimer.singleShot(0, apply_ready)

    def apply_ready():
        apply()
        if not finished:
            report({'ready': True})

    def start():
        nonlocal attempts
        if finished:
            return
        attempts += 1
        try:
            native.connect_desktop()
        except OSError as error:
            if attempts < 20:
                reconnect.start()
            else:
                fail(str(error))

    def explorer_exited():
        native.bridge = None
        native.stop()
        if not finished:
            reconnect.start()

    def read():
        nonlocal paths
        buffer.extend(bytes(socket.readAll()))
        while b'\n' in buffer:
            line, _, rest = buffer.partition(b'\n')
            buffer[:] = rest
            message = json.loads(line)
            paths = message.get('paths', [])
        if native and native.bridge:
            apply()

    socket.readyRead.connect(read)
    socket.disconnected.connect(stop)
    socket.errorOccurred.connect(lambda _: stop())
    socket.connectToServer(endpoint)
    if not socket.waitForConnected(3000):
        return 1
    try:
        native = NativeDesktop()
        native.ready.connect(ready)
        native.error.connect(fail)
        native.explorer_exited.connect(explorer_exited)
        reconnect.timeout.connect(start)
        QTimer.singleShot(0, start)
        app.aboutToQuit.connect(native.stop)
        return app.exec_()
    except OSError as error:
        report({'error': str(error)})
        return 1
