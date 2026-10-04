"""桌面虚拟分类规则；只读取文件信息，不移动、改名或删除文件。"""

import ctypes
import os
import re
import stat
import uuid


UNCATEGORIZED = "__uncategorized__"

_EXTENSIONS = {
    "apps": {".lnk", ".url", ".exe", ".appref-ms"},
    "documents": {
        ".txt", ".md", ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".xlsm",
        ".ppt", ".pptx", ".csv", ".rtf", ".odt", ".ods", ".odp", ".epub",
        ".wps", ".et", ".dps", ".log", ".json", ".xml", ".html", ".htm",
    },
    "images": {
        ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".ico",
        ".tif", ".tiff", ".heic", ".avif", ".psd",
    },
    "archives": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".iso"},
    "media": {
        ".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma", ".mp4",
        ".mkv", ".avi", ".mov", ".wmv", ".webm", ".m4v", ".mpeg", ".mpg",
    },
}


def normalize_path(path):
    """配置与索引共用路径键，不解析快捷方式或符号链接的目标。"""
    return os.path.normcase(os.path.abspath(os.path.expanduser(os.fspath(path))))


def default_state():
    presets = [
        ("apps", "应用", "apps"),
        ("documents", "文档", "documents"),
        ("images", "图片", "images"),
        ("folders", "文件夹", "folders"),
        ("archives", "压缩包", "archives"),
        ("media", "影音", "media"),
    ]
    return {
        "categories": [
            {"id": key, "name": name, "icon": icon, "mode": "any",
             "rules": [{"field": "kind", "value": key}]}
            for key, name, icon in presets
        ],
        "automatic": True,
        "view_modes": {},  # 分类各自记住大图标或单列小图标，不参与规则匹配
        "dock_separators": ["apps"],  # 保存分隔符前方的分类 ID，不参与规则匹配
        "manual": {},
        "excluded": [],
        "extra_paths": [],
    }


def separator_positions(state):
    """旧配置沿用应用分类后的隔断，显式空列表表示不使用分类分隔符。"""
    if "dock_separators" in state:
        return list(state["dock_separators"])
    return [category["id"] for category in state.get("categories", [])
            if category.get("icon") == "apps"]


class _GUID(ctypes.Structure):
    _fields_ = [("data1", ctypes.c_uint32), ("data2", ctypes.c_uint16),
                ("data3", ctypes.c_uint16), ("data4", ctypes.c_ubyte * 8)]


def _guid(value):
    return _GUID.from_buffer_copy(uuid.UUID(value).bytes_le)


def _com_method(pointer, index, result, *arguments):
    table = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return ctypes.WINFUNCTYPE(result, ctypes.c_void_p, *arguments)(table[index])


def shortcut_target(path):
    """只读本地 Shell Link 保存的目标，不运行快捷方式，也不触发 Resolve 搜索。"""
    if os.name != "nt":
        return ""
    ole = ctypes.WinDLL("ole32")
    ole.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    ole.CoInitializeEx.restype = ctypes.c_long
    ole.CoUninitialize.argtypes = []
    ole.CoCreateInstance.argtypes = [ctypes.POINTER(_GUID), ctypes.c_void_p,
                                    ctypes.c_uint32, ctypes.POINTER(_GUID),
                                    ctypes.POINTER(ctypes.c_void_p)]
    ole.CoCreateInstance.restype = ctypes.c_long
    initialized = ole.CoInitializeEx(None, 0)
    # RPC_E_CHANGED_MODE 表示当前线程已有另一种 COM apartment，可以直接使用它。
    if initialized < 0 and initialized != -2147417850:
        return ""
    link = ctypes.c_void_p()
    persist = ctypes.c_void_p()
    try:
        clsid = _guid("00021401-0000-0000-C000-000000000046")
        iid_link = _guid("000214F9-0000-0000-C000-000000000046")
        iid_persist = _guid("0000010B-0000-0000-C000-000000000046")
        if ole.CoCreateInstance(ctypes.byref(clsid), None, 1, ctypes.byref(iid_link),
                                ctypes.byref(link)) < 0:
            return ""
        query = _com_method(link, 0, ctypes.c_long, ctypes.POINTER(_GUID),
                            ctypes.POINTER(ctypes.c_void_p))
        if query(link, ctypes.byref(iid_persist), ctypes.byref(persist)) < 0:
            return ""
        # vtable 顺序来自 Windows SDK：IUnknown 0..2，IPersist.GetClassID 3，Load 5。
        load = _com_method(persist, 5, ctypes.c_long, ctypes.c_wchar_p, ctypes.c_uint32)
        if load(persist, normalize_path(path), 0) < 0:
            return ""
        buffer = ctypes.create_unicode_buffer(32768)
        get_path = _com_method(link, 3, ctypes.c_long, ctypes.c_wchar_p, ctypes.c_int,
                               ctypes.c_void_p, ctypes.c_uint32)
        if get_path(link, buffer, len(buffer), None, 0) < 0 or not buffer.value:
            return ""
        return normalize_path(os.path.expandvars(buffer.value))
    except OSError:
        return ""
    finally:
        if persist:
            _com_method(persist, 2, ctypes.c_uint32)(persist)
        if link:
            _com_method(link, 2, ctypes.c_uint32)(link)
        if initialized >= 0:
            ole.CoUninitialize()


