"""Dock 共用菜单：保留 Qt 交互，按玻璃主题绘制真正透明的圆角。"""

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPalette, QPen, QPixmap
from PyQt5.QtWidgets import QMenu


def _color(value, fallback):
    return QColor(value) if value is not None else QColor(fallback)


def glyph(name, color=None):
    """小型线条图标；高分辨率画布可同时适配常见 Windows 缩放。"""
    image = QPixmap(40, 40)
    image.setDevicePixelRatio(2)
    image.fill(Qt.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(_color(color, "#e7e9f2"), 1.35, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)

    def line(x1, y1, x2, y2):
        p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

    def path(points, close=False):
        shape = QPainterPath(QPointF(*points[0]))
        for point in points[1:]:
            shape.lineTo(QPointF(*point))
        if close:
            shape.closeSubpath()
        p.drawPath(shape)

    if name == "grid":
        for x in (3.5, 11):
            for y in (3.5, 11):
                p.drawRoundedRect(QRectF(x, y, 5.5, 5.5), 1.3, 1.3)
    elif name == "list":
        for y in (4.5, 10, 15.5):
            p.drawRoundedRect(QRectF(3, y - 1.5, 3, 3), .7, .7)
            line(9, y, 17, y)
    elif name == "open":
        p.drawRoundedRect(QRectF(3.5, 7, 12, 9.5), 2, 2)
        path([(9, 11), (16.5, 3.5), (16.5, 8)])
        line(12, 3.5, 16.5, 3.5)
    elif name == "copy":
        p.drawRoundedRect(QRectF(7, 7, 10, 10), 1.7, 1.7)
        path([(5, 13), (3, 13), (3, 3), (13, 3), (13, 5)])
    elif name == "cut":
        p.drawEllipse(QRectF(3, 12, 5, 5))
        p.drawEllipse(QRectF(12, 12, 5, 5))
        line(6.5, 12.5, 15, 3)
        line(13.5, 12.5, 5, 3)
    elif name == "delete":
        line(3.5, 5.5, 16.5, 5.5)
        path([(6, 5.5), (7, 3), (13, 3), (14, 5.5)])
        path([(5, 7.5), (6, 17), (14, 17), (15, 7.5)])
        line(8.5, 8.5, 9, 14)
        line(11.5, 8.5, 11, 14)
    elif name in ("compress", "extract"):
        p.drawRoundedRect(QRectF(3, 5, 14, 12), 2, 2)
        path([(3, 6), (6, 3), (14, 3), (17, 6)])
        line(5, 8, 8, 8)
        line(5, 11, 8, 11)
        line(5, 14, 8, 14)
        if name == "compress":
            line(13, 9, 13, 14)
            path([(10.5, 11.5), (13, 14), (15.5, 11.5)])
        else:
            line(13, 14, 13, 9)
            path([(10.5, 11.5), (13, 9), (15.5, 11.5)])
    elif name == "pin":
        path([(8, 3.5), (15.5, 6.5), (13.5, 8), (12, 11.5), (13, 13.5), (6, 11), (8, 9.5), (9, 5.5)], True)
        line(8.5, 12.5, 5, 17)
    elif name == "categories":
        p.drawRoundedRect(QRectF(3, 6, 14, 10.5), 2, 2)
        path([(3, 7), (3, 4.5), (8, 4.5), (10, 6)])
        line(7, 10, 7, 13)
        line(11, 10, 11, 13)
    elif name == "automatic":
        p.drawArc(QRectF(4, 4, 12, 12), 30 * 16, 270 * 16)
        path([(13.5, 3.5), (16.5, 5), (16.5, 1.5)])
        path([(7.5, 10), (9.5, 12), (13, 8.5)])
    elif name == "remove":
        p.drawEllipse(QRectF(3.5, 3.5, 13, 13))
        line(6.5, 10, 13.5, 10)
    elif name == "settings":
        for y, knob in ((5, 7), (10, 13), (15, 8)):
            line(3.5, y, knob - 2, y)
            line(knob + 2, y, 16.5, y)
            p.drawEllipse(QRectF(knob - 2, y - 2, 4, 4))
    elif name == "location":
        p.drawRoundedRect(QRectF(3, 3, 14, 14), 2.5, 2.5)
        line(6, 14, 14, 14)
        path([(7, 8), (10, 5), (13, 8)])
        line(10, 5, 10, 11)
    elif name == "show":
        eye = QPainterPath(QPointF(2, 10))
        eye.cubicTo(6, 3, 14, 3, 18, 10)
        eye.cubicTo(14, 17, 6, 17, 2, 10)
        p.drawPath(eye)
        p.drawEllipse(QRectF(7.5, 7.5, 5, 5))
    elif name == "exit":
        p.drawArc(QRectF(4, 4.5, 12, 12), 135 * 16, 270 * 16)
        line(10, 2.5, 10, 10)
    else:
        p.drawRoundedRect(QRectF(4, 4, 12, 12), 3, 3)
    p.end()
    return QIcon(image)


class ThemedMenu(QMenu):
    """圆角菜单无原生矩形阴影，子菜单自动延续父菜单主题。"""

    def __init__(self, parent=None, light=False, colors=None):
        super().__init__(parent)
        self.setWindowFlags(self.windowFlags() | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAutoFillBackground(False)
        self.setObjectName("themedDockMenu")
        self._owned_menus = []
        self._glyph_names = {}
        self.set_theme(light, colors)

    def set_theme(self, light, colors=None):
        self.light = bool(light)
        self.colors = dict(colors or {})
        self._fg = _color(self.colors.get("label_fg", self.colors.get("fg")), "#293043" if self.light else "#f3f2fa")
        # 菜单承担阅读和操作任务，底色比 Dock 更稳定；透明仍保留玻璃层次。
        self._base = _color(self.colors.get("tint"), "#f6f5fc" if self.light else "#211b2d")
        self._base.setAlpha(244 if self.light else 242)
        self._border = _color(self.colors.get("label_border", self.colors.get("border")), "#ffffff" if self.light else "#b4a8cd")
        self._border.setAlpha(90 if self.light else 65)
        fg = self._fg.name()
        hover = "rgba(115,105,170,25)" if self.light else "rgba(198,181,236,35)"
        muted = "rgba(53,58,76,105)" if self.light else "rgba(230,225,244,95)"
        rule = "rgba(88,82,110,32)" if self.light else "rgba(234,226,253,35)"
        # 显式 ID 避免父面板的通用 QMenu 规则重新绘出方形底色和边框。
        self.setStyleSheet("""
            QMenu#themedDockMenu {
                background: transparent; border: none; padding: 7px; min-width: 200px;
                color: %s; font-family: 'Microsoft YaHei UI'; font-size: 13px;
            }
            QMenu#themedDockMenu::item {
                background: transparent; color: %s; border: none;
                min-height: 20px; padding: 7px 34px 7px 12px; border-radius: 7px;
            }
            QMenu#themedDockMenu::item:selected { background: %s; color: %s; }
            QMenu#themedDockMenu::item:disabled { color: %s; }
            QMenu#themedDockMenu::separator {
                height: 1px; background: %s; margin: 5px 9px;
            }
            QMenu#themedDockMenu::icon { padding-left: 3px; }
            QMenu#themedDockMenu::indicator { width: 16px; height: 16px; }
            QMenu#themedDockMenu::right-arrow { width: 8px; height: 8px; }
        """ % (fg, fg, hover, fg, muted, rule))
        palette = self.palette()
        for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
            palette.setColor(QPalette.Active, role, self._fg)
            palette.setColor(QPalette.Inactive, role, self._fg)
        self.setPalette(palette)
        previous_glyphs, self._glyph_names = self._glyph_names, {}
        for action in self.actions():
            name = previous_glyphs.get(action.icon().cacheKey())
            if name:
                action.setIcon(self.glyph(name))
        for menu in self._owned_menus:
            menu.set_theme(self.light, self.colors)
        self.update()

    def glyph(self, name):
        icon = glyph(name, self._fg)
        self._glyph_names[icon.cacheKey()] = name
        return icon

    def addMenu(self, *args):
        # 外部菜单保留原归属和 Qt 返回类型；只管理本类自行创建的子菜单。
        if len(args) == 1 and isinstance(args[0], QMenu):
            return super().addMenu(args[0])
        if len(args) == 1:
            title, icon = args[0], None
        elif len(args) == 2:
            icon, title = args
        else:
            raise TypeError("addMenu expects title, icon and title, or QMenu")
        menu = ThemedMenu(self, self.light, self.colors)
        menu.setTitle(title)
        if icon is not None:
            menu.setIcon(icon)
        super().addMenu(menu)
        self._owned_menus.append(menu)
        return menu

    def clear(self):
        owned, self._owned_menus = self._owned_menus, []
        self._glyph_names.clear()
        super().clear()
        for menu in owned:
            menu.hide()
            menu.deleteLater()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        # 先清除整张透明表面，悬停重绘也不会在四角留下旧像素。
        p.setCompositionMode(QPainter.CompositionMode_Source)
        p.fillRect(self.rect(), Qt.transparent)
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        rect = QRectF(self.rect()).adjusted(.5, .5, -.5, -.5)
        shape = QPainterPath()
        shape.addRoundedRect(rect, 12, 12)
        p.fillPath(shape, self._base)
        shine = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        shine.setColorAt(0, QColor(255, 255, 255, 42 if self.colors.get("gloss") else (25 if self.light else 15)))
        shine.setColorAt(.45, QColor(255, 255, 255, 0))
        shine.setColorAt(1, QColor(90, 69, 126, 9 if self.light else 14))
        p.fillPath(shape, shine)
        p.setPen(QPen(self._border, 1))
        p.drawPath(shape)
        p.end()
        # 文字、勾选、图标、快捷键、滚动箭头和键盘焦点仍由 Qt 原生菜单绘制。
        super().paintEvent(event)
