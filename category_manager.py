"""分类管理窗口：统一玻璃主题，编辑草稿在保存时一次提交。"""

import copy
import uuid

from PyQt5.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, pyqtSignal
from PyQt5.QtGui import (QColor, QFont, QIcon, QKeySequence, QLinearGradient,
                         QPainter, QPainterPath, QPen, QPixmap)
from PyQt5.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox,
                             QDialog, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
                             QLabel, QLayout, QLineEdit, QListWidget, QListWidgetItem,
                             QPushButton, QScrollArea, QShortcut, QSizeGrip,
                             QSizePolicy, QSplitter, QStackedWidget, QStyle,
                             QStyledItemDelegate, QToolButton, QVBoxLayout, QWidget)

from menu_ui import ThemedMenu
from organizer import separator_positions
from organizer_artwork import category_pixmap
from icon_theme import icon_choices


KINDS = [("apps", "应用与快捷方式"), ("documents", "文档"), ("images", "图片"),
         ("folders", "文件夹"), ("archives", "压缩包"), ("media", "音频与视频"),
         ("other", "其他文件")]
ICONS = [("ide", "IDE 开发"), ("office", "办公沟通"), ("industrial", "工控调试"),
         ("entertainment", "娱乐影音"), ("utilities", "系统工具")] + KINDS + [
         ("work", "工作"), ("code", "开发"), ("star", "收藏")]
ICONS += [(key, name) for key, name in icon_choices() if key not in dict(ICONS)]
FIELDS = [("kind", "文件类型"), ("extension", "扩展名"), ("name", "名称包含"),
          ("path", "路径包含"), ("exact", "指定文件或应用")]


def _artwork(key, size, light):
    # 管理窗口按 2x 准备静态图标；复制包装后设置 DPR，避免修改共用缓存。
    image = QPixmap(category_pixmap(key, size * 2, light))
    image.setDevicePixelRatio(2)
    return image


def _style(light):
    fg, muted = ("#292738", "#716d81") if light else ("#f2effa", "#aaa4bb")
    edge = "rgba(87,72,116,26)" if light else "rgba(215,202,245,28)"
    card = "rgba(255,255,255,150)" if light else "rgba(255,255,255,8)"
    field = "rgba(255,255,255,178)" if light else "rgba(12,9,22,76)"
    hover = "rgba(112,94,186,24)" if light else "rgba(182,163,236,25)"
    accent = "#7261d2" if light else "#b4a8ff"
    return """
        QWidget { color: %(fg)s; font-family: 'Microsoft YaHei UI', 'Segoe UI'; font-size: 13px; }
        QDialog, QWidget#editorForm, QWidget#rulesBody { background: transparent; }
        QLabel { background: transparent; border: none; }
        QLabel[muted="true"] { color: %(muted)s; }
        QLabel#windowTitle { font-size: 23px; font-weight: 600; }
        QLabel#sectionTitle { font-size: 15px; font-weight: 600; }
        QLabel#eyebrow { color: %(muted)s; font-size: 11px; }
        QLabel#badge { background: %(hover)s; color: %(accent)s; border-radius: 9px; padding: 4px 9px; font-size: 11px; }
        QFrame#sidebar, QFrame#card, QFrame#emptyCard {
            background: %(card)s; border: 1px solid %(edge)s; border-radius: 18px;
        }
        QFrame#ruleRow { background: %(field)s; border: 1px solid %(edge)s; border-radius: 12px; }
        QPushButton, QToolButton {
            background: %(card)s; border: 1px solid %(edge)s; border-radius: 10px;
            padding: 8px 12px; min-height: 20px;
        }
        QPushButton:hover, QToolButton:hover { background: %(hover)s; border-color: rgba(139,119,211,90); }
        QPushButton:pressed, QToolButton:pressed { background: rgba(133,111,209,40); }
        QPushButton:focus, QToolButton:focus { border-color: #a598e9; }
        QPushButton:disabled { color: %(muted)s; background: transparent; }
        QPushButton[primary="true"] { background: #7866d8; color: white; border: 1px solid #9786ee; font-weight: 600; }
        QPushButton[primary="true"]:hover { background: #8876e6; }
        QPushButton[quiet="true"] { background: transparent; border: 1px solid transparent; color: %(muted)s; }
        QPushButton[quiet="true"]:hover { background: %(hover)s; color: %(fg)s; }
        QPushButton[danger="true"]:hover { color: #ed8397; background: rgba(219,91,122,18); }
        QPushButton#iconButton { padding: 3px; border-radius: 17px; background: transparent; }
        QPushButton#closeButton { padding: 0; border-radius: 11px; font-size: 19px; }
        QToolButton#iconTile { padding: 3px; border-radius: 12px; font-size: 11px; background: transparent; border: 1px solid transparent; }
        QToolButton#iconTile:checked { background: %(hover)s; border: 1px solid #aa9aee; }
        QLineEdit, QComboBox {
            background: %(field)s; border: 1px solid %(edge)s; border-radius: 9px;
            padding: 7px 10px; min-height: 20px; selection-background-color: #7866d8; selection-color: white;
        }
        QLineEdit:focus, QComboBox:focus { border-color: #a494eb; }
        QLineEdit#categoryName { font-size: 19px; font-weight: 600; padding: 6px 10px; }
        QComboBox { padding-right: 27px; }
        QComboBox::drop-down { border: none; width: 25px; background: transparent; }
        QComboBox::down-arrow { image: none; }
        QListWidget { background: transparent; border: none; outline: none; }
        QListWidget::item { padding: 0; border: none; }
        QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; border: none; }
        QScrollBar:vertical { background: transparent; width: 7px; margin: 4px 0; }
        QScrollBar::handle:vertical { background: rgba(149,136,179,85); border-radius: 3px; min-height: 28px; }
        QScrollBar::handle:vertical:hover { background: rgba(149,136,179,150); }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
        QSplitter::handle { background: transparent; width: 12px; }
        QCheckBox { spacing: 9px; background: transparent; padding: 4px 0; }
        QCheckBox::indicator { width: 16px; height: 16px; }
        QSizeGrip { background: transparent; width: 14px; height: 14px; }
    """ % dict(fg=fg, muted=muted, edge=edge, card=card, field=field, hover=hover, accent=accent)