def _path_kind(path, info):
    extension = os.path.splitext(path)[1].casefold()
    if stat.S_ISDIR(info.st_mode) or os.path.isdir(path):
        return "folders", ""
    kind = next((key for key, values in _EXTENSIONS.items() if extension in values), "other")
    return kind, extension


def describe_path(path):
    """描述一个实际存在的入口。调用方负责处理扫描期间的删除和权限变化。"""
    path = normalize_path(path)
    info = os.stat(path, follow_symlinks=False)
    name = os.path.basename(path) or path
    kind, extension = _path_kind(path, info)
    target = ""
    target_stamp = None
    if extension == ".lnk":
        target = shortcut_target(path)
        if target:
            try:
                target_info = os.stat(target)
                target_stamp = (target_info.st_size, target_info.st_mtime_ns,
                                target_info.st_ctime_ns)
                kind, extension = _path_kind(target, target_info)
            except OSError:
                pass  # 已失效、商店或特殊链接仍保留为应用入口。
    # Windows 文件创建时间用于区分被删除后复用的文件 ID；改名不会改变它。
    birth_ns = getattr(info, "st_birthtime_ns", None)
    if birth_ns is None and os.name == "nt":
        birth_ns = info.st_ctime_ns
    identity = f"{info.st_dev}:{info.st_ino}" if info.st_ino else None
    return {
        "path": path,
        "name": name,
        "kind": kind,
        "extension": extension,
        "target": target,
        "target_stamp": target_stamp,
        "identity": identity,
        "birth_ns": birth_ns,
        "stamp": (info.st_size, info.st_mtime_ns, info.st_ctime_ns),
        "attributes": getattr(info, "st_file_attributes", 0),
    }


def scan_directory(path):
    """只枚举顶层，共享桌面目录可能不存在，返回空列表即可。"""
    entries = []
    try:
        with os.scandir(path) as children:
            for child in children:
                if child.name.casefold() == "desktop.ini":
                    continue
                if os.name != "nt" and child.name.startswith("."):
                    continue
                try:
                    entry = describe_path(child.path)
                except OSError:
                    continue
                if entry["attributes"] & 0x06:  # Windows HIDDEN / SYSTEM
                    continue
                entries.append(entry)
    except OSError:
        return []
    return sorted(entries, key=lambda item: (item["kind"] != "folders",
                                            item["name"].casefold()))


def desktop_directories():
    """使用 Windows 桌面已知目录，兼容 OneDrive 重定向和公共桌面。"""
    paths = []
    if os.name == "nt":
        shell = ctypes.windll.shell32
        for folder_id in (0x0010, 0x0019):  # DESKTOPDIRECTORY / COMMON_DESKTOPDIRECTORY
            buffer = ctypes.create_unicode_buffer(32768)
            if shell.SHGetFolderPathW(None, folder_id, None, 0, buffer) == 0:
                if buffer.value:
                    paths.append(buffer.value)
    if not paths:
        paths.append(os.path.join(os.path.expanduser("~"), "Desktop"))
        if os.name == "nt" and os.environ.get("PUBLIC"):
            paths.append(os.path.join(os.environ["PUBLIC"], "Desktop"))
    return list(dict.fromkeys(normalize_path(path) for path in paths))


