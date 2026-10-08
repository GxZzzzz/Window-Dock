# -*- coding: utf-8 -*-
"""共用文件操作入口：剪贴板只传路径，删除复用后台系统回收接口。"""

import os
import struct

from PyQt5.QtCore import QMimeData, QObject, Qt, QUrl
from PyQt5.QtWidgets import QApplication, QDialog, QHBoxLayout, QVBoxLayout

from category_manager import _GlassDialog, _button, _label
from archive_actions import TOOL_NAMES, archive_arguments, installed_tools, is_archive, launch_archive


# Qt 5 导出时按这个原生名称注册格式；x-qt-windows-mime 包装只用于读取外部格式。
DROP_EFFECT = "Preferred DropEffect"


class _DeleteDialog(_GlassDialog):
    def __init__(self, paths, owner):
        super().__init__(owner, light=owner.is_light())
        self.setWindowTitle("删除项目")
        self.setFixedWidth(440)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 23, 24, 22)
        layout.setSpacing(13)
        layout.addWidget(_label("移入回收站？", name="windowTitle"))
        layout.addWidget(_label("将 %d 个项目移入系统回收站，可在回收站恢复。" % len(paths), wrap=True))
        for path in paths[:4]:
            label = _label(os.path.basename(path), muted=True, wrap=True)
            label.setTextFormat(Qt.PlainText)
            label.setToolTip(path)
            layout.addWidget(label)
        if len(paths) > 4:
            layout.addWidget(_label("以及另外 %d 个项目" % (len(paths) - 4), muted=True))
        layout.addWidget(_label("快捷方式只删除入口，不影响它指向的程序或文件。", muted=True, wrap=True))
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = _button("取消", self.reject)
        buttons.addWidget(cancel)
        buttons.addWidget(_button("移入回收站", self.accept, primary=True))
        layout.addLayout(buttons)
        cancel.setFocus()
        self.adjustSize()
        screen = owner.screen() or QApplication.primaryScreen()
        area = screen.availableGeometry()
        self.move(area.center() - self.rect().center())
        self.capture_background(screen)


class FileActions(QObject):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        # 启动时发现一次，右键交互不承担冷启动的注册表和磁盘查询。
        self.archive_tools = installed_tools()

    def add_menu(self, menu, paths):
        commands = {}
        for command, text, shortcut in (("copy", "复制", "Ctrl+C"),
                                        ("cut", "剪切", "Ctrl+X"),
                                        ("delete", "删除…", "Delete")):
            action = menu.addAction(menu.glyph(command), text + "\t" + shortcut)
            action.setEnabled(bool(paths))
            if command == "delete":
                service = self.owner.recycle_bin
                action.setEnabled(bool(paths) and service is not None
                                  and not service.busy and not service.stopping)
                action.setToolTip("移入系统回收站；快捷方式只删除入口本身")
            commands[action] = command
        menu.addSeparator()
        tools = self.archive_tools
        for operation, title, icon in (("compress", "压缩…", "compress"), ("extract", "解压…", "extract")):
            submenu = menu.addMenu(menu.glyph(icon), title)
            available = bool(paths) and bool(tools) and (operation == "compress" or all(is_archive(path) for path in paths))
            submenu.menuAction().setEnabled(available)
            if not tools:
                submenu.menuAction().setToolTip("未找到 Bandizip 或 7-Zip，安装或加入 PATH 后重启 Dock")
            elif operation == "extract" and not available:
                submenu.menuAction().setToolTip("请选择压缩包；支持同时选中多个压缩包")
            for tool in tools:
                action = submenu.addAction(submenu.glyph(icon), TOOL_NAMES[tool] + "…")
                action.setToolTip("在 %s 中选择格式与保存位置" % TOOL_NAMES[tool] if operation == "compress"
                                  else "在 %s 中选择解压位置，保留同名文件询问" % TOOL_NAMES[tool])
                commands[action] = operation + ":" + tool
            submenu.setToolTipsVisible(True)
        menu.setToolTipsVisible(True)
        return commands

    def perform(self, command, paths):
        # 对入口本身操作，始终不把 .lnk 替换成其目标路径。
        paths = list(dict.fromkeys(os.path.abspath(path) for path in paths if path))
        if not paths:
            return False
        if command.startswith(("compress:", "extract:")):
            operation, tool = command.split(":", 1)
            executable = self.archive_tools.get(tool)
            if not executable:
                self.owner.organizer_message("压缩与解压", "未找到压缩软件，请安装后重启 Dock。")
                return False
            if operation == "extract" and not all(is_archive(path) for path in paths):
                return False
            try:
                arguments = archive_arguments(tool, operation, paths)
                launch_archive(executable, arguments, os.path.dirname(paths[0]))
            except OSError as error:
                detail = "选中项目的路径总长度过长，请分批操作。" if getattr(error, "winerror", None) == 206 else str(error)
                self.owner.organizer_message("压缩与解压", "无法启动 %s：%s" % (TOOL_NAMES[tool], detail))
                return False
            return True
        if command in ("copy", "cut"):
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(path) for path in paths])
            # Explorer 用这个 DWORD 区分复制和移动；剪切时仍不立即改动文件。
            mime.setData(DROP_EFFECT, struct.pack("<I", 2 if command == "cut" else 1))
            clipboard = QApplication.clipboard()
            clipboard.setMimeData(mime)
            if not clipboard.ownsClipboard():
                self.owner.organizer_message("剪贴板", "剪贴板暂时不可用，请重试。")
                return False
            return True
        if command == "delete":
            service = self.owner.recycle_bin
            if service is None or service.busy or service.stopping:
                self.owner.organizer_message("删除项目", "回收站暂时不可用，请稍后重试。")
                return False
            dialog = _DeleteDialog(paths, self.owner)
            accepted = dialog.exec_() == QDialog.Accepted
            dialog.deleteLater()
            return accepted and service.recycle(paths)
        return False