def _label(text, *, muted=False, name=None, wrap=False):
    label = QLabel(text)
    label.setProperty("muted", muted)
    if name:
        label.setObjectName(name)
    label.setWordWrap(wrap)
    return label


def _button(text, callback, *, quiet=False, primary=False):
    button = QPushButton(text)
    button.setAutoDefault(False)
    button.setProperty("quiet", quiet)
    button.setProperty("primary", primary)
    button.setCursor(Qt.PointingHandCursor)
    button.clicked.connect(callback)
    return button


class _GlassDialog(QDialog):
    """只有打开时取一次低分辨率背景；移动和重绘都复用缓存。"""
    def __init__(self, parent=None, light=True, popup=False):
        flags = (Qt.Popup if popup else Qt.Dialog) | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint
        super().__init__(parent, flags)
        self.light = light
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAutoFillBackground(False)
        self.snapshot = QPixmap()
        self.screen_geometry = QRect()
        self.capture_count = 0
        self.setStyleSheet(_style(light))

    def capture_background(self, screen):
        if QApplication.platformName() == "offscreen":
            return
        captured = screen.grabWindow(0)
        self.screen_geometry = screen.geometry()
        if not captured.isNull():
            self.snapshot = captured.scaled(max(1, self.screen_geometry.width() // 12),
                                            max(1, self.screen_geometry.height() // 12),
                                            Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            self.snapshot.setDevicePixelRatio(1)
            self.capture_count += 1

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.setCompositionMode(QPainter.CompositionMode_Source)
        p.fillRect(self.rect(), Qt.transparent)
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        rect = QRectF(self.rect()).adjusted(.6, .6, -.6, -.6)
        shape = QPainterPath()
        shape.addRoundedRect(rect, 24, 24)
        p.setClipPath(shape)
        if not self.snapshot.isNull():
            origin = self.mapToGlobal(QPoint())
            sx = self.snapshot.width() / self.screen_geometry.width()
            sy = self.snapshot.height() / self.screen_geometry.height()
            source = QRectF((origin.x() - self.screen_geometry.x()) * sx,
                            (origin.y() - self.screen_geometry.y()) * sy,
                            self.width() * sx, self.height() * sy)
            p.drawPixmap(QRectF(self.rect()), self.snapshot, source)
        base = QColor(244, 242, 251, 239) if self.light else QColor(29, 25, 41, 242)
        if self.snapshot.isNull():
            base.setAlpha(252)
        p.fillPath(shape, base)
        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0, QColor(255, 255, 255, 32 if self.light else 14))
        gradient.setColorAt(.5, QColor(133, 111, 203, 4))
        gradient.setColorAt(1, QColor(102, 124, 197, 15))
        p.fillPath(shape, gradient)
        p.setClipping(False)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 195 if self.light else 52), 1))
        p.drawPath(shape)
        p.end()


class _TitleBar(QFrame):
    def __init__(self, parent):
        super().__init__(parent)
        self._drag = None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag = event.globalPos() - self.window().pos()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag is not None and event.buttons() & Qt.LeftButton:
            self.window().move(event.globalPos() - self._drag)
            self.window().update()

    def mouseReleaseEvent(self, event):
        self._drag = None


class _Choice(QComboBox):
    """下拉选项复用 Dock 菜单，避免系统白底弹窗打断深色主题。"""
    def __init__(self, light, parent=None):
        super().__init__(parent)
        self.light = light

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor("#7b728c" if self.light else "#beb4d6"), 1.4,
                      Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        x, y = self.width() - 16, self.height() / 2
        p.drawLine(QPointF(x - 3, y - 1.5), QPointF(x, y + 1.5))
        p.drawLine(QPointF(x, y + 1.5), QPointF(x + 3, y - 1.5))

    def showPopup(self):
        menu = ThemedMenu(self, light=self.light)
        menu.setMinimumWidth(self.width())
        for i in range(self.count()):
            action = menu.addAction(self.itemIcon(i), self.itemText(i))
            action.setData(i)
            action.setCheckable(True)
            action.setChecked(i == self.currentIndex())
            if i == self.currentIndex():
                menu.setActiveAction(action)
        menu.ensurePolished()
        area = (QApplication.screenAt(self.mapToGlobal(QPoint())) or QApplication.primaryScreen()).availableGeometry()
        point = self.mapToGlobal(QPoint(0, self.height() + 5))
        hint = menu.sizeHint()
        if point.y() + hint.height() > area.bottom():
            point.setY(self.mapToGlobal(QPoint()).y() - hint.height() - 5)
        point.setX(max(area.left() + 5, min(point.x(), area.right() - hint.width() - 5)))
        point.setY(max(area.top() + 5, point.y()))
        action = menu.exec_(point)
        if action is not None:
            self.setCurrentIndex(action.data())
        menu.deleteLater()
        self.hidePopup()
        self.update()