def _values(value):
    return [piece.strip() for piece in re.split(r"[,，\n]", value) if piece.strip()]


def _matches_rule(entry, rule):
    values = _values(rule.get("value", ""))
    if not values:
        return False
    field = rule.get("field")
    if field == "kind":
        return entry["kind"].casefold() in {value.casefold() for value in values}
    if field == "extension":
        extensions = {"." + value.casefold().lstrip("*.") for value in values}
        return bool(entry["extension"]) and entry["extension"].casefold() in extensions
    if field in ("name", "path"):
        targets = [entry[field]]
        if entry.get("target"):
            targets.append(os.path.basename(entry["target"]) if field == "name"
                           else entry["target"])
        return any(value.casefold() in target.casefold() for value in values for target in targets)
    if field == "exact":
        paths = {entry["path"], entry.get("target", "")}
        return bool(paths & {normalize_path(value) for value in values})
    return False


def matches_category(entry, category):
    """每条规则的多个值为任一值匹配；不同规则按用户选择的任意/全部组合。"""
    rules = category.get("rules", [])
    if not rules:
        return False
    results = (_matches_rule(entry, rule) for rule in rules)
    return all(results) if category.get("mode") == "all" else any(results)


def classify(entries, state):
    categories = state.get("categories", [])
    grouped = {category["id"]: [] for category in categories}
    grouped[UNCATEGORIZED] = []
    manual = state.get("manual", {})
    excluded = set(state.get("excluded", []))
    seen = set()
    for entry in entries:
        path = normalize_path(entry["path"])
        if path in seen or path in excluded:
            continue
        seen.add(path)
        assigned = manual.get(path)
        if assigned not in grouped:
            assigned = None
        # automatic 只控制服务的变化监听，一键整理始终执行规则。
        if assigned is None:
            assigned = next((category["id"] for category in categories
                             if matches_category(entry, category)), None)
        grouped[assigned or UNCATEGORIZED].append(entry)
    return grouped


def _same_file(old, new):
    if not old.get("identity") or old["identity"] != new.get("identity"):
        return False
    if old.get("birth_ns") is not None or new.get("birth_ns") is not None:
        return old.get("birth_ns") == new.get("birth_ns")
    # 没有创建时间的平台采用保守判断，避免 inode 被复用后错误继承归属。
    return tuple(old.get("stamp", ())[:2]) == tuple(new.get("stamp", ())[:2])


def reconcile_entries(old_entries, new_entries, state):
    """按文件身份追踪改名，原位维护归属；不把已删除入口的覆盖留给后来同名文件。"""
    old_by_path = {entry["path"]: entry for entry in old_entries}
    new_by_path = {entry["path"]: entry for entry in new_entries}
    old_by_identity = {}
    new_by_identity = {}
    for entry in old_entries:
        if entry.get("identity"):
            old_by_identity.setdefault(entry["identity"], []).append(entry)
    for entry in new_entries:
        if entry.get("identity"):
            new_by_identity.setdefault(entry["identity"], []).append(entry)
    moves = {}
    removed = set()
    for path, old in old_by_path.items():
        current = new_by_path.get(path)
        if current is not None and _same_file(old, current):
            continue
        candidates = new_by_identity.get(old.get("identity"), [])
        # 硬链接等多入口身份不明确时，不擅自迁移手动归属。
        if len(old_by_identity.get(old.get("identity"), [])) == 1 and len(candidates) == 1:
            candidate = candidates[0]
            if candidate["path"] != path and _same_file(old, candidate):
                moves[path] = candidate["path"]
                continue
        removed.add(path)
    manual = state.setdefault("manual", {})
    state["manual"] = {moves.get(path, path): category for path, category in manual.items()
                       if path not in removed}
    for key in ("excluded", "extra_paths"):
        state[key] = list(dict.fromkeys(moves.get(path, path)
                                       for path in state.get(key, []) if path not in removed))
    return new_entries
