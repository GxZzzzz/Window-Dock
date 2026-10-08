# -*- coding: utf-8 -*-
"""Dock 分类面板与文件操作入口；拖放归类不改变原文件。"""

import os
from collections import OrderedDict

from PyQt5.QtCore import (QAbstractListModel, QEasingCurve, QEvent, QFileInfo, QItemSelectionModel, QMimeData, QObject,
                          QPoint, QPropertyAnimation, QRect, QRectF, QSize, Qt, QThread,
                          pyqtSignal, pyqtSlot)
from PyQt5.QtGui import (QColor, QContextMenuEvent, QDrag, QIcon, QImage, QKeySequence, QLinearGradient,
                         QPainter, QPainterPath, QPen, QPixmap)
from PyQt5.QtWidgets import (QAbstractItemView, QActionGroup, QApplication,
                             QFileIconProvider, QFrame, QHBoxLayout, QLabel,
                             QListView, QShortcut, QSizePolicy, QStyle, QStyledItemDelegate,
                             QVBoxLayout, QWidget)

try:
    from organizer import normalize_path
except ImportError:
    def normalize_path(path):
        return os.path.normcase(os.path.abspath(os.fspath(path)))


# 管理窗口独立维护，保留 Dock 已有的导入入口。
from category_manager import CategoryManager


UNCATEGORIZED = "__uncategorized__"
_ENTRY_IMAGE_LOADER = None


def set_entry_image_loader(loader):
    """启动时接入高分辨率系统图标读取器；后台回调只返回 QImage。"""
    global _ENTRY_IMAGE_LOADER
    _ENTRY_IMAGE_LOADER = loader


def _entry_label(item):
    """应用和快捷方式隐藏后缀，普通文件及文件夹保留完整名称。"""
    name = item.get("name") or os.path.basename(item["path"])
    if item.get("kind") == "folders" and not item.get("target"):
        return name
    stem, extension = os.path.splitext(name)
    if extension.casefold() in {".lnk", ".url"} or item.get("kind") == "apps":
        return stem or name
    return name


def _entry_menu_position(anchor, menu_size, available, preferred="right"):
    """以图标的可见轮廓为锚点，点击名称或图标时位置一致；使用逻辑像素。"""
    area = available.adjusted(8, 8, -8, -8)
    width, height = menu_size.width(), menu_size.height()
    right, left = anchor.right() + 8, anchor.left() - width - 8
    above, below = anchor.top() - height - 8, anchor.bottom() + 8
    if preferred in ("above", "below"):
        x = anchor.center().x() - width // 2
        y = above if preferred == "above" else below
        if y < area.top():
            y = below
        if y + height - 1 > area.bottom():
            y = above
    else:
        x = left if preferred == "left" else right
        y = anchor.top() - 8
        if x < area.left():
            x = right
        if x + width - 1 > area.right():
            x = left
    x = max(area.left(), min(x, area.right() - menu_size.width() + 1))
    y = max(area.top(), min(y, area.bottom() - menu_size.height() + 1))
    return QPoint(x, y)


from organizer_artwork import category_pixmap
from menu_ui import ThemedMenu


