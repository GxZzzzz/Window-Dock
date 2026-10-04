"""按需读取成套入口图标，缓存缩放结果；绘制期间不扫描资源目录。"""

from functools import lru_cache
import json
from pathlib import Path
import sys

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap


@lru_cache(maxsize=1)
def _theme():
    root = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
    folder = root / "assets" / "icons" / "ios-category-v2"
    if not folder.is_dir() and getattr(sys, "frozen", False):
        folder = Path(sys._MEIPASS) / "assets" / "icons" / "ios-category-v2"
    try:
        return folder, json.loads((folder / "manifest.json").read_text(encoding="utf-8-sig"))["icons"]
    except (OSError, ValueError, KeyError):
        return folder, {}


@lru_cache(maxsize=96)
def themed_icon(key, size):
    key = {"code": "ide", "work": "office"}.get(key, key)
    folder, icons = _theme()
    relative = icons.get(key)
    if not relative:
        return None
    image = QPixmap(str(folder / relative))
    if image.isNull():
        return None
    return image.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
