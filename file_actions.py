# -*- coding: utf-8 -*-
"""共用文件操作入口：剪贴板只传路径，删除复用后台系统回收接口。"""

import os
import struct

from PyQt5.QtCore import QMimeData, QObject, Qt, QUrl
from PyQt5.QtWidgets import QApplication, QDialog, QHBoxLayout, QVBoxLayout

from category_manager import _GlassDialog, _button, _label


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
        return commands

    def perform(self, command, paths):
        # 对入口本身操作，始终不把 .lnk 替换成其目标路径。
        paths = list(dict.fromkeys(os.path.abspath(path) for path in paths if path))
        if not paths:
            return False
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