def _stylesheet(light):
    fg, muted = ("#26303e", "#637083") if light else ("#f0f2f6", "#bdc5d2")
    surface = "rgba(241,245,250,245)" if light else "rgba(35,42,54,246)"
    field = "rgba(255,255,255,145)" if light else "rgba(105,116,134,60)"
    border = "rgba(118,135,157,55)" if light else "rgba(186,198,216,48)"
    return """
        QWidget { color: %s; font-family: 'Microsoft YaHei UI', 'Segoe UI'; font-size: 13px; }
        QDialog#categoryManager { background: %s; border: 1px solid %s; border-radius: 20px; }
        QFrame#glassSurface { background: transparent; border: none; }
        QLabel { background: transparent; }
        QLabel[muted='true'] { color: %s; }
        QPushButton { background: %s; border: 1px solid %s; border-radius: 9px; padding: 8px 13px; }
        QPushButton:hover { background: rgba(141,157,183,45); border-color: rgba(124,145,178,110); }
        QPushButton:pressed { background: rgba(141,157,183,65); }
        QPushButton:disabled { color: %s; }
        QPushButton[primary='true'] { background: #647d9a; color: white; border: 1px solid #647d9a; }
        QPushButton[primary='true']:hover { background: #57708c; }
        QListView, QListWidget { background: transparent; border: none; outline: none; }
        QListWidget::item { padding: 10px; border-radius: 8px; }
        QListWidget::item:selected { background: rgba(124,145,178,42); color: %s; }
        QLineEdit, QComboBox { background: %s; border: 1px solid %s; border-radius: 7px; padding: 7px; min-height: 20px; }
        QComboBox QAbstractItemView { background: %s; selection-background-color: #647d9a; }
        QScrollArea { border: none; background: transparent; }
        QScrollBar:vertical { background: transparent; width: 8px; margin: 2px; }
        QScrollBar::handle:vertical { background: rgba(125,149,183,100); border-radius: 3px; min-height: 30px; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
    """ % (fg, surface, border, muted, field, border, muted, fg, field, border,
           surface)


class _IconWorker(QObject):
    ready = pyqtSignal(str, QIcon)
    imageReady = pyqtSignal(str, QImage)

    def __init__(self):
        super().__init__()
        self.provider = None

    @pyqtSlot(str)
    def fetch(self, path):
        if QThread.currentThread().isInterruptionRequested():
            return
        loader = _ENTRY_IMAGE_LOADER
        if loader is not None:
            try:
                image = loader(path)
                if isinstance(image, QImage) and not image.isNull():
                    self.imageReady.emit(path, image)
                    return
            except Exception:
                # 高分辨率提取失败时仍保留系统图标入口。
                pass
        if self.provider is None:
            self.provider = QFileIconProvider()
        self.ready.emit(path, self.provider.icon(QFileInfo(path)))


class _EntryModel(QAbstractListModel):
    iconRequested = pyqtSignal(str)
    iconReady = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.items = []
        self.row_by_path = {}
        self.manual = set()
        self.icons = OrderedDict()
        self.pending = set()
        self.thread = QThread(self)
        self.worker = _IconWorker()
        self.worker.moveToThread(self.thread)
        self.thread.finished.connect(self.worker.deleteLater)
        self.iconRequested.connect(self.worker.fetch)
        self.worker.ready.connect(self._icon_ready)
        self.worker.imageReady.connect(self._image_ready)
        self.thread.start()
        QApplication.instance().aboutToQuit.connect(self.shutdown)
        self.fallback = QApplication.style().standardIcon(QStyle.SP_FileIcon)

    def shutdown(self):
        if self.thread.isRunning():
            self.thread.requestInterruption()
            self.thread.quit()
            self.thread.wait()

    def replace(self, entries, manual):
        entries, manual = list(entries), set(manual)
        if self.items == entries and self.manual == manual:
            return
        self.beginResetModel()
        self.items = entries
        self.row_by_path = {normalize_path(entry["path"]): row for row, entry in enumerate(self.items)}
        self.manual = manual
        self.endResetModel()

    def request_icon(self, path):
        """面板和 Dock 预览共享队列，返回 None 表示后台仍在获取。"""
        path = normalize_path(path)
        if path in self.icons:
            self.icons.move_to_end(path)
            return self.icons[path]
        if path not in self.pending:
            self.pending.add(path)
            self.iconRequested.emit(path)
        return None

    def rowCount(self, parent=None):
        return len(self.items) if parent is None or not parent.isValid() else 0

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self.items):
            return None
        item = self.items[index.row()]
        path = item["path"]
        if role == Qt.DisplayRole:
            return _entry_label(item)
        if role == Qt.ToolTipRole:
            marker = "手动指定分类\n" if normalize_path(path) in self.manual else ""
            return marker + item.get("name", os.path.basename(path)) + "\n" + path
        if role == Qt.UserRole:
            return item
        if role == Qt.UserRole + 1:
            return normalize_path(path) in self.manual
        if role == Qt.DecorationRole:
            return self.request_icon(path) or self.fallback
        return None

    @pyqtSlot(str, QIcon)
    def _icon_ready(self, path, icon):
        self.pending.discard(path)
        self.icons[path] = icon
        while len(self.icons) > 160:
            self.icons.popitem(last=False)
        row = self.row_by_path.get(path)
        if row is not None:
            ix = self.index(row, 0)
            self.dataChanged.emit(ix, ix, [Qt.DecorationRole])
        self.iconReady.emit(path)

    @pyqtSlot(str, QImage)
    def _image_ready(self, path, image):
        self._icon_ready(path, QIcon(QPixmap.fromImage(image)))

    def flags(self, index):
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled


