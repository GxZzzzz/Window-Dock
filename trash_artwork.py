"""系统入口的矢量图标按尺寸和主题缓存，绘制帧只缩放位图。"""

from functools import lru_cache
from PyQt5.QtCore import Qt, QRectF, QPointF
from PyQt5.QtGui import QColor, QPixmap, QPainter, QPainterPath, QLinearGradient, QPen
from icon_theme import themed_icon


@lru_cache(maxsize=16)
def computer_pixmap(size, light=False):
    themed = themed_icon("computer", size)
    if themed is not None:
        return themed
    image = QPixmap(size, size)
    image.fill(Qt.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(size / 64.0, size / 64.0)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(9, 18, 32, 35))
    p.drawEllipse(QRectF(17, 54, 30, 5))
    metal = QLinearGradient(20, 43, 42, 57)
    metal.setColorAt(0, QColor("#e4f3fc"))
    metal.setColorAt(.55, QColor("#a4c2d6"))
    metal.setColorAt(1, QColor("#7895b0"))
    p.setBrush(metal)
    stand = QPainterPath()
    stand.moveTo(27, 43)
    stand.lineTo(37, 43)
    stand.lineTo(38.5, 52)
    stand.lineTo(43, 54)
    stand.quadTo(44, 56, 41, 56)
    stand.lineTo(23, 56)
    stand.quadTo(20, 56, 21, 54)
    stand.lineTo(25.5, 52)
    stand.closeSubpath()
    p.drawPath(stand)

    # 与垃圾桶共用冰银材质和蓝绿色调，屏幕留出清晰的窄边框。
    frame = QLinearGradient(7, 9, 55, 47)
    frame.setColorAt(0, QColor("#effaff"))
    frame.setColorAt(.5, QColor("#c5dce9"))
    frame.setColorAt(1, QColor("#7895b0"))
    p.setBrush(frame)
    p.setPen(QPen(QColor("#628198") if light else QColor("#c3e1f0"), .7))
    p.drawRoundedRect(QRectF(5, 9, 54, 37), 4, 4)
    screen = QPainterPath()
    screen.addRoundedRect(QRectF(8, 12, 48, 28), 2, 2)
    sky = QLinearGradient(8, 12, 51, 40)
    sky.setColorAt(0, QColor("#132d51"))
    sky.setColorAt(.55, QColor("#276e9c"))
    sky.setColorAt(1, QColor("#61c8ce"))
    p.fillPath(screen, sky)
    p.save()
    p.setClipPath(screen)
    wave = QPainterPath()
    wave.moveTo(5, 38)
    wave.cubicTo(24, 9, 35, 51, 60, 23)
    wave.lineTo(60, 43)
    wave.lineTo(5, 43)
    wave.closeSubpath()
    glow = QLinearGradient(20, 23, 40, 43)
    glow.setColorAt(0, QColor(184, 247, 245, 225))
    glow.setColorAt(1, QColor(45, 140, 183, 80))
    p.fillPath(wave, glow)
    p.restore()
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#658b9f"))
    p.drawEllipse(QRectF(31, 42, 2, 2))
    p.end()
    return image


@lru_cache(maxsize=24)
def trash_pixmap(size, full=False, light=False):
    themed = themed_icon("trash_full" if full else "trash_empty", size)
    if themed is not None:
        return themed
    image = QPixmap(size, size)
    image.fill(Qt.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(size / 64.0, size / 64.0)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(9, 18, 32, 35))
    p.drawEllipse(QRectF(15, 54, 36, 6))

    # 略收腰的冰银桶身，统一投影和窄边高光，小尺寸仍能看清轮廓。
    body = QPainterPath()
    body.moveTo(13, 18)
    body.lineTo(17.2, 51)
    body.cubicTo(17.8, 56, 23, 58, 32, 58)
    body.cubicTo(41, 58, 46.2, 56, 46.8, 51)
    body.lineTo(51, 18)
    body.closeSubpath()
    material = QLinearGradient(12, 24, 51, 39)
    for stop, color in ((0, "#93b1c8"), (.18, "#e4f3fc"), (.48, "#c5dce9"),
                        (.78, "#a4c2d6"), (1, "#7895b0")):
        material.setColorAt(stop, QColor(color))
    p.setBrush(material)
    p.setPen(QPen(QColor("#628198") if light else QColor("#c3e1f0"), .7))
    p.drawPath(body)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#526f87"))
    p.drawEllipse(QRectF(13, 13, 38, 11))
    p.setBrush(QColor("#243f58"))
    p.drawEllipse(QRectF(16, 15, 32, 7))

    if full:
        # 满桶仅露出两张纸，不加数量徽标，保持 Dock 简洁。
        for x, y, angle, fill in ((20, 5, -13, "#eef8ff"), (34, 7, 14, "#76d7de")):
            p.save()
            p.translate(x + 6, y + 9)
            p.rotate(angle)
            p.setBrush(QColor(fill))
            p.setPen(QPen(QColor("#9ab6c6"), .6))
            p.drawRoundedRect(QRectF(-6, -9, 13, 20), 1.5, 1.5)
            p.setPen(QPen(QColor(74, 116, 140, 90), .8))
            for line_y in (-4, 0, 4):
                p.drawLine(QPointF(-3, line_y), QPointF(4, line_y))
            p.restore()

    # 前沿覆盖纸张根部，避免纸像悬浮在桶外。
    lip = QPainterPath()
    lip.moveTo(13, 18)
    lip.cubicTo(17, 26, 47, 26, 51, 18)
    p.setPen(QPen(QColor("#e9faff"), 2.4, Qt.SolidLine, Qt.RoundCap))
    p.setBrush(Qt.NoBrush)
    p.drawPath(lip)
    p.setPen(QPen(QColor(255, 255, 255, 95), 1, Qt.SolidLine, Qt.RoundCap))
    p.drawLine(QPointF(18, 27), QPointF(21, 50))

    # 三段循环箭头作为统一标识，采用蓝绿冷色，不依赖系统字体符号。
    p.setPen(QPen(QColor("#2c7e92"), 2.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)
    for angle in (0, 120, 240):
        p.save()
        p.translate(32, 40)
        p.rotate(angle)
        arrow = QPainterPath()
        arrow.moveTo(-4.7, -5.8)
        arrow.quadTo(1.5, -8.6, 6.2, -2.7)
        arrow.moveTo(6.1, -6.2)
        arrow.lineTo(6.2, -2.7)
        arrow.lineTo(2.6, -3.2)
        p.drawPath(arrow)
        p.restore()
    p.end()
    return image
