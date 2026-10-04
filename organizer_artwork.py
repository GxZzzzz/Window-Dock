# -*- coding: utf-8 -*-
"""分类入口共用独立图标；不在绘制期间访问文件或外壳。"""

from PyQt5.QtCore import Qt, QRectF
from PyQt5.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap, QLinearGradient
from icon_theme import themed_icon

_native = {}


def set_native_icons(icons):
    _native.clear()
    _native.update({key: value for key, value in icons.items()
                    if value is not None and not value.isNull()})


def category_pixmap(icon_key, size, light=True):
    """Dock、分类标题和设置共用图标；后续成套资源可通过 _native 替换。"""
    themed = themed_icon(icon_key, size)
    if themed is not None:
        return themed
    image = QPixmap(size, size)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.SmoothPixmapTransform)
    painter.scale(size / 64.0, size / 64.0)
    fallback = {"ide": "code", "office": "work", "industrial": "code",
                "entertainment": "media", "utilities": "apps"}.get(icon_key, icon_key)
    native = _native.get(fallback)
    if fallback == "apps":
        icon_key = "apps"
    if icon_key != "apps" and native is None:
        native = _native.get("folders")
    if icon_key == "apps" and native is None:
        # 临时应用符号：四格独立色块，无容器底板，不拼接分类内应用缩略图。
        for x, y in ((7, 7), (35, 7), (7, 35), (35, 35)):
            rect = QRectF(x, y, 22, 22)
            gradient = QLinearGradient(x, y, x + 22, y + 22)
            gradient.setColorAt(0, QColor("#87d6ff"))
            gradient.setColorAt(1, QColor("#4785e8"))
            painter.setBrush(gradient)
            painter.setPen(QPen(QColor(225, 247, 255, 190), .65))
            painter.drawRoundedRect(rect, 5, 5)
    elif native is not None:
        # 系统图标本身包含阴影和透明留白，避免再次套底板或画拟物轮廓。
        painter.drawPixmap(QRectF(0, 0, 64, 64), native, QRectF(native.rect()))
    else:
        # 极少数外壳提取失败时只提供简洁的文件夹轮廓。
        folder = QPainterPath()
        folder.moveTo(5, 18)
        folder.quadTo(5, 14, 9, 14)
        folder.lineTo(26, 14)
        folder.lineTo(31, 20)
        folder.lineTo(55, 20)
        folder.quadTo(59, 20, 59, 24)
        folder.lineTo(59, 51)
        folder.quadTo(59, 55, 55, 55)
        folder.lineTo(9, 55)
        folder.quadTo(5, 55, 5, 51)
        folder.closeSubpath()
        gradient = QLinearGradient(0, 14, 0, 55)
        gradient.setColorAt(0, QColor("#ffdb78"))
        gradient.setColorAt(1, QColor("#edb748"))
        painter.setPen(QPen(QColor("#cc9d3b"), .6))
        painter.setBrush(gradient)
        painter.drawPath(folder)
    painter.end()
    return image