class _EntryDelegate(QStyledItemDelegate):
    def __init__(self, light=True, parent=None):
        super().__init__(parent)
        self.light = light
        self.list_mode = False
        self.menu_active = False

    def sizeHint(self, option, index):
        if self.list_mode:
            return QSize(120, 36)
        return QSize(116, 126)

    def icon_rect(self, cell):
        if self.list_mode:
            return QRect(cell.left() + 12, cell.center().y() - 11, 22, 22)
        box = cell.adjusted(4, 3, -4, -3)
        return QRect(box.center().x() - 28, box.top() + 6, 56, 56)

    def paint(self, painter, option, index):
        if self.list_mode:
            self._paint_list(painter, option, index)
            return
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        box = option.rect.adjusted(4, 3, -4, -3)
        icon_rect = self.icon_rect(option.rect)
        if (option.state & QStyle.State_Selected
                or (not self.menu_active and option.state & QStyle.State_MouseOver)):
            selected = bool(option.state & QStyle.State_Selected)
            painter.setPen(QPen(QColor(100, 128, 168, 85) if self.light else QColor(215, 225, 245, 75), .8)
                           if selected else Qt.NoPen)
            painter.setBrush(QColor(119, 141, 173, (48 if self.light else 60) if selected else 24))
            # 高亮围绕实际图标居中，名称在框外，不再占满一整格的空白。
            painter.drawRoundedRect(QRectF(icon_rect).adjusted(-6, -6, 6, 6), 12, 12)
        icon = index.data(Qt.DecorationRole)
        if icon:
            icon.paint(painter, icon_rect)
        painter.setPen(QColor("#253041" if self.light else "#f2f4f9"))
        name = str(index.data(Qt.DisplayRole))
        metrics = painter.fontMetrics()
        width = box.width() - 10
        # 最多两行，完整名称和路径留在悬停提示中。
        split = 0
        for i in range(1, len(name) + 1):
            if metrics.horizontalAdvance(name[:i]) > width:
                break
            split = i
        if split == len(name):
            lines = [name]
        else:
            # 括号和空格优先作为换行边界，避免把英文别名拆成零碎尾巴。
            boundary = next((i for i in range(split, 0, -1)
                             if name[i].isspace() or name[i] in "(（[【"), split)
            if boundary >= max(1, split // 2) and metrics.horizontalAdvance(name[boundary:].lstrip()) <= width:
                split = boundary
            lines = [name[:max(split, 1)].rstrip(),
                     metrics.elidedText(name[max(split, 1):].lstrip(), Qt.ElideMiddle, width)]
        for offset, line in enumerate(lines):
            painter.drawText(QRect(box.left() + 5, box.top() + 69 + offset * 17,
                                   width, 18), Qt.AlignHCenter | Qt.AlignTop, line)
        painter.restore()

    def _paint_list(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        box = option.rect.adjusted(2, 2, -2, -2)
        if (option.state & QStyle.State_Selected
                or (not self.menu_active and option.state & QStyle.State_MouseOver)):
            selected = bool(option.state & QStyle.State_Selected)
            painter.setPen(QPen(QColor(100, 128, 168, 85) if self.light else QColor(215, 225, 245, 75), .8)
                           if selected else Qt.NoPen)
            painter.setBrush(QColor(119, 141, 173, (48 if self.light else 60) if selected else 24))
            painter.drawRoundedRect(QRectF(box), 8, 8)
        icon = index.data(Qt.DecorationRole)
        if icon:
            icon.paint(painter, self.icon_rect(option.rect))
        painter.setPen(QColor("#253041" if self.light else "#f2f4f9"))
        text_box = option.rect.adjusted(44, 0, -12, 0)
        name = painter.fontMetrics().elidedText(str(index.data(Qt.DisplayRole)), Qt.ElideMiddle, text_box.width())
        painter.drawText(text_box, Qt.AlignLeft | Qt.AlignVCenter, name)
        painter.restore()


class _EntryView(QListView):
    pathsDropped = pyqtSignal(list)
    itemContextMenuRequested = pyqtSignal(QPoint)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.can_drop = True
        self.setViewMode(QListView.IconMode)
        self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Static)
        self.setGridSize(QSize(116, 126))
        self.setUniformItemSizes(True)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setMouseTracking(True)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.CopyAction)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)

    def set_display_mode(self, list_mode):
        self.setViewMode(QListView.ListMode if list_mode else QListView.IconMode)
        self.setFlow(QListView.TopToBottom if list_mode else QListView.LeftToRight)
        self.setWrapping(not list_mode)
        self.setMovement(QListView.Static)
        self.setGridSize(QSize() if list_mode else QSize(116, 126))

    def contextMenuEvent(self, event):
        if event.reason() == QContextMenuEvent.Keyboard:
            index = self.currentIndex()
            if index.isValid():
                self.scrollTo(index)
                pos = self.visualRect(index).intersected(self.viewport().rect()).center()
            else:
                pos = QPoint(-1, -1)
        else:
            # Windows 弹出窗口的菜单事件可能带着顶层面板坐标；始终从屏幕坐标换算到内容区。
            pos = self.viewport().mapFromGlobal(event.globalPos())
        self.itemContextMenuRequested.emit(pos)
        event.accept()

    def dragEnterEvent(self, event):
        if self.can_drop and event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dropEvent(self, event):
        if self.can_drop and event.mimeData().hasUrls():
            paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
            if paths:
                self.pathsDropped.emit(paths)
                event.setDropAction(Qt.CopyAction)
                event.accept()
                return
        event.ignore()

    def startDrag(self, actions):
        from PyQt5.QtCore import QUrl
        indexes = self.selectedIndexes()
        if not indexes:
            return
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(ix.data(Qt.UserRole)["path"]) for ix in indexes])
        drag = QDrag(self)
        drag.setMimeData(mime)
        icon = indexes[0].data(Qt.DecorationRole)
        if icon:
            drag.setPixmap(icon.pixmap(40, 40))
        # 虚拟分类始终使用 Copy；拖到外部时不得要求移动原文件。
        drag.exec_(Qt.CopyAction, Qt.CopyAction)