class _Toggle(QCheckBox):
    """沿用复选框的键盘与辅助功能，只统一开关的绘制。"""
    def __init__(self, text, light, parent=None):
        super().__init__(text, parent)
        self.light = light
        self.setCursor(Qt.PointingHandCursor)

    def sizeHint(self):
        return QSize(self.fontMetrics().horizontalAdvance(self.text()) + 50, 32)

    def minimumSizeHint(self):
        return self.sizeHint()

    def hitButton(self, pos):
        return self.rect().contains(pos)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        y = (self.height() - 20) / 2
        p.setPen(QPen(QColor("#a798e5" if self.hasFocus() else "#9386aa"), 1))
        p.setBrush(QColor("#8975dc" if self.isChecked() else ("#ded9e9" if self.light else "#464051")))
        p.drawRoundedRect(QRectF(1, y, 35, 20), 10, 10)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#ffffff" if self.isChecked() else ("#faf9ff" if self.light else "#c4bdcf")))
        p.drawEllipse(QRectF(19 if self.isChecked() else 4, y + 3, 14, 14))
        p.setPen(QColor("#393145" if self.light else "#e9e3f4"))
        p.drawText(QRectF(47, 0, self.width() - 47, self.height()), Qt.AlignVCenter, self.text())


class _CategoryDelegate(QStyledItemDelegate):
    def __init__(self, light, parent=None):
        super().__init__(parent)
        self.light = light

    def sizeHint(self, option, index):
        return QSize(220, 42 if index.data(Qt.UserRole) == "__separator__" else 70)

    def paint(self, p, option, index):
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(option.rect).adjusted(2, 2, -2, -2)
        selected = bool(option.state & QStyle.State_Selected)
        if selected or option.state & QStyle.State_MouseOver:
            p.setPen(QPen(QColor(137, 118, 203, 53 if selected else 0), 1))
            p.setBrush(QColor(123, 103, 202, 24 if self.light else 40) if selected
                       else QColor(148, 128, 207, 13))
            p.drawRoundedRect(rect, 12, 12)
        fg = QColor("#322c43" if self.light else "#f0ebfa")
        muted = QColor("#8a8299" if self.light else "#a29aae")
        if index.data(Qt.UserRole) == "__separator__":
            p.setPen(QPen(QColor(144, 132, 169, 75), 1))
            cy = rect.center().y()
            p.drawLine(QPointF(rect.left() + 16, cy), QPointF(rect.center().x() - 28, cy))
            p.drawLine(QPointF(rect.center().x() + 28, cy), QPointF(rect.right() - 16, cy))
            p.setPen(muted)
            font = QFont(option.font);font.setPixelSize(11);p.setFont(font)
            p.drawText(rect, Qt.AlignCenter, "分隔符")
        else:
            if selected:
                p.setPen(Qt.NoPen);p.setBrush(QColor("#a494eb"))
                p.drawRoundedRect(QRectF(rect.left() + 4, rect.center().y() - 12, 3, 24), 1.5, 1.5)
            icon_rect = QRect(int(rect.left() + 13), int(rect.center().y() - 20), 40, 40)
            icon = index.data(Qt.DecorationRole)
            if icon:
                icon.paint(p, icon_rect)
            text_rect = QRectF(rect.left() + 64, rect.top() + 11, rect.width() - 97, 23)
            font = QFont(option.font);font.setPixelSize(13);font.setWeight(QFont.DemiBold);p.setFont(font)
            p.setPen(fg)
            p.drawText(text_rect, Qt.AlignVCenter, p.fontMetrics().elidedText(index.data() or "", Qt.ElideRight, int(text_rect.width())))
            font.setPixelSize(11);font.setWeight(QFont.Normal);p.setFont(font);p.setPen(muted)
            p.drawText(text_rect.translated(0, 22), Qt.AlignVCenter, index.data(Qt.UserRole + 1) or "")
            p.drawText(QRectF(rect.right() - 31, rect.top(), 24, rect.height()), Qt.AlignCenter,
                       str(index.data(Qt.UserRole + 2) or "").zfill(2))
        p.restore()


