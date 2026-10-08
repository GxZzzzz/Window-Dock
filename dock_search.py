# -*- coding: utf-8 -*-
"""已有入口的轻量搜索；复用分类索引和图标队列，不遍历磁盘。"""

import heapq
import os
import unicodedata
from collections import Counter

from PyQt5.QtCore import (QAbstractListModel, QEasingCurve, QEvent, QPoint, QPointF, QRect, QRectF,
                          QSize, Qt, QThread, QTimer, QVariantAnimation, pyqtSignal)
from PyQt5.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PyQt5.QtWidgets import (QAbstractItemView, QApplication, QGraphicsOpacityEffect, QLabel, QLineEdit,
                             QListView, QStyle, QStyledItemDelegate, QToolButton, QWidget)

from organizer import normalize_path
from organizer_ui import _entry_label, _GlassSurface, _stylesheet
from menu_ui import ThemedMenu


def _fold(text):
    return unicodedata.normalize("NFKC", str(text)).casefold()


def search_snapshot(service, pinned):
    """只复制共享索引中的元数据；不解析快捷方式，也不检查文件系统。"""
    categories = {c["id"]: c["name"] for c in service.state["categories"]}
    categories["__uncategorized__"] = "未分类"
    entries = {}
    for cid, group in service.groups().items():
        for item in group:
            key = normalize_path(item["path"])
            entry = dict(item, label=_entry_label(item), category=categories.get(cid, "未分类"))
            entries[key] = entry
    for item in pinned:
        path = item.get("path")
        if not path or item.get("sep"):
            continue
        key = normalize_path(path)
        if key in entries:
            entries[key]["alias"] = item.get("name", "")
            continue
        name = os.path.basename(path)
        kind = "apps" if os.path.splitext(path)[1].lower() in {".exe", ".lnk", ".url", ".appref-ms"} else ""
        entry = {"path": path, "name": name, "kind": kind, "category": "固定入口"}
        # 固定入口可有自定义名称；普通文件仍用完整文件名避免丢失后缀。
        entry["label"] = (item.get("name") or _entry_label(entry)) if kind else name
        entry["alias"] = item.get("name", "")
        entries[key] = entry
    return tuple(entries.values())


class _SearchTask(QThread):
    ready = pyqtSignal(int, object, int)

    def __init__(self, generation, entries, query, parent=None):
        super().__init__(parent)
        self.generation, self.entries, self.query = generation, entries, query

    def run(self):
        query = _fold(self.query).strip()
        tokens = query.split()
        matches = []
        for ordinal, entry in enumerate(self.entries):
            if ordinal % 64 == 0 and self.isInterruptionRequested():
                return
            label = _fold(entry["label"])
            names = " ".join((label, _fold(entry.get("name", "")), _fold(entry.get("alias", ""))))
            if all(token in names for token in tokens):
                rank = 0 if label == query else 1 if label.startswith(query) else 2
                matches.append((rank, len(label), label, ordinal, entry))
        if self.isInterruptionRequested():
            return
        # 限制一次展示量，避免宽泛查询创建成千上万个可见结果。
        selected = [dict(row[-1]) for row in heapq.nsmallest(200, matches)]
        duplicates = Counter(_fold(row[-1]["label"]) for row in matches)
        for item in selected:
            item["subtitle"] = item["category"]
            if duplicates[_fold(item["label"])] > 1:
                item["subtitle"] += "  ·  " + os.path.dirname(item["path"])
        self.ready.emit(self.generation, selected, len(matches))


class _ResultModel(QAbstractListModel):
    def __init__(self, icon_source, parent):
        super().__init__(parent)
        self.items = []
        self.rows = {}
        self.icon_source = icon_source
        icon_source.iconReady.connect(self._icon_ready)

    def replace(self, items):
        self.beginResetModel()
        self.items = items
        self.rows = {normalize_path(item["path"]): i for i, item in enumerate(items)}
        self.endResetModel()

    def rowCount(self, parent=None):
        return 0 if parent is not None and parent.isValid() else len(self.items)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.items):
            return None
        item = self.items[index.row()]
        if role == Qt.DisplayRole:
            return item["label"]
        if role == Qt.UserRole:
            return item
        if role == Qt.ToolTipRole:
            return item["label"] + "\n" + item["category"] + "\n" + item["path"]
        if role == Qt.DecorationRole:
            return self.icon_source.request_icon(item["path"]) or self.icon_source.fallback

    def _icon_ready(self, path):
        row = self.rows.get(path)
        if row is not None and self.parent().expanded:
            ix = self.index(row, 0)
            self.dataChanged.emit(ix, ix, [Qt.DecorationRole])