class _ElidedLabel(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.full_text = ""
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

    def setText(self, text):
        self.full_text = str(text)
        self.setToolTip(self.full_text)
        self._elide()

    def _elide(self):
        QLabel.setText(self, self.fontMetrics().elidedText(self.full_text, Qt.ElideMiddle, self.width()))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide()


class _GlassSurface(QFrame):
    """打开前捕获一次背景，绘制只取缓存，不在空闲时抓屏。"""
    def __init__(self, light=True, parent=None):
        super().__init__(parent)
        self.light = light
        self.snapshot = QPixmap()
        self.screen_geometry = QRect()
        self.capture_count = 0

    def capture(self, screen):
        captured = screen.grabWindow(0)
        self.screen_geometry = screen.geometry()
        if not captured.isNull():
            # 仅保留约 1/9 尺寸的背景；绘制放大后呈柔和毛玻璃。
            self.snapshot = captured.scaled(max(1, self.screen_geometry.width() // 9),
                                            max(1, self.screen_geometry.height() // 9),
                                            Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            self.snapshot.setDevicePixelRatio(1)
            self.capture_count += 1
        else:
            self.snapshot = QPixmap()
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        rect = QRectF(self.rect()).adjusted(.6, .6, -.6, -.6)
        path = QPainterPath()
        path.addRoundedRect(rect, 22, 22)
        p.setClipPath(path)
        if not self.snapshot.isNull():
            origin = self.mapToGlobal(QPoint(0, 0))
            sx = self.snapshot.width() / self.screen_geometry.width()
            sy = self.snapshot.height() / self.screen_geometry.height()
            source = QRectF((origin.x() - self.screen_geometry.x()) * sx,
                            (origin.y() - self.screen_geometry.y()) * sy,
                            self.width() * sx, self.height() * sy)
            p.drawPixmap(QRectF(self.rect()), self.snapshot, source)
            tint = QColor(247, 250, 255, 161) if self.light else QColor(19, 25, 35, 171)
        else:
            tint = QColor(238, 244, 251, 244) if self.light else QColor(32, 40, 53, 245)
        p.fillPath(path, tint)
        shine = QLinearGradient(0, 0, 0, self.height())
        shine.setColorAt(0, QColor(255, 255, 255, 32 if self.light else 17))
        shine.setColorAt(.45, QColor(255, 255, 255, 3))
        shine.setColorAt(1, QColor(53, 68, 89, 7 if self.light else 14))
        p.fillPath(path, shine)
        p.setClipping(False)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 170 if self.light else 61), 1))
        p.drawRoundedRect(rect, 22, 22)
        p.setPen(QPen(QColor(88, 111, 143, 28 if self.light else 32), .7))
        p.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 21, 21)


