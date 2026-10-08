"""桌面分类索引与事件监听；所有文件操作均为只读。"""

import copy
import os
import stat

from PyQt5.QtCore import QObject, QFileSystemWatcher, QThread, QTimer, pyqtSignal

from organizer import (classify, default_state, describe_path, desktop_directories,
                       normalize_path, reconcile_entries, separator_positions)


def _cached_description(path, info, previous):
    stamp = (info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    identity = f"{info.st_dev}:{info.st_ino}" if info.st_ino else None
    attributes = getattr(info, "st_file_attributes", 0)
    birth_ns = getattr(info, "st_birthtime_ns", None)
    if (previous and previous.get("stamp") == stamp
            # Windows scandir 的 stat 不提供文件 ID，未变化时无需另开句柄取 ID。
            and (not info.st_ino or previous.get("identity") == identity)
            and (birth_ns is None or previous.get("birth_ns") == birth_ns)
            and previous.get("attributes") == attributes):
        target = previous.get("target")
        if target:
            try:
                target_info = os.stat(target)
                target_stamp = (target_info.st_size, target_info.st_mtime_ns,
                                target_info.st_ctime_ns)
            except OSError:
                target_info = None
                target_stamp = None
            if target_stamp != previous.get("target_stamp"):
                if (target_info is None or previous.get("target_stamp") is None
                        or stat.S_ISDIR(target_info.st_mode) != (previous["kind"] == "folders")):
                    # 目标消失、恢复或类型变化才重新解析 Shell Link；不额外监听目标目录。
                    return describe_path(path)
                # 目录内容和文件内容变化不改变分类，更新轻量元数据即可。
                refreshed = dict(previous)
                refreshed["target_stamp"] = target_stamp
                return refreshed
        return previous
    return describe_path(path)


class _IndexWorker(QThread):
    result = pyqtSignal(object)

    def __init__(self, generation, directories, targets, extra_paths,
                 directory_cache, extra_cache, notify=False, parent=None):
        super().__init__(parent)
        self.generation = generation
        self.directories = directories
        self.targets = targets
        self.extra_paths = extra_paths
        # 每次任务拥有自己的映射，描述项只读共享，避免复制图标或界面对象。
        self.directory_cache = {path: dict(items) for path, items in directory_cache.items()}
        self.extra_cache = dict(extra_cache)
        self.notify = notify

    def run(self):
        errors = []
        try:
            for directory in self.directories:
                if self.isInterruptionRequested():
                    return
                if directory not in self.targets:
                    continue
                previous = self.directory_cache.get(directory, {})
                refreshed = {}
                try:
                    with os.scandir(directory) as children:
                        for child in children:
                            if self.isInterruptionRequested():
                                return
                            if child.name.casefold() == "desktop.ini":
                                continue
                            if os.name != "nt" and child.name.startswith("."):
                                continue
                            path = normalize_path(child.path)
                            try:
                                info = child.stat(follow_symlinks=False)
                                if getattr(info, "st_file_attributes", 0) & 0x06:
                                    continue
                                refreshed[path] = _cached_description(path, info, previous.get(path))
                            except OSError:
                                # 枚举后立即删除的单个文件无需使整次分类失败。
                                continue
                    self.directory_cache[directory] = refreshed
                except FileNotFoundError:
                    self.directory_cache[directory] = {}
                except OSError as exc:
                    errors.append(f"无法读取分类目录 {directory}：{exc}")

            extras = {}
            for path in self.extra_paths:
                if self.isInterruptionRequested():
                    return
                previous = self.extra_cache.get(path)
                if os.path.dirname(path) not in self.targets and path not in self.targets and previous:
                    extras[path] = previous
                    continue
                try:
                    info = os.stat(path, follow_symlinks=False)
                    extras[path] = _cached_description(path, info, previous)
                except FileNotFoundError:
                    # 手动入口改名后，通过同目录的文件身份恢复，保留其手动归属。
                    if previous and previous.get("identity"):
                        replacement = self._renamed_extra(path, previous)
                        if replacement:
                            extras[replacement["path"]] = replacement
                except OSError as exc:
                    if previous:
                        extras[path] = previous
                    errors.append(f"无法读取手动入口 {path}：{exc}")
            self.result.emit({"generation": self.generation,
                              "directories": self.directory_cache,
                              "extras": extras, "errors": errors, "notify": self.notify})
        except Exception as exc:
            self.result.emit({"generation": self.generation, "fatal": str(exc)})

    def _renamed_extra(self, path, previous):
        candidates = []
        try:
            with os.scandir(os.path.dirname(path)) as children:
                for child in children:
                    if self.isInterruptionRequested():
                        return None
                    try:
                        # Windows DirEntry.stat 的 ino/dev 为 0，改名匹配必须读实际文件 ID。
                        info = os.stat(child.path, follow_symlinks=False)
                        identity = f"{info.st_dev}:{info.st_ino}" if info.st_ino else None
                        if identity != previous["identity"]:
                            continue
                        candidate = describe_path(child.path)
                        if (candidate.get("birth_ns") == previous.get("birth_ns")
                                and (candidate.get("birth_ns") is not None
                                     or candidate["stamp"][:2] == previous["stamp"][:2])):
                            candidates.append(candidate)
                    except OSError:
                        continue
        except OSError:
            return None
        return candidates[0] if len(candidates) == 1 else None


class OrganizerService(QObject):
    changed = pyqtSignal()
    busyChanged = pyqtSignal(bool)
    error = pyqtSignal(str)
    completed = pyqtSignal(int)

    def __init__(self, state, save_callback, parent=None, directories=None):
        super().__init__(parent)
        self.state = state
        # 在补默认值前记录旧版已有隔断，避免升级改变用户当前布局。
        self.state.setdefault("dock_separators", separator_positions(self.state))
        for key, value in default_state().items():
            self.state.setdefault(key, value)
        self._save_callback = save_callback
        selected = desktop_directories() if directories is None else directories
        self.directories = list(dict.fromkeys(normalize_path(path) for path in selected))
        self.entries = {}
        self._groups_cache = None
        self._directory_cache = {}
        self._extra_cache = {}
        self._worker = None
        self._generation = 0
        self._started = False
        self._pending = set()
        self._pending_notify = False
        self._pending_explicit = False
        self._busy = False
        self._failed_watch = set()
        self._reported_errors = set()
        self._watcher = QFileSystemWatcher(self)
        self._watcher.directoryChanged.connect(self._queue_change)
        self._watcher.fileChanged.connect(self._queue_change)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(300)
        self._debounce.timeout.connect(self._launch_pending)
        self._fallback = QTimer(self)
        self._fallback.setInterval(60000)
        self._fallback.timeout.connect(self._retry_failed_watches)

    def start(self):
        if self._started:
            return
        self._started = True
        self._generation += 1
        self._sync_watches()
        self._request_scan(False)

    def stop(self):
        self._started = False
        self._generation += 1
        self._pending.clear()
        self._pending_notify = False
        self._pending_explicit = False
        self._debounce.stop()
        self._fallback.stop()
        paths = self._watcher.directories() + self._watcher.files()
        if paths:
            self._watcher.removePaths(paths)
        if self._worker:
            self._worker.requestInterruption()
            # 只读顶层任务会在下一条入口处取消，退出时不能销毁运行中的 QThread。
            self._worker.wait()
            self._worker.deleteLater()
            self._worker = None
        self._set_busy(False)

    def groups(self):
        # Dock、面板和完成提示共享同一份结果，只有索引或归属改变才重算。
        if self._groups_cache is None:
            grouped = classify(self.entries.values(), self.state)
            for category, items in grouped.items():
                positions = {path: index for index, path in enumerate(self.state.get("item_order", {}).get(category, []))}
                items.sort(key=lambda item: (positions.get(normalize_path(item["path"]), len(positions)),
                                             item["kind"] != "folders", item["name"].casefold()))
            self._groups_cache = grouped
        return self._groups_cache

    def _notify_changed(self):
        self._groups_cache = None
        self.changed.emit()

    def request_scan(self):
        """用户的一键整理仍然可用，自动开关只约束后台更新。"""
        self._pending_explicit = True
        self._request_scan(True)

    def _request_scan(self, notify):
        self._pending_notify = self._pending_notify or notify
        self._pending.update(self.directories)
        self._pending.update(os.path.dirname(normalize_path(path))
                             for path in self.state.get("extra_paths", []))
        if self._started:
            self._debounce.stop()
            self._launch_pending()

    def set_automatic(self, enabled):
        enabled = bool(enabled)
        if self.state.get("automatic", True) == enabled:
            return
        self.state["automatic"] = enabled
        self._persist()
        self._sync_watches()
        if enabled:
            self._request_scan(False)
        else:
            # 自动开关不能取消正在排队的一键整理或手动拖入。
            if not self._pending_explicit:
                self._pending.clear()
                self._pending_notify = False
            self._debounce.stop()
        self._notify_changed()

    def update_categories(self, categories, separators=None):
        positions = separator_positions(self.state) if separators is None else separators
        self.state["categories"] = copy.deepcopy(categories)
        ids = {category["id"] for category in categories}
        self.state["dock_separators"] = [key for key in dict.fromkeys(positions)
                                         if key in ids or key == "__before_categories__"]
        self.state["manual"] = {path: category for path, category
                                in self.state.get("manual", {}).items() if category in ids}
        self.state["view_modes"] = {key: mode for key, mode in self.state.get("view_modes", {}).items()
                                    if key in ids or key == "__uncategorized__"}
        self.state["item_order"] = {key: order for key, order in self.state.get("item_order", {}).items()
                                    if key in ids or key == "__uncategorized__"}
        self._persist()
        self._notify_changed()

    def set_view_mode(self, category_id, mode):
        self.state.setdefault("view_modes", {})[category_id] = mode
        # 仅保存显示偏好，不触发文件索引、重新分类或 Dock 动画重建。
        self._persist()

    def reorder_paths(self, category_id, paths, before=None):
        current = [normalize_path(entry["path"]) for entry in self.groups().get(category_id, [])]
        selected = {normalize_path(path) for path in paths}
        moving = [path for path in current if path in selected]
        if not moving:
            return
        remaining = [path for path in current if path not in selected]
        before = normalize_path(before) if before else None
        offset = remaining.index(before) if before in remaining else len(remaining)
        ordered = remaining[:offset] + moving + remaining[offset:]
        if ordered == current:
            return
        self.state.setdefault("item_order", {})[category_id] = ordered
        # 放手后保存一次；排序只重用现有索引，不启动扫描。
        self._persist()
        self._notify_changed()

    def assign_paths(self, paths, category_id):
        if category_id not in {item["id"] for item in self.state["categories"]}:
            return
        extras = set(self.state.get("extra_paths", []))
        self._pending_explicit = True
        excluded = set(self.state.get("excluded", []))
        for supplied in paths:
            path = normalize_path(supplied)
            self.state["manual"][path] = category_id
            excluded.discard(path)
            if os.path.dirname(path) not in self.directories:
                extras.add(path)
            self._pending.add(os.path.dirname(path))
        self.state["extra_paths"] = sorted(extras)
        self.state["excluded"] = sorted(excluded)
        self._persist()
        self._sync_watches()
        self._notify_changed()
        if self._started:
            self._debounce.stop()
            self._launch_pending()

    def restore_auto(self, paths):
        excluded = set(self.state.get("excluded", []))
        for supplied in paths:
            path = normalize_path(supplied)
            self.state["manual"].pop(path, None)
            excluded.discard(path)
        self.state["excluded"] = sorted(excluded)
        self._persist()
        self._notify_changed()

    def exclude_paths(self, paths):
        excluded = set(self.state.get("excluded", []))
        for supplied in paths:
            path = normalize_path(supplied)
            excluded.add(path)
            self.state["manual"].pop(path, None)
        self.state["excluded"] = sorted(excluded)
        self._persist()
        self._notify_changed()

    def _queue_change(self, path):
        if not self._started or not self.state.get("automatic", True):
            return
        path = normalize_path(path)
        self._pending.add(path if path in self.directories else os.path.dirname(path)
                          if path in self._watcher.files() or path in self._extra_cache else path)
        self._debounce.start()

    def _launch_pending(self):
        if not self._started or self._worker:
            return
        if not (self._pending or self._pending_explicit or self._pending_notify):
            self._set_busy(False)
            return
        targets = set(self._pending)
        self._pending.clear()
        # 空桌面目录列表也允许首次任务处理手动入口。
        worker = _IndexWorker(self._generation, self.directories, targets,
                              list(self.state.get("extra_paths", [])),
                              self._directory_cache, self._extra_cache,
                              self._pending_notify, self)
        self._pending_notify = False
        self._pending_explicit = False
        self._worker = worker
        worker.result.connect(self._accept_result)
        worker.finished.connect(self._worker_finished)
        self._set_busy(True)
        worker.start()

    def _accept_result(self, result):
        if not self._started or result["generation"] != self._generation:
            return
        if "fatal" in result:
            self._report_error("分类索引更新失败：" + result["fatal"])
            return
        self._directory_cache = result["directories"]
        self._extra_cache = result["extras"]
        combined = {}
        for items in self._directory_cache.values():
            combined.update(items)
        combined.update(self._extra_cache)
        before = copy.deepcopy(self.state)
        reconcile_entries(self.entries.values(), combined.values(), self.state)
        changed = self.entries != combined or self.state != before
        self.entries = combined
        if self.state != before:
            self._persist()
        self._sync_watches()
        for message in result["errors"]:
            self._report_error(message)
        if changed:
            self._notify_changed()
        if result["notify"]:
            self.completed.emit(sum(len(items) for items in self.groups().values()))

    def _worker_finished(self):
        worker = self.sender()
        if worker is not self._worker:
            return
        self._worker = None
        worker.deleteLater()
        if self._started and (self._pending or self._pending_explicit or self._pending_notify):
            # 运行中的扫描结束，也要等文件事件安静满 300ms，避免绕过事件合并。
            if not self._debounce.isActive():
                self._launch_pending()
        else:
            self._set_busy(False)

    def _sync_watches(self):
        desired = set()
        if self._started and self.state.get("automatic", True):
            desired.update(self.directories)
            for path in self.state.get("extra_paths", []):
                desired.add(os.path.dirname(path))
                entry = self.entries.get(path)
                if entry and entry["kind"] != "folders":
                    desired.add(path)
        current = set(self._watcher.directories() + self._watcher.files())
        obsolete = current - desired
        if obsolete:
            self._watcher.removePaths(list(obsolete))
        failed = set(self._watcher.addPaths(list(desired - current))) if desired - current else set()
        self._failed_watch = failed
        for path in sorted(failed):
            self._report_error(f"无法监听 {path} 的变化，暂时每 60 秒检查一次。")
        if failed and self._started:
            self._fallback.start()
        else:
            self._fallback.stop()

    def _retry_failed_watches(self):
        failed = set(self._failed_watch)
        self._sync_watches()
        for path in failed:
            self._pending.add(path if path in self.directories else os.path.dirname(path)
                              if path in self._extra_cache else path)
        if self._pending:
            self._launch_pending()

    def _persist(self):
        try:
            self._save_callback()
        except Exception as exc:
            self._report_error("无法保存分类设置：" + str(exc))

    def _report_error(self, message):
        if message not in self._reported_errors:
            self._reported_errors.add(message)
            self.error.emit(message)

    def _set_busy(self, value):
        if self._busy != value:
            self._busy = value
            self.busyChanged.emit(value)