class _ResultDelegate(QStyledItemDelegate):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner

    def sizeHint(self, option, index):
        return QSize(240, self.owner.px(56))

    def paint(self, painter, option, index):
        light = self.owner.light
        px = self.owner.px
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        box = option.rect.adjusted(2, 2, -2, -2)
        if option.state & (QStyle.State_Selected | QStyle.State_MouseOver):
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(104, 133, 191, 37 if light else 61))
            painter.drawRoundedRect(QRectF(box), px(11), px(11))
        icon = index.data(Qt.DecorationRole)
        if icon:
            icon.paint(painter, QRect(box.left() + px(12), box.center().y() - px(14), px(28), px(28)))
        text = box.adjusted(px(52), px(5), -px(12), -px(5))
        font = QFont("Microsoft YaHei UI")
        font.setPixelSize(px(13))
        painter.setFont(font)
        painter.setPen(QColor("#253041" if light else "#f2f4fb"))
        name = painter.fontMetrics().elidedText(index.data(Qt.DisplayRole), Qt.ElideMiddle, text.width())
        painter.drawText(QRect(text.left(), text.top(), text.width(), px(23)), Qt.AlignVCenter, name)
        font.setPixelSize(px(11))
        painter.setFont(font)
        painter.setPen(QColor("#68748a" if light else "#a9b4cb"))
        subtitle = painter.fontMetrics().elidedText(index.data(Qt.UserRole)["subtitle"], Qt.ElideMiddle, text.width())
        painter.drawText(QRect(text.left(), text.top() + px(23), text.width(), px(18)), Qt.AlignVCenter, subtitle)
        painter.restore()


class _SearchEdit(QLineEdit):
    focused = pyqtSignal()
    navigation = pyqtSignal(int)
    dismissed = pyqtSignal()

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.focused.emit()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.focused.emit()
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.dismissed.emit()
        elif event.key() in (Qt.Key_Up, Qt.Key_Down):
            self.navigation.emit(-1 if event.key() == Qt.Key_Up else 1)
        else:
            # 交给 QLineEdit 原生处理输入法、粘贴和组合字符。
            super().keyPressEvent(event)

    def contextMenuEvent(self, event):
        owner = self.window()
        standard = self.createStandardContextMenu()
        menu = ThemedMenu(owner, light=owner.light, colors=owner.dock.theme_colors())
        menu.addActions(standard.actions())
        owner._editing_menu = True
        try:
            menu.exec_(event.globalPos())
        finally:
            owner._editing_menu = False
            menu.deleteLater()
            standard.deleteLater()
        if not owner.isActiveWindow():
            owner.collapse()