class _IconPicker(_GlassDialog):
    selected = pyqtSignal(str)

    def __init__(self, parent, light, selected):
        super().__init__(parent, light, popup=True)
        self.setWindowTitle("选择分类图标")
        layout = QVBoxLayout(self);layout.setContentsMargins(16, 16, 16, 16);layout.setSpacing(12)
        top = QHBoxLayout();top.addWidget(_label("选择分类图标", name="sectionTitle"));top.addStretch()
        close = _button("×", self.close, quiet=True);close.setObjectName("closeButton");close.setFixedSize(28, 28)
        top.addWidget(close);layout.addLayout(top)
        canonical = {"work": "office", "code": "ide"}.get(selected, selected)
        choices = [(k, n) for k, n in ICONS if k not in {"work", "code"}]
        layout.addWidget(_label("%d 个图标 · 滚动查看更多" % len(choices), muted=True, name="eyebrow"))
        self.scroll = QScrollArea();self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget();grid = QGridLayout(body)
        grid.setContentsMargins(0, 0, 10, 0);grid.setSpacing(5)
        grid.setSizeConstraint(QLayout.SetFixedSize)
        grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self._selected_tile = None
        for i, (key, label) in enumerate(choices):
            button = QToolButton();button.setObjectName("iconTile")
            button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            button.setIcon(QIcon(_artwork(key, 48, light)));button.setIconSize(QSize(48, 48))
            button.setText({"apps": "应用", "media": "影音"}.get(key, label))
            button.setToolTip(label);button.setFixedSize(80, 78)
            button.setCheckable(True);button.setChecked(key == canonical)
            if key == canonical:
                self._selected_tile = button
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda _=False, k=key: self._choose(k))
            grid.addWidget(button, i // 5, i % 5)
        self.scroll.setWidget(body);layout.addWidget(self.scroll)
        area = (parent.screen() or QApplication.primaryScreen()).availableGeometry()
        self.setFixedSize(480, min(600, area.height() - 32))
        self.snapshot = parent.snapshot
        self.screen_geometry = parent.screen_geometry

    def showEvent(self, event):
        super().showEvent(event)
        if self._selected_tile is not None:
            self.scroll.ensureWidgetVisible(self._selected_tile)

    def _choose(self, key):
        self.selected.emit(key)
        self.close()

    def hideEvent(self, event):
        super().hideEvent(event)
        # 点击外部关闭 Popup 时也释放控件，重复选图不会累积隐藏窗口。
        self.deleteLater()


class _RuleRow(QFrame):
    removed = pyqtSignal(object)
    changed = pyqtSignal()

    def __init__(self, rule=None, parent=None, light=True):
        super().__init__(parent)
        self.setObjectName("ruleRow")
        self.setMinimumHeight(104)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        rule = rule or {"field": "kind", "value": "documents"}
        layout = QVBoxLayout(self);layout.setContentsMargins(12, 10, 12, 12);layout.setSpacing(8)
        top = QHBoxLayout();top.setSpacing(8)
        self.number = _label("", muted=True, name="eyebrow");top.addWidget(self.number)
        self.field = _Choice(light)
        for key, label in FIELDS:
            self.field.addItem(label, key)
        self.field.setMinimumWidth(154);top.addWidget(self.field);top.addStretch()
        remove = _button("×", lambda: self.removed.emit(self), quiet=True)
        remove.setProperty("danger", True);remove.setFixedSize(30, 30);remove.setToolTip("移除这条规则")
        remove.setAccessibleName("移除规则");top.addWidget(remove)
        layout.addLayout(top)
        bottom = QHBoxLayout();bottom.setSpacing(8)
        self.text = QLineEdit();self.text.setMinimumWidth(80);self.text.setAccessibleName("规则内容")
        self.kind = _Choice(light)
        for key, label in KINDS:
            self.kind.addItem(label, key)
        bottom.addWidget(self.text, 1);bottom.addWidget(self.kind, 1)
        self.browse = _button("选择文件…", self._choose);bottom.addWidget(self.browse)
        layout.addLayout(bottom)
        self.field.setCurrentIndex(max(0, self.field.findData(rule.get("field", "kind"))))
        self.text.setText(str(rule.get("value", "")))
        ki = self.kind.findData(rule.get("value", "documents"))
        if ki < 0:
            self.kind.addItem("多个类型：" + str(rule.get("value", "")), rule.get("value", ""))
            ki = self.kind.count() - 1
        self.kind.setCurrentIndex(ki)
        self.field.currentIndexChanged.connect(self._field_changed)
        self.text.textChanged.connect(self.changed)
        self.kind.currentIndexChanged.connect(self.changed)
        self._field_changed()

    def _field_changed(self):
        field = self.field.currentData()
        self.kind.setVisible(field == "kind");self.text.setVisible(field != "kind")
        self.browse.setVisible(field == "exact")
        hints = {"extension": "例如：pdf, docx, xlsx",
                 "name": "例如：项目, 合同, Visual Studio",
                 "path": "例如：工作资料, 项目",
                 "exact": "选择文件或应用，或填写完整路径"}
        self.text.setPlaceholderText(hints.get(field, ""))
        self.changed.emit()

    def _choose(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "选择要匹配的文件或应用")
        if paths:
            self.text.setText(", ".join(paths))

    def value(self):
        field = self.field.currentData()
        return {"field": field, "value": self.kind.currentData() if field == "kind" else self.text.text().strip()}


class _SeparatorPreview(QWidget):
    def __init__(self, light, parent=None):
        super().__init__(parent)
        self.light = light;self.split = True
        self.images = [_artwork(key, 48, light) for key in ("apps", "documents", "images", "folders")]
        self.setMinimumHeight(104)

    def paintEvent(self, event):
        p = QPainter(self);p.setRenderHint(QPainter.Antialiasing)
        x, y = (self.width() - 302) / 2, (self.height() - 76) / 2
        p.setPen(QPen(QColor(153, 138, 187, 70), 1))
        p.setBrush(QColor(255, 255, 255, 100 if self.light else 15))
        if self.split:
            for offset in (0, 166):
                p.drawRoundedRect(QRectF(x + offset, y, 136, 76), 18, 18)
        else:
            p.drawRoundedRect(QRectF(x, y, 302, 76), 18, 18)
        p.setPen(QPen(QColor(153, 138, 187, 130), 2.5, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(x + 151, y + 25), QPointF(x + 151, y + 51))
        for image, offset in zip(self.images, (12, 76, 178, 242)):
            p.drawPixmap(int(x + offset), int(y + 14), image)


class CategoryManager(_GlassDialog):
    """分类、规则和分隔符只修改草稿；关闭或取消不会提交。"""
    def __init__(self, service, light=True, parent=None, dock_config=None):
        super().__init__(parent, light)
        self.setObjectName("categoryManager");self.setWindowTitle("分类管理 · Window Dock")
        self.service = service;self.dock_config = dock_config
        self.categories = copy.deepcopy(service.state.get("categories", []))
        self.separators = separator_positions(service.state)
        self.current_id = None;self.rule_rows = [];self._loading = True;self._picker = None
        outer = QVBoxLayout(self);outer.setContentsMargins(22, 16, 22, 16);outer.setSpacing(16)
        titlebar = _TitleBar(self);header = QHBoxLayout(titlebar);header.setContentsMargins(2, 0, 0, 0)
        heading = QVBoxLayout();heading.setSpacing(4)
        for text, name, muted in [("WINDOW DOCK", "eyebrow", True), ("分类管理", "windowTitle", False)]:
            label = _label(text, muted=muted, name=name)
            label.setAttribute(Qt.WA_TransparentForMouseEvents);heading.addWidget(label)
        header.addLayout(heading);header.addStretch()
        header.addWidget(_label("按你的习惯，整理桌面", muted=True))
        close = _button("×", self.reject, quiet=True);close.setObjectName("closeButton")
        close.setFixedSize(34, 34);close.setToolTip("关闭，不保存更改");close.setAccessibleName("关闭分类管理")
        header.addSpacing(12);header.addWidget(close, 0, Qt.AlignTop);outer.addWidget(titlebar)

        split = QSplitter(Qt.Horizontal);split.setChildrenCollapsible(False);split.setHandleWidth(14)
        sidebar = QFrame();sidebar.setObjectName("sidebar");sidebar.setMinimumWidth(226)
        side = QVBoxLayout(sidebar);side.setContentsMargins(10, 17, 10, 12);side.setSpacing(8)
        side_header = QHBoxLayout();side_header.setContentsMargins(9, 0, 9, 0)
        side_header.addWidget(_label("分类与顺序", name="sectionTitle"));side_header.addStretch()
        self.category_count = _label("", name="badge");side_header.addWidget(self.category_count)
        side.addLayout(side_header)
        hint = _label("拖动排序，靠前的分类优先匹配", muted=True);hint.setContentsMargins(9, 0, 0, 5);side.addWidget(hint)
        self.list = QListWidget();self.list.setMouseTracking(True)
        self.list.setItemDelegate(_CategoryDelegate(light, self.list))
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setDragDropMode(QAbstractItemView.InternalMove);self.list.setDefaultDropAction(Qt.MoveAction)
        self.list.setDropIndicatorShown(True);self.list.currentItemChanged.connect(self._switch)
        self.list.model().rowsMoved.connect(self._order_changed);side.addWidget(self.list, 1)
        side.addWidget(_button("＋  新建分类", self._add))
        actions = QHBoxLayout();actions.setSpacing(4)
        self.add_separator_button = _button("添加分隔符", self._add_separator, quiet=True)
        actions.addWidget(self.add_separator_button, 1)
        self.delete_button = _button("删除", self._delete, quiet=True);self.delete_button.setProperty("danger", True)
        actions.addWidget(self.delete_button);side.addLayout(actions);split.addWidget(sidebar)

        self.editor_stack = QStackedWidget();split.addWidget(self.editor_stack);split.setSizes([252, 668])
        self.editor_stack.setMinimumWidth(390)
        self.form = QWidget();self.form.setObjectName("editorForm")
        form = QVBoxLayout(self.form);form.setContentsMargins(0, 0, 8, 0);form.setSpacing(14)
        form.setSizeConstraint(QLayout.SetMinAndMaxSize)
        identity = QFrame();identity.setObjectName("card")
        identity_layout = QHBoxLayout(identity);identity_layout.setContentsMargins(18, 18, 18, 18);identity_layout.setSpacing(16)
        self.icon_button = _button("", self._pick_icon);self.icon_button.setObjectName("iconButton")
        self.icon_button.setFixedSize(76, 76);self.icon_button.setIconSize(QSize(68, 68))
        self.icon_button.setToolTip("选择分类图标");self.icon_button.setAccessibleName("选择分类图标")
        identity_layout.addWidget(self.icon_button)
        details = QVBoxLayout();details.setSpacing(6)
        details.addWidget(_label("分类名称", muted=True, name="eyebrow"))
        self.name = QLineEdit();self.name.setObjectName("categoryName")
        self.name.setPlaceholderText("给这个分类起个名字");self.name.textChanged.connect(self._name_changed)
        self.name.setAccessibleName("分类名称");details.addWidget(self.name)
        self.icon_hint = _label("点击左侧图标更换封面", muted=True, name="eyebrow");details.addWidget(self.icon_hint)
        identity_layout.addLayout(details, 1);form.addWidget(identity)
        # 保留组合框的数据接口，实际选择通过图标网格完成。
        self.icon = QComboBox(self);self.icon.hide()
        for key, label in ICONS:
            self.icon.addItem(label, key)
        self.icon.currentIndexChanged.connect(self._icon_changed)

        rule_card = QFrame();rule_card.setObjectName("card")
        rule_layout = QVBoxLayout(rule_card);rule_layout.setContentsMargins(18, 18, 18, 18);rule_layout.setSpacing(13)
        rule_heading = QHBoxLayout();rule_heading.addWidget(_label("自动分类规则", name="sectionTitle"));rule_heading.addStretch()
        self.rule_count = _label("", name="badge");rule_heading.addWidget(self.rule_count);rule_layout.addLayout(rule_heading)
        mode_line = QHBoxLayout();mode_line.addWidget(_label("将项目归入此分类，当", muted=True));mode_line.addStretch()
        self.mode = _Choice(light);self.mode.addItem("满足任意一条", "any");self.mode.addItem("满足全部条件", "all")
        self.mode.currentIndexChanged.connect(self._mark_dirty);mode_line.addWidget(self.mode);rule_layout.addLayout(mode_line)
        self.rules_widget = QWidget();self.rules_widget.setObjectName("rulesBody")
        self.rules_layout = QVBoxLayout(self.rules_widget);self.rules_layout.setContentsMargins(0, 0, 0, 0)
        self.rules_layout.setSpacing(10)
        self.rules_layout.setSizeConstraint(QLayout.SetMinAndMaxSize)
        self.rule_empty = _label("暂不自动收纳\n可以直接拖入应用和文件，或添加规则自动整理。", muted=True, wrap=True)
        self.rule_empty.setAlignment(Qt.AlignCenter);self.rule_empty.setMinimumHeight(92)
        rule_layout.addWidget(self.rule_empty);rule_layout.addWidget(self.rules_widget)
        self.add_rule_button = _button("＋  添加规则", lambda: self._append_rule())
        rule_layout.addWidget(self.add_rule_button)
        rule_layout.addWidget(_label("多个关键词或扩展名用逗号分隔，同一条规则匹配任意一个值。", muted=True, wrap=True))
        form.addWidget(rule_card)
        notice = _label("手动拖入的项目会优先留在你指定的分类。\n自动整理不移动原文件，也不会覆盖手动归属。", muted=True, wrap=True)
        notice.setContentsMargins(8, 2, 8, 6);form.addWidget(notice);form.addStretch()
        self.editor_scroll = QScrollArea();self.editor_scroll.setWidgetResizable(True)
        self.editor_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.editor_scroll.setWidget(self.form);self.editor_stack.addWidget(self.editor_scroll)

        separator_page = QFrame();separator_page.setObjectName("card")
        separator_layout = QVBoxLayout(separator_page);separator_layout.setContentsMargins(28, 24, 28, 24)
        separator_layout.addWidget(_label("分隔符", name="sectionTitle"))
        separator_layout.addWidget(_label("让 Dock 的分区更清楚", muted=True))
        self.separator_preview = _SeparatorPreview(light);separator_layout.addWidget(self.separator_preview)
        separator_layout.addWidget(_label("拖动左侧的分隔符，把它放在两个分类之间。\n放到最前面，可以分开固定应用与分类入口。", muted=True, wrap=True))
        self.split_background = _Toggle("分隔符同时划开玻璃背景", light)
        self.split_background.setChecked(bool(dock_config.get("sep_split", True)) if dock_config is not None else True)
        self.split_background.setVisible(dock_config is not None)
        self.split_background.toggled.connect(self._split_changed);separator_layout.addSpacing(14)
        separator_layout.addWidget(self.split_background)
        separator_layout.addWidget(_label("关闭时保留分隔线，玻璃背景连续；对所有分隔符生效。", muted=True, wrap=True))
        separator_layout.addStretch()
        separator_layout.addWidget(_label("分隔符只改变显示布局，不参与分类匹配。\n两边都有图标时才会显示。", muted=True, wrap=True))
        self.editor_stack.addWidget(separator_page)
        empty = QFrame();empty.setObjectName("emptyCard");empty_layout = QVBoxLayout(empty)
        empty_layout.setContentsMargins(30, 30, 30, 30);empty_layout.addStretch()
        empty_icon = QLabel();empty_icon.setPixmap(_artwork("apps", 76, light));empty_icon.setAlignment(Qt.AlignCenter)
        empty_layout.addWidget(empty_icon)
        empty_title = _label("创建你的第一个分类", name="sectionTitle");empty_title.setAlignment(Qt.AlignCenter);empty_layout.addWidget(empty_title)
        empty_note = _label("应用、工作资料、灵感收藏……\n从一个分类开始，按自己的习惯整理。", muted=True, wrap=True)
        empty_note.setAlignment(Qt.AlignCenter);empty_layout.addWidget(empty_note)
        empty_layout.addSpacing(12);empty_layout.addWidget(_button("＋  新建分类", self._add), 0, Qt.AlignCenter);empty_layout.addStretch()
        self.editor_stack.addWidget(empty);outer.addWidget(split, 1)

        footer = QHBoxLayout();footer.setSpacing(10)
        self.status = _label("更改仅在保存后生效", muted=True, name="eyebrow");footer.addWidget(self.status)
        self.restore_excluded = _Toggle("恢复已移除的 %d 个入口" % len(service.state.get("excluded", [])), light)
        self.restore_excluded.setVisible(bool(service.state.get("excluded", [])))
        self.restore_excluded.setToolTip("保存时取消排除，让这些入口重新按规则分类")
        self.restore_excluded.toggled.connect(self._mark_dirty);footer.addWidget(self.restore_excluded)
        footer.addStretch()
        footer.addWidget(_button("取消", self.reject, quiet=True))
        self.save_button = _button("保存设置", self._save, primary=True);self.save_button.setMinimumWidth(106)
        self.save_button.setToolTip("保存全部更改 · Ctrl+S");footer.addWidget(self.save_button)
        footer.addWidget(QSizeGrip(self), 0, Qt.AlignBottom);outer.addLayout(footer)
        QShortcut(QKeySequence.Save, self, activated=self._save)
        self._populate();self._loading = False;self._refresh_order();self._split_changed()
        self.list.setCurrentRow(0 if self.list.count() else -1)
        if not self.list.count():
            self._switch(None, None)
        self.status.setText("更改仅在保存后生效")
        screen = parent.screen() if parent is not None else QApplication.primaryScreen()
        available = screen.availableGeometry()
        self.setMinimumSize(min(820, available.width() - 24), min(560, available.height() - 24))
        self.resize(min(1000, available.width() - 24), min(720, available.height() - 24))
        self.move(available.center() - self.rect().center())
        self.capture_background(screen)

    def _item(self, category):
        item = QListWidgetItem(QIcon(_artwork(category.get("icon", "folders"), 40, self.light)), category["name"])
        item.setData(Qt.UserRole, category["id"]);item.setToolTip(category["name"])
        count = len(category.get("rules", []))
        item.setData(Qt.UserRole + 1, ("%d 条自动规则" % count) if count else "手动归类")
        return item

    def _populate(self):
        self.list.blockSignals(True);self.list.clear()
        if "__before_categories__" in self.separators:
            self.list.addItem(self._separator_item())
        for category in self.categories:
            self.list.addItem(self._item(category))
            if category["id"] in self.separators:
                self.list.addItem(self._separator_item())
        self.list.blockSignals(False)

    @staticmethod
    def _separator_item():
        item = QListWidgetItem("分隔符");item.setData(Qt.UserRole, "__separator__")
        item.setToolTip("拖动以调整 Dock 分区");return item

    def _category(self, category_id):
        return next((c for c in self.categories if c["id"] == category_id), None)

    def _mark_dirty(self, *_):
        if not self._loading:
            self.status.setText("有未保存的更改")

    def _refresh_order(self):
        count = 0
        for row in range(self.list.count()):
            item = self.list.item(row)
            if item.data(Qt.UserRole) != "__separator__":
                count += 1;item.setData(Qt.UserRole + 2, count)
        self.category_count.setText(str(count))
        self.list.viewport().update()

    def _order_changed(self, *_):
        self._refresh_order();self._mark_dirty()

    def _stash(self):
        category = self._category(self.current_id)
        if category is not None:
            category.update(name=self.name.text().strip() or "未命名分类", icon=self.icon.currentData(),
                            mode=self.mode.currentData(), rules=[r.value() for r in self.rule_rows if r.value()["value"]])
            item = self.list.currentItem()
            # currentItemChanged 时 currentItem 已是下一项，按 ID 更新旧项目。
            for row in range(self.list.count()):
                item = self.list.item(row)
                if item.data(Qt.UserRole) == self.current_id:
                    item.setText(category["name"]);item.setToolTip(category["name"])
                    item.setIcon(QIcon(_artwork(category["icon"], 40, self.light)))
                    count = len(category["rules"])
                    item.setData(Qt.UserRole + 1, ("%d 条自动规则" % count) if count else "手动归类")
                    break

    def _switch(self, current, previous):
        self._stash()
        self.current_id = current.data(Qt.UserRole) if current else None
        category = self._category(self.current_id)
        self.delete_button.setEnabled(category is not None or self.current_id == "__separator__")
        self.editor_stack.setCurrentIndex(0 if category is not None else 1 if self.current_id == "__separator__" else 2)
        if category is None:
            return
        self._loading = True
        self.name.setText(category["name"])
        self.icon.setCurrentIndex(max(0, self.icon.findData(category.get("icon", "folders"))))
        self.mode.setCurrentIndex(max(0, self.mode.findData(category.get("mode", "any"))))
        for row in list(self.rule_rows):
            self._remove_rule(row)
        for rule in category.get("rules", []):
            self._append_rule(rule)
        self._update_rules();self._icon_changed()
        self.editor_scroll.verticalScrollBar().setValue(0)
        self._loading = False

    def _name_changed(self, text):
        if self._loading:
            return
        item = self.list.currentItem()
        if item and item.data(Qt.UserRole) != "__separator__":
            item.setText(text.strip() or "未命名分类");item.setToolTip(text.strip() or "未命名分类")
        self._mark_dirty()

    def _icon_changed(self, *_):
        key = self.icon.currentData() or "folders"
        self.icon_button.setIcon(QIcon(_artwork(key, 68, self.light)))
        if not self._loading:
            item = self.list.currentItem()
            if item and item.data(Qt.UserRole) != "__separator__":
                item.setIcon(QIcon(_artwork(key, 40, self.light)))
        self._mark_dirty()

    def _pick_icon(self):
        if self._picker is not None:
            self._picker.close()
        picker = _IconPicker(self, self.light, self.icon.currentData())
        self._picker = picker
        picker.destroyed.connect(lambda: setattr(self, "_picker", None) if self._picker is picker else None)
        picker.selected.connect(lambda key: self.icon.setCurrentIndex(self.icon.findData(key)))
        point = self.icon_button.mapToGlobal(QPoint(0, self.icon_button.height() + 6))
        area = (QApplication.screenAt(point) or QApplication.primaryScreen()).availableGeometry()
        point.setX(max(area.left() + 8, min(point.x(), area.right() - picker.width() - 8)))
        point.setY(max(area.top() + 8, min(point.y(), area.bottom() - picker.height() - 8)))
        picker.move(point);picker.show()

    def _append_rule(self, rule=None):
        row = _RuleRow(rule, self.rules_widget, self.light)
        row.removed.connect(self._remove_rule);row.changed.connect(self._rule_changed)
        self.rule_rows.append(row);self.rules_layout.addWidget(row)
        self._update_rules();self._mark_dirty()

    def _remove_rule(self, row):
        self.rules_layout.removeWidget(row);self.rule_rows.remove(row)
        row.hide();row.deleteLater();self._update_rules();self._mark_dirty()

    def _rule_changed(self):
        self._update_rules();self._mark_dirty()

    def _update_rules(self):
        count = len(self.rule_rows)
        self.rule_count.setText("%d 条规则" % count)
        self.rule_empty.setVisible(not count)
        for index, row in enumerate(self.rule_rows, 1):
            row.number.setText("%02d" % index)
        if not self._loading:
            item = self.list.currentItem()
            if item and item.data(Qt.UserRole) != "__separator__":
                active = sum(bool(r.value()["value"]) for r in self.rule_rows)
                item.setData(Qt.UserRole + 1, ("%d 条自动规则" % active) if active else "手动归类")

    def _split_changed(self, *_):
        self.separator_preview.split = self.split_background.isChecked()
        self.separator_preview.update();self._mark_dirty()

    def _add(self):
        self._stash()
        category = {"id": uuid.uuid4().hex, "name": "新分类", "icon": "folders", "mode": "any", "rules": []}
        self.categories.append(category);item = self._item(category);self.list.addItem(item)
        self.list.setCurrentItem(item);self._refresh_order();self._mark_dirty()
        self.name.setFocus();self.name.selectAll()

    def _add_separator(self):
        self._stash()
        if self.current_id == "__separator__":
            return
        row = self.list.currentRow() + 1 if self.list.currentRow() >= 0 else self.list.count()
        for neighbor in (row - 1, row):
            item = self.list.item(neighbor)
            if item is not None and item.data(Qt.UserRole) == "__separator__":
                self.list.setCurrentItem(item);return
        item = self._separator_item();self.list.insertItem(row, item);self.list.setCurrentItem(item)
        self._refresh_order();self._mark_dirty()

    def _confirm_delete(self, category):
        dialog = _GlassDialog(self, self.light);dialog.setWindowTitle("删除分类")
        dialog.snapshot = self.snapshot;dialog.screen_geometry = self.screen_geometry
        layout = QVBoxLayout(dialog);layout.setContentsMargins(24, 24, 24, 22);layout.setSpacing(15)
        layout.addWidget(_label("删除这个分类？", name="sectionTitle"))
        layout.addWidget(_label("“%s”中的项目将重新参与自动分类。原文件会保留，点击主窗口的保存设置后才生效。" % category["name"],
                                muted=True, wrap=True))
        row = QHBoxLayout();row.addStretch();row.addWidget(_button("保留分类", dialog.reject, quiet=True))
        row.addWidget(_button("删除分类", dialog.accept, primary=True));layout.addLayout(row)
        dialog.setFixedWidth(410);dialog.adjustSize();dialog.move(self.geometry().center() - dialog.rect().center())
        result = dialog.exec_() == QDialog.Accepted
        dialog.deleteLater();return result

    def _delete(self):
        category = self._category(self.current_id)
        if category is None and self.current_id != "__separator__":
            return
        if category is not None and not self._confirm_delete(category):
            return
        if category is not None:
            self.categories.remove(category)
        self.current_id = None
        item = self.list.takeItem(self.list.currentRow());del item
        if not self.list.count():
            self._switch(None, None)
        self._refresh_order();self._mark_dirty()

    def _save(self):
        self._stash()
        ordered, separators = [], []
        anchor = "__before_categories__"
        for row in range(self.list.count()):
            key = self.list.item(row).data(Qt.UserRole)
            if key == "__separator__":
                separators.append(anchor)
            else:
                ordered.append(self._category(key));anchor = key
        if self.dock_config is not None:
            self.dock_config["sep_split"] = self.split_background.isChecked()
        self.service.update_categories(ordered, separators)
        if self.restore_excluded.isChecked():
            self.service.restore_auto(list(self.service.state.get("excluded", [])))
        self.accept()
