# -*- coding: utf-8 -*-
"""Dock 内部虚拟拖动：用鼠标释放位置提交，不向 Explorer 发出文件复制请求。"""

import time

from PyQt5.QtCore import QEvent, QObject, QPoint, QRectF, Qt
from PyQt5.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import QApplication, QWidget


class _DragPreview(QWidget):
    def __init__(self):
        super().__init__(None, Qt.ToolTip | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.resize(220, 78)
        self.icon = QPixmap()
        self.count = 1
        self.hint = ""

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(255, 255, 255, 75), 1))
        p.setBrush(QColor(34, 29, 45, 235))
        p.drawRoundedRect(QRectF(.5, .5, self.width() - 1, self.height() - 1), 13, 13)
        if not self.icon.isNull():
            p.drawPixmap(10, 9, self.icon.scaled(40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        p.setPen(QColor("#f4f1fb"))
        p.setFont(QFont("Microsoft YaHei UI", 9))
        p.drawText(QRectF(60, 10, 150, 36), Qt.AlignVCenter,
                   "%d 个项目" % self.count if self.count > 1 else "拖动项目")
        p.setPen(QColor("#c9c4d7"))
        p.drawText(QRectF(10, 49, 200, 22), Qt.AlignVCenter,
                   p.fontMetrics().elidedText(self.hint, Qt.ElideRight, 200))


class EntryDrag(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.active = False
        self.preview = _DragPreview()
        self.source = None
        self._move = self._drop = self._cancel = None
        self._last_move = 0.0
        QApplication.instance().aboutToQuit.connect(self.cancel)

    def begin(self, source, paths, icon, position, move, drop, cancel):
        self.cancel()
        self.active = True
        self.source = source
        self.paths = list(paths)
        self._move, self._drop, self._cancel = move, drop, cancel
        self.preview.icon = icon
        self.preview.count = len(paths)
        source.installEventFilter(self)
        source.grabMouse()
        source.grabKeyboard()
        self.preview.show()
        self._last_move = time.perf_counter()
        self.update_position(position)

    def update_position(self, position):
        self.preview.move(position + QPoint(15, 15))
        hint = self._move(position) or "Esc 取消"
        if hint != self.preview.hint:
            self.preview.hint = hint
            self.preview.update()

    def finish(self, position=None):
        if not self.active:
            return
        source, callback = self.source, self._drop if position is not None else self._cancel
        self.active = False
        self.source = None
        source.removeEventFilter(self)
        source.releaseMouse()
        source.releaseKeyboard()
        self.preview.hide()
        self._move = self._drop = self._cancel = None
        if position is None:
            callback()
        else:
            callback(position)

    def cancel(self):
        self.finish()

    def eventFilter(self, watched, event):
        if not self.active or watched is not self.source:
            return False
        if event.type() == QEvent.MouseMove:
            # 高回报率鼠标最多更新约 120 次/秒，放手仍以释放事件的精确位置提交。
            now = time.perf_counter()
            if now - self._last_move >= .008:
                self._last_move = now
                self.update_position(event.globalPos())
            return True
        if event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            self.finish(event.globalPos())
            return True
        if event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape:
            self.cancel()
            return True
        if event.type() in (QEvent.KeyPress, QEvent.KeyRelease, QEvent.ShortcutOverride):
            event.accept()
            return True
        if event.type() in (QEvent.Hide, QEvent.Close, QEvent.UngrabMouse):
            self.cancel()
        return False
