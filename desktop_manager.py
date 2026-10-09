"""向原生桌面连接进程传递分类结果；断开连接时恢复视图项目。"""

import json
import os
import sys
import uuid

from PyQt5.QtCore import QObject, QProcess, QTimer, pyqtSignal
from PyQt5.QtNetwork import QLocalServer

from desktop_visibility import set_icons_visible, restore_stock_view
from organizer import desktop_directories

RECYCLE_KEY = "::{645FF040-5081-101B-9F08-00AA002F954E}"


class DesktopManager(QObject):
    error = pyqtSignal(str)
    ready = pyqtSignal()

    def __init__(self, script_path, parent=None):
        super().__init__(parent)
        self.script_path = script_path
        self.paths = frozenset()
        self.directories = frozenset(desktop_directories())
        self.mode = "all"
        self.socket = None
        self.buffer = b""
        self.stopping = False
        self._failure_message = ""
        self.server = QLocalServer(self)
        self.server.newConnection.connect(self._connected)
        self.process = QProcess(self)
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._process_error)
        self._startup = QTimer(self)
        self._startup.setSingleShot(True)
        # 容纳旧连接退出及有限超时重试；单次启动计时，不增加空闲检查。
        self._startup.setInterval(40000)
        self._startup.timeout.connect(self._startup_timeout)

    def update(self, groups, categories):
        paths = frozenset(entry["path"] for category in categories
                          for entry in groups.get(category["id"], [])
                          if os.path.dirname(entry["path"]) in self.directories)
        if paths != self.paths:
            self.paths = paths
            self._send_paths()

    def set_mode(self, mode):
        if self.mode == mode == "managed" and self.process.state() != QProcess.NotRunning:
            return
        self.stop()
        self.mode = mode
        set_icons_visible(mode != "hidden")
        if mode != "managed":
            return
        self.stopping = False
        self._failure_message = ""
        endpoint = "WindowDock.Desktop." + uuid.uuid4().hex
        if not self.server.listen(endpoint):
            raise OSError(self.server.errorString())
        program = sys.executable
        arguments = ["--native-desktop", endpoint]
        if not getattr(sys, "frozen", False):
            arguments.insert(0, self.script_path)
        self.process.setProgram(program)
        self.process.setArguments(arguments)
        self.process.setWorkingDirectory(os.path.dirname(self.script_path))
        self.process.start()
        self._startup.start()

    def _connected(self):
        incoming = self.server.nextPendingConnection()
        if incoming is None:
            return
        if self.socket is not None:
            incoming.disconnectFromServer()
            incoming.deleteLater()
            return
        self.socket = incoming
        self.buffer = b""
        incoming.readyRead.connect(self._read)
        self._send_paths()

    def _send_paths(self):
        if self.socket:
            self.socket.write((json.dumps({"paths": sorted(self.paths | {RECYCLE_KEY})}, ensure_ascii=False)
                               + "\n").encode("utf-8"))
            self.socket.flush()

    def _read(self):
        if not self.socket:
            return
        self.buffer += bytes(self.socket.readAll())
        while b"\n" in self.buffer:
            line, self.buffer = self.buffer.split(b"\n", 1)
            message = json.loads(line)
            if message.get("error"):
                self._failure_message = message["error"]
            if message.get("ready"):
                self._startup.stop()
                self.ready.emit()

    def _startup_timeout(self):
        self.stop()
        self.mode = "all"
        try:
            restore_stock_view()
        except OSError:
            pass
        self.error.emit("桌面显示服务未能及时启动，已恢复 Windows 桌面图标。")

    def _finished(self, *args):
        self._startup.stop()
        self._close_pipe()
        try:
            if self.mode == "managed":
                restore_stock_view()
        except OSError:
            pass  # Explorer 正在重启时，其新桌面本来就会显示完整图标。
        if not self.stopping and self.mode == "managed":
            self.mode = "all"
            self.error.emit((self._failure_message + "\n" if self._failure_message else "")
                            + "桌面显示服务已退出，已恢复 Windows 桌面图标。")

    def _process_error(self, error):
        if error == QProcess.FailedToStart:
            self._startup.stop()
            self._close_pipe()
            self.mode = "all"
            self.error.emit("桌面显示服务启动失败：" + self.process.errorString())

    def _close_pipe(self):
        if self.socket:
            self.socket.disconnectFromServer()
            self.socket.deleteLater()
            self.socket = None
        self.server.close()

    def stop(self):
        self.stopping = True
        self._startup.stop()
        self._close_pipe()
        if self.process.state() != QProcess.NotRunning:
            # 正常退出由管道断开触发；超时后关闭辅助进程并恢复原控件。
            if not self.process.waitForFinished(6000):
                self.process.kill()
                self.process.waitForFinished(1000)
                restore_stock_view()