class CategoryPanel(QWidget):
    def __init__(self, service, launch_callback, pin_callback, light=True, parent=None, menu_theme=None, file_actions=None):
        # Windows 的原生弹窗阴影按矩形窗口绘制，会露在透明圆角外侧。
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setWindowTitle("Window Dock 分类面板")
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.service = service
        self.launch_callback = launch_callback
        self.pin_callback = pin_callback
        self.file_actions = file_actions
        self.light = light
        self.menu_theme = menu_theme
        self.category_id = None
        self._anchor = QRect()
        self._prefer_above = True
        self._dock_edge = None
        self._appear = QPropertyAnimation(self, b"windowOpacity", self)
        self._appear.setDuration(170)
        self._appear.setEasingCurve(QEasingCurve.OutCubic)
        self.setAcceptDrops(True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.surface = _GlassSurface(light)
        self.surface.setObjectName("glassSurface")
        outer.addWidget(self.surface)
        layout = QVBoxLayout(self.surface)
        layout.setContentsMargins(19, 15, 19, 13)
        layout.setSpacing(9)
        top = QHBoxLayout()
        self.badge = QLabel()
        self.badge.setFixedSize(32, 32)
        top.addWidget(self.badge)
        self.title = _ElidedLabel()
        self.title.setStyleSheet("font-size: 16px; font-weight: 600;")
        top.addWidget(self.title, 1)
        self.count = QLabel()
        self.count.setProperty("muted", True)
        top.addWidget(self.count)
        layout.addLayout(top)
        self.hint = QLabel("拖入应用或文件，手动归类 · 原文件位置不变")
        self.hint.setProperty("muted", True)
        self.hint.setWordWrap(True)
        self.hint.hide()
        self.model = _EntryModel(self)
        self.view = _EntryView()
        self.delegate = _EntryDelegate(light, self.view)
        self.view.setItemDelegate(self.delegate)
        self.view.setModel(self.model)
        self.view.itemContextMenuRequested.connect(self._context_menu)
        self.view.doubleClicked.connect(self._launch_index)
        self.view.pathsDropped.connect(self._assign)
        self._file_shortcuts = []
        if self.file_actions:
            for key, command in ((QKeySequence.Copy, "copy"), (QKeySequence.Cut, "cut"), (QKeySequence.Delete, "delete")):
                shortcut = QShortcut(QKeySequence(key), self.view)
                shortcut.setContext(Qt.WidgetWithChildrenShortcut)
                shortcut.setAutoRepeat(False)
                shortcut.activated.connect(lambda value=command: self._file_command(value))
                self._file_shortcuts.append(shortcut)
        layout.addWidget(self.view, 1)
        self.empty = QLabel("拖入应用或文件，创建你的分类\n也可以在管理分类中添加筛选规则\n原文件位置保持不变")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setProperty("muted", True)
        self.empty.setMinimumHeight(92)
        self.empty.setWordWrap(True)
        layout.addWidget(self.empty)
        self.status = QLabel()
        self.status.setProperty("muted", True)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.status.hide()
        self.view.setToolTip("双击打开，右键查看操作；拖放只改变分类，不移动原文件")
        self.setStyleSheet(_stylesheet(light))
        service.changed.connect(self._changed)
        service.error.connect(self._error)

    def open_category(self, category_id, anchor_rect, prefer_above=True, light=None, dock_edge=None):
        was_visible = self.isVisible()
        self.category_id = category_id
        self._anchor = QRect(anchor_rect)
        self._prefer_above = prefer_above
        self._dock_edge = dock_edge
        if light is not None and light != self.light:
            self.light = light
            self.delegate.light = light
            self.surface.light = light
            self.surface.update()
            self.setStyleSheet(_stylesheet(light))
        self.status.hide()
        if not self._refresh():
            return
        self._place()
        if not was_visible:
            screen = QApplication.screenAt(self._anchor.center()) or QApplication.primaryScreen()
            self.surface.capture(screen)
            self._appear.stop()
            self.setWindowOpacity(0)
        self.show()
        self.raise_()
        self.view.setFocus()
        if not was_visible:
            self._appear.setStartValue(0.0)
            self._appear.setEndValue(1.0)
            self._appear.start()

    def hideEvent(self, event):
        self._appear.stop()
        self.setWindowOpacity(1)
        super().hideEvent(event)

    def _changed(self):
        if self.isVisible():
            if self._refresh():
                self._place()

    def _refresh(self):
        category = next((c for c in self.service.state.get("categories", [])
                         if c["id"] == self.category_id), None)
        if self.category_id == UNCATEGORIZED:
            category = {"id": UNCATEGORIZED, "name": "未分类", "icon": "other"}
        if category is None:
            self.hide()
            return False
        mode_changed = self._apply_view_mode()
        self.title.setText(category["name"])
        self.badge.setPixmap(category_pixmap(category.get("icon", "folders"), 32, self.light))
        entries = self.service.groups().get(self.category_id, [])
        manual = {path for path, cid in self.service.state.get("manual", {}).items()
                  if cid == self.category_id}
        scroll_position = 0 if mode_changed else self.view.verticalScrollBar().value()
        self.model.replace(entries, manual)
        self.view.verticalScrollBar().setValue(scroll_position)
        self.count.setText("%d 项" % len(entries))
        self.view.setVisible(bool(entries))
        self.empty.setVisible(not entries)
        self.view.can_drop = self.category_id != UNCATEGORIZED
        self.hint.setText("这些项目尚未匹配分类，可修改规则或恢复自动分类"
                          if self.category_id == UNCATEGORIZED else
                          "拖入应用或文件，手动归类 · 原文件位置不变")
        self.surface.setToolTip(self.hint.text())
        return True

    def _apply_view_mode(self):
        list_mode = self.service.state.get("view_modes", {}).get(self.category_id, "icons") == "list"
        if self.delegate.list_mode == list_mode:
            return False
        self.delegate.list_mode = list_mode
        self.view.set_display_mode(list_mode)
        return True

    def _set_view_mode(self, mode):
        current = self.view.currentIndex()
        self.service.set_view_mode(self.category_id, mode)
        self._apply_view_mode()
        self._place()
        self.view.doItemsLayout()
        if current.isValid():
            self.view.scrollTo(current, QAbstractItemView.PositionAtCenter)
        self.view.viewport().update()

    def _view_actions(self, menu):
        submenu = menu.addMenu("查看")
        submenu.menuAction().setIcon(menu.glyph("list" if self.delegate.list_mode else "grid"))
        group = QActionGroup(submenu)
        group.setExclusive(True)
        actions = {}
        for name, mode in (("大图标", "icons"), ("列表", "list")):
            action = submenu.addAction(name)
            action.setCheckable(True)
            action.setChecked(self.delegate.list_mode == (mode == "list"))
            group.addAction(action)
            actions[action] = mode
        return actions

    def _new_menu(self):
        colors = self.menu_theme() if self.menu_theme else None
        return ThemedMenu(self, light=colors.get("light", self.light) if colors else self.light, colors=colors)

    def _exec_menu(self, menu, position):
        # 菜单接管鼠标后只保留选中高亮，避免另一项残留的悬停看起来像错选。
        self.delegate.menu_active = True
        QApplication.sendEvent(self.view.viewport(), QEvent(QEvent.Leave))
        self.view.viewport().update()
        try:
            return menu.exec_(position)
        finally:
            self.delegate.menu_active = False
            self.view.viewport().update()

    def _display_menu(self, global_pos):
        menu = self._new_menu()
        actions = self._view_actions(menu)
        screen = QApplication.screenAt(global_pos) or QApplication.primaryScreen()
        menu.ensurePolished()
        chosen = self._exec_menu(menu, _entry_menu_position(QRect(global_pos, QSize(1, 1)), menu.sizeHint(), screen.availableGeometry()))
        menu.deleteLater()
        if chosen in actions:
            self._set_view_mode(actions[chosen])

    def contextMenuEvent(self, event):
        self._display_menu(event.globalPos())

    def _place(self):
        screen = QApplication.screenAt(self._anchor.center()) or QApplication.primaryScreen()
        area = screen.availableGeometry()
        count = len(self.model.items)
        status_height = 35 if not self.status.isHidden() else 0
        if self.delegate.list_mode:
            columns, row_height, base_height = 1, 36, 69
            width = min(480, area.width() - 24)
            capacity = max(1, min(14, (area.height() - 24 - base_height - status_height) // row_height))
        else:
            columns, row_height, base_height = max(1, min(5, count)), 126, 78
            width = min(max(316, 116 * columns + 50) if count else 360, area.width() - 24)
            columns = max(1, min(columns, (width - 38) // 116))
            capacity = max(1, min(4, (area.height() - 24 - base_height - status_height) // row_height))
        # 仅预留标题、边距和列表间隔，不保留工具栏空位。
        rows = max(1, min(capacity, (count + columns - 1) // columns))
        height = base_height + rows * row_height if count else 178
        height += status_height
        height = min(height, area.height() - 24)
        if self._dock_edge in ("left", "right"):
            # 侧边 Dock 向屏幕内部展开；空间不足时换侧，仍以当前屏幕为边界。
            left, right = self._anchor.left() - width - 12, self._anchor.right() + 12
            x = right if self._dock_edge == "left" else left
            if x < area.left() + 8:
                x = right
            if x + width > area.right() - 8:
                x = left
            y = self._anchor.center().y() - height // 2
        else:
            x = self._anchor.center().x() - width // 2
            above, below = self._anchor.top() - height - 12, self._anchor.bottom() + 12
            y = above if self._prefer_above else below
            if y < area.top() + 8:
                y = below
            if y + height > area.bottom() - 8:
                y = above
        x = max(area.left() + 8, min(x, area.right() - width - 8))
        y = max(area.top() + 8, min(y, area.bottom() - height - 8))
        self.setGeometry(x, y, width, height)
        scrollbar = 8 if count > rows * columns else 0
        # 明确预留滚动条，避免滚动条出现后挤掉一列并反复改变布局。
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn if scrollbar else Qt.ScrollBarAlwaysOff)
        padding = (max(0, (width - 38 - scrollbar - min(count, columns) * 116 - 4) // 2)
                   if count and not self.delegate.list_mode else 0)
        self.view.setViewportMargins(padding, 0, padding, 0)

    def _assign(self, paths):
        if self.category_id != UNCATEGORIZED:
            self.service.assign_paths(paths, self.category_id)
            self._set_status("已手动归类，自动整理将保留这个归属")

    def dragEnterEvent(self, event):
        if self.category_id != UNCATEGORIZED and event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        self.dragEnterEvent(event)

    def dropEvent(self, event):
        if self.category_id != UNCATEGORIZED and event.mimeData().hasUrls():
            paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
            if paths:
                self._assign(paths)
                event.setDropAction(Qt.CopyAction)
                event.accept()
                return
        event.ignore()

    def _launch_index(self, index):
        entry = index.data(Qt.UserRole)
        if entry:
            self.hide()
            self.launch_callback(entry["path"])

    def _context_menu(self, pos):
        index = self.view.indexAt(pos) if self.view.viewport().rect().contains(pos) else self.model.index(-1, 0)
        if not index.isValid():
            self._display_menu(self.view.viewport().mapToGlobal(pos))
            return
        selection = self.view.selectionModel()
        # 已选中的多项继续批量操作；点到新项目时明确切换，菜单不沿用旧的当前项。
        command = QItemSelectionModel.NoUpdate if selection.isSelected(index) else QItemSelectionModel.ClearAndSelect
        selection.setCurrentIndex(index, command)
        selected = self.view.selectedIndexes()
        paths = [ix.data(Qt.UserRole)["path"] for ix in selected]
        menu = self._new_menu()
        open_action = menu.addAction(menu.glyph("open"), "打开")
        pin_action = menu.addAction(menu.glyph("pin"), "固定至 Dock")
        menu.addSeparator()
        file_commands = self.file_actions.add_menu(menu, paths) if self.file_actions else {}
        if file_commands:
            menu.addSeparator()
        move_menu = menu.addMenu("手动归入分类")
        move_menu.menuAction().setIcon(menu.glyph("categories"))
        actions = {}
        for category in self.service.state.get("categories", []):
            action = move_menu.addAction(QIcon(category_pixmap(category.get("icon", "folders"), 22)), category["name"])
            action.setEnabled(category["id"] != self.category_id)
            actions[action] = category["id"]
        auto_action = menu.addAction(menu.glyph("automatic"), "恢复自动分类")
        auto_action.setEnabled(any(normalize_path(path) in self.service.state.get("manual", {}) for path in paths))
        exclude_action = menu.addAction(menu.glyph("remove"), "从分类中移除")
        exclude_action.setToolTip("仅移除分类入口，保留原文件和位置")
        menu.setToolTipsVisible(True)
        menu.addSeparator()
        view_actions = self._view_actions(menu)
        cell = self.view.visualRect(index)
        local = cell if self.delegate.list_mode else self.delegate.icon_rect(cell).adjusted(-6, -6, 6, 6)
        local = local.intersected(self.view.viewport().rect())
        if local.isEmpty():
            local = self.view.visualRect(index).intersected(self.view.viewport().rect())
        anchor = QRect(self.view.viewport().mapToGlobal(local.topLeft()), local.size())
        screen = QApplication.screenAt(anchor.center()) or QApplication.primaryScreen()
        menu.ensurePolished()
        action = self._exec_menu(menu, _entry_menu_position(anchor, menu.sizeHint(), screen.availableGeometry()))
        menu.deleteLater()
        if action == open_action:
            self.hide()
            for path in paths:
                self.launch_callback(path)
        elif action == pin_action:
            for path in paths:
                self.pin_callback(path)
        elif action in file_commands:
            self._file_command(file_commands[action], paths)
        elif action == auto_action:
            self.service.restore_auto(paths)
        elif action == exclude_action:
            self.service.exclude_paths(paths)
        elif action in actions:
            self.service.assign_paths(paths, actions[action])
        elif action in view_actions:
            self._set_view_mode(view_actions[action])

    def _file_command(self, command, paths=None):
        if self.file_actions is None:
            return
        if paths is None:
            paths = [ix.data(Qt.UserRole)["path"] for ix in self.view.selectedIndexes()]
        if not paths:
            return
        if command == "delete":
            self.hide()
        self.file_actions.perform(command, paths)

    def _error(self, message):
        self._set_status(message)

    def _set_status(self, message):
        self.status.setText(message)
        self.status.setVisible(bool(message))
        if self.isVisible():
            self._place()