class DockSearch(QWidget):
    """放大镜展开成输入框；结果与输入共用窗口，避免焦点在弹窗间跳转。"""
    def __init__(self, dock):
        super().__init__(dock, Qt.Tool | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.dock = dock
        self.light = dock.is_light()
        self.expanded = False
        self._reveal = 0.0
        self._placing = False
        self._anchor = QRect()
        self._capsule = QRectF()
        self._generation = 0
        self._snapshot = None
        self._worker = None
        self._pending = None
        self._stopping = False
        self._editing_menu = False
        self.setWindowTitle("Window Dock 搜索")
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFont(QFont("Microsoft YaHei UI", 9))
        self.input_clip = QWidget(self)
        self.edit = _SearchEdit(self.input_clip)
        self.edit.setPlaceholderText("搜索")
        self.edit.setAccessibleName("搜索 Dock 中的应用和文件")
        self.edit.setClearButtonEnabled(True)
        self.edit.setFrame(False)
        self.edit.focused.connect(self.expand)
        self.edit.navigation.connect(self._navigate)
        self.edit.dismissed.connect(self.collapse)
        self.edit.textChanged.connect(self._queue)
        self.edit.returnPressed.connect(self._open_current)
        self.input_clip.hide()
        self.edit_opacity = QGraphicsOpacityEffect(self.input_clip)
        self.input_clip.setGraphicsEffect(self.edit_opacity)
        self.button = QToolButton(self)
        self.button.setAccessibleName("搜索 Dock")
        self.button.setToolTip("搜索 Dock 中的应用和文件")
        self.button.setCursor(Qt.PointingHandCursor)
        self.button.clicked.connect(self.expand)
        self.surface = _GlassSurface(self.light, self)
        self.surface_opacity = QGraphicsOpacityEffect(self.surface)
        self.surface.setGraphicsEffect(self.surface_opacity)
        self.surface.setObjectName("glassSurface")
        self.heading = QLabel("搜索 Dock", self.surface)
        self.heading.setProperty("muted", True)
        self.empty = QLabel("输入名称，查找应用和文件", self.surface)
        self.empty.setProperty("muted", True)
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setWordWrap(True)
        self.view = QListView(self.surface)
        self.model = _ResultModel(dock.category_panel.model, self)
        self.view.setModel(self.model)
        self.view.setItemDelegate(_ResultDelegate(self))
        self.view.setUniformItemSizes(True)
        self.view.setMouseTracking(True)
        self.view.setSelectionMode(QAbstractItemView.SingleSelection)
        self.view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.view.setFocusPolicy(Qt.NoFocus)
        self.view.clicked.connect(self._open_index)
        self.surface.hide()
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(90)
        self._debounce.timeout.connect(self._submit)
        self._motion = QVariantAnimation(self)
        self._motion.setEasingCurve(QEasingCurve.InOutCubic)
        self._motion.valueChanged.connect(self._motion_frame)
        self._motion.finished.connect(self._motion_finished)
        # 背景只在收起后或锚点改变时预取一次，点击与动画帧中不抓屏。
        self._backdrop_timer = QTimer(self)
        self._backdrop_timer.setSingleShot(True)
        self._backdrop_timer.setInterval(180)
        self._backdrop_timer.timeout.connect(self._capture_background)
        dock.organizer.changed.connect(self.invalidate)
        QApplication.instance().aboutToQuit.connect(self.shutdown)
        self.update_theme()

    def px(self, value):
        return int(round(value * self.dock.ui_mult))

    def update_theme(self):
        self.light = self.dock.is_light()
        self.surface.light = self.light
        self.setStyleSheet(_stylesheet(self.light) + "QLabel { font-size: %dpx; }" % self.px(12))
        color = "#273244" if self.light else "#f2f4fb"
        self.edit.setStyleSheet("QLineEdit { background: transparent; border: none; color: %s; font-size: %dpx; padding: 0; }" % (color, self.px(13)))
        self.button.setStyleSheet("QToolButton { background: transparent; border: none; border-radius: %dpx; } QToolButton:hover { background: rgba(170,185,219,25); } QToolButton:focus { border: 1px solid #8ba5dd; }" % self.px(20))
        self.surface.update()
        self.update()

    def set_anchor(self, rect):
        changed = rect != self._anchor
        self._anchor = QRect(rect)
        if changed or self.light != self.dock.is_light():
            self.update_theme()
            self._place()
            if not self.expanded:
                self._backdrop_timer.start()

    def _animate_to(self, target):
        start = self._reveal
        self._motion.stop()
        distance = abs(target - start)
        if distance < .001:
            self._reveal = target
            self._motion_finished()
            return
        # Qt 修改时长时会按上一次的 currentTime 重算值；配置期间阻断回调，避免重开回跳。
        self._motion.blockSignals(True)
        self._motion.setDuration(max(80, round((240 if target else 200) * distance)))
        self._motion.setStartValue(start)
        self._motion.setEndValue(float(target))
        self._motion.setCurrentTime(0)
        self._motion.blockSignals(False)
        self._motion.start()

    def _motion_frame(self, value):
        self._reveal = float(value)
        self._place()

    def _motion_finished(self):
        self._reveal = 1.0 if self.expanded else 0.0
        if not self.expanded:
            self.edit.clear()
            self.model.replace([])
            if not self._stopping:
                self._backdrop_timer.start()
            self.dock.apply_layer()
        self._place()

    def _capture_background(self):
        if self.expanded or self._reveal > 0 or not self.isVisible() or self._stopping:
            return
        if not self.dock.cfg.get("glass", True):
            self.surface.snapshot = QPixmap()
            return
        screen = QApplication.screenAt(self._anchor.center()) or QApplication.primaryScreen()
        rect = self._results_rect(self._expanded_anchor(), self.px(48 + 56 * 6))
        origin = rect.topLeft() - screen.geometry().topLeft()
        captured = screen.grabWindow(0, origin.x(), origin.y(), rect.width(), rect.height())
        if not captured.isNull():
            self.surface.snapshot = captured.scaled(max(1, rect.width() // 9), max(1, rect.height() // 9),
                                                    Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            self.surface.snapshot.setDevicePixelRatio(1)
            self.surface.screen_geometry = rect
            self.surface.capture_count += 1

    def expand(self):
        if self._stopping or self._placing:
            return
        if not self.expanded:
            if self.dock.category_panel:
                self.dock.category_panel.hide()
            self.dock._clear_hover()
            self.expanded = True
            self._backdrop_timer.stop()
            self._queue()
            self._animate_to(1.0)
        self.raise_()
        self.activateWindow()
        self.edit.setFocus(Qt.MouseFocusReason)

    def collapse(self, animate=True):
        if not self.expanded and (animate or self._reveal == 0):
            return
        self.expanded = False
        self._cancel()
        self.edit.clearFocus()
        if animate and self.isVisible():
            self._animate_to(0.0)
        else:
            self._motion.stop()
            self._motion_finished()

    def invalidate(self):
        self._snapshot = None
        if self.expanded:
            self._queue()

    def _cancel(self):
        self._generation += 1
        self._debounce.stop()
        self._pending = None
        if self._worker:
            self._worker.requestInterruption()

    def _queue(self, *_):
        self._cancel()
        if not self.expanded:
            return
        self.model.replace([])
        self.view.hide()
        self.empty.show()
        self.heading.setText("搜索 Dock")
        self.empty.setText("正在查找…" if self.edit.text().strip() else "输入名称，查找应用和文件")
        self._place()
        if self.edit.text().strip():
            self._debounce.start()

    def _submit(self):
        if not self.expanded or not self.edit.text().strip():
            return
        if self._snapshot is None:
            self._snapshot = search_snapshot(self.dock.organizer, self.dock.cfg["items"])
        self._pending = (self._generation, self._snapshot, self.edit.text())
        self._start_pending()

    def _start_pending(self):
        if self._worker or self._pending is None or self._stopping:
            return
        task = _SearchTask(*self._pending, self)
        self._pending = None
        self._worker = task
        task.ready.connect(self._accept)
        task.finished.connect(self._finished)
        task.start()

    def _finished(self):
        task = self._worker
        self._worker = None
        if task:
            task.deleteLater()
        self._start_pending()

    def _accept(self, generation, items, count):
        if generation != self._generation or not self.expanded:
            return
        self.model.replace(items)
        self.heading.setText("%d 个结果" % count if count <= 200 else "%d 个结果 · 显示前 200 项，请补充名称" % count)
        self.view.setVisible(bool(items))
        self.empty.setVisible(not items)
        self.empty.setText("没有匹配的项目\n仅搜索 Dock 已收纳的应用和文件")
        if items:
            self.view.setCurrentIndex(self.model.index(0, 0))
        self._place()

    def _navigate(self, delta):
        self.expand()
        if self.model.items:
            row = min(max(0, self.view.currentIndex().row() + delta), len(self.model.items) - 1)
            ix = self.model.index(row, 0)
            self.view.setCurrentIndex(ix)
            self.view.scrollTo(ix)

    def _open_current(self):
        self._open_index(self.view.currentIndex())

    def _open_index(self, index):
        item = index.data(Qt.UserRole)
        if item and self.expanded:
            path = item["path"]
            self.collapse()
            self.dock.launch(path)

    def _expanded_anchor(self):
        anchor = QRect(self._anchor)
        screen = QApplication.screenAt(anchor.center()) or QApplication.primaryScreen()
        area = screen.availableGeometry().adjusted(8, 8, -8, -8)
        anchor.setWidth(self.px(220))
        anchor.moveLeft(max(area.left(), min(anchor.left(), area.right() + 1 - anchor.width())))
        return anchor

    def _results_rect(self, anchor, height):
        screen = QApplication.screenAt(anchor.center()) or QApplication.primaryScreen()
        area = screen.availableGeometry().adjusted(8, 8, -8, -8)
        width = min(self.px(450), area.width())
        edge = self.dock.cfg.get("position", "bottom")
        above_room = anchor.top() - area.top() - self.px(10)
        below_room = area.bottom() - anchor.bottom() - self.px(10)
        above = edge in ("bottom", "custom")
        # 方向用完整面板计算，短结果不会突然换到搜索框另一侧。
        room, other = (above_room, below_room) if above else (below_room, above_room)
        if room < self.px(48 + 56 * 6) and other > room:
            above = not above
        height = min(height, max(1, above_room if above else below_room))
        x = anchor.left()
        y = anchor.top() - height - self.px(10) if above else anchor.bottom() + 1 + self.px(10)
        if edge in ("left", "right"):
            bar = self.dock.window_rect(self.dock.bar_rect_f()).toAlignedRect()
            global_bar = QRect(self.dock.mapToGlobal(bar.topLeft()), bar.size())
            x = global_bar.right() + self.px(14) if edge == "left" else global_bar.left() - width - self.px(14)
        x = max(area.left(), min(x, area.right() + 1 - width))
        y = max(area.top(), min(y, area.bottom() + 1 - height))
        return QRect(x, y, width, height)

    def _place(self):
        if self._anchor.isEmpty():
            return
        self._placing = True
        anchor, full = QRect(self._anchor), self._expanded_anchor()
        shown = self.expanded or self._reveal > 0
        # 收起时也保留同一原生窗口边界。否则 Windows 会先把旧画面随窗口向左搬，
        # 再等 Qt 绘制新坐标，导致放大镜在结果面板左上角闪出一帧。
        # 未绘制区域保持全透明，由分层窗口的 alpha 命中测试让鼠标穿透。
        bounds = anchor.united(full).united(self._results_rect(full, self.px(48 + 56 * 6)))
        results = QRect()
        if shown:
            height = self.px(48 + 56 * min(6, len(self.model.items))) if self.model.items else self.px(144)
            results = self._results_rect(full, height)
        if self.geometry() != bounds:
            self.setGeometry(bounds)
        t = self._reveal
        self._capsule = QRectF(anchor.x() + (full.x() - anchor.x()) * t - bounds.x(),
                               anchor.y() - bounds.y(),
                               anchor.width() + (full.width() - anchor.width()) * t, anchor.height())
        self.button.setGeometry(anchor.translated(-bounds.topLeft()))
        self.button.setVisible(not shown)
        self.input_clip.setVisible(shown)
        self.surface.setVisible(shown)
        self.view.setEnabled(self.expanded)
        if shown:
            inner = self._capsule.adjusted(self.px(38), self.px(3), -self.px(12), -self.px(3)).toAlignedRect()
            inner.setWidth(max(1, inner.width()))
            self.input_clip.setGeometry(inner)
            # 输入控件始终保持最终宽度，裁切容器揭开文字，避免逐帧重新排字和移动光标。
            self.edit.setGeometry(0, 0, full.width() - self.px(50), inner.height())
            self.surface.setGeometry(results.translated(-bounds.topLeft()))
            self.heading.setGeometry(self.px(18), self.px(10), results.width() - self.px(36), self.px(24))
            content = QRect(self.px(9), self.px(38), results.width() - self.px(18), results.height() - self.px(46))
            self.view.setGeometry(content)
            self.empty.setGeometry(content)
        for effect, opacity in ((self.edit_opacity, max(0.0, min(1.0, (t - .22) / .62))),
                                (self.surface_opacity, max(0.0, min(1.0, (t - .42) / .58)))):
            effect.setOpacity(opacity)
            effect.setEnabled(opacity < 1.0)
        self._placing = False
        self.update()

    def event(self, event):
        if (event.type() == QEvent.WindowDeactivate and getattr(self, "expanded", False)
                and not self._placing and not self._editing_menu):
            self.collapse()
        return super().event(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._capsule.contains(QPointF(event.pos())):
            self.expand()
        elif self.expanded and not self.surface.geometry().contains(event.pos()):
            self.collapse()
        super().mousePressEvent(event)

    def hideEvent(self, event):
        self.collapse(animate=False)
        self._backdrop_timer.stop()
        super().hideEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        if not self.expanded:
            self._backdrop_timer.start()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        box = QRectF(self._capsule).adjusted(.7, .7, -.7, -.7)
        path = QPainterPath()
        path.addRoundedRect(box, box.height() / 2, box.height() / 2)
        tint = QColor(240, 242, 251, 195) if self.light else QColor(57, 48, 72, 204)
        p.fillPath(path, tint)
        sheen = QLinearGradient(box.topLeft(), box.bottomLeft())
        sheen.setColorAt(0, QColor(255, 255, 255, 32 if self.light else 24))
        sheen.setColorAt(1, QColor(255, 255, 255, 2))
        p.fillPath(path, sheen)
        p.setBrush(Qt.NoBrush)
        base = (255, 255, 255, 115 if self.light else 52)
        active = (122, 149, 209, 200)
        border = QColor(*(round(a + (b - a) * self._reveal) for a, b in zip(base, active)))
        p.setPen(QPen(border, 1))
        p.drawPath(path)
        p.setPen(QPen(QColor("#566176" if self.light else "#d6d8e5"), self.px(1.5), Qt.SolidLine, Qt.RoundCap))
        center = self._capsule.topLeft() + QPointF((18 + 2 * self._reveal) * self.dock.ui_mult,
                                                  self._capsule.height() / 2 - (2 - self._reveal) * self.dock.ui_mult)
        radius = self.px(5.5)
        p.drawEllipse(center, radius, radius)
        p.drawLine(center + QPoint(radius - 1, radius - 1), center + QPoint(self.px(10), self.px(10)))

    def shutdown(self):
        self._stopping = True
        self._motion.stop()
        self._backdrop_timer.stop()
        self._cancel()
        if self._worker:
            self._worker.quit()
            self._worker.wait()
