# 来源与第三方许可

## 上游项目

Window Dock 基于 [WKaleXD/iOS-style-Dock](https://github.com/WKaleXD/iOS-style-Dock)，保留原 Git 历史与 MIT 版权声明：Copyright (c) 2026 WWQ。

原项目源码、程序图标及上游截图沿用其许可。新增项目代码沿用根目录 [LICENSE](LICENSE)，不改变依赖库的许可证。

## 运行与构建依赖

| 组件 | 用途 | 许可资料 |
| --- | --- | --- |
| Python | 运行时 | [Python License](https://docs.python.org/3/license.html) |
| PyQt5 | Qt 的 Python 绑定 | GPL v3 / 商业许可，参见 [Riverbank 许可说明](https://www.riverbankcomputing.com/software/pyqt/intro) |
| Qt 5 | 窗口、绘制与事件循环 | 各模块许可不同，参见 [Qt 许可说明](https://doc.qt.io/qt-5/licensing.html) |
| PyInstaller | 构建工具 | GPL 及打包分发例外，参见 [PyInstaller 许可](https://pyinstaller.org/en/stable/license.html) |
| MSVC / Windows SDK | 原生 DLL 构建 | 适用 Microsoft 随工具提供的条款 |

MIT 是本项目代码的许可，不代表包含 PyQt5 / Qt 的整个二进制包都只有 MIT 义务。分发构建产物时须同时遵守实际安装的第三方依赖许可，并保留随包提供的许可证文件。

## 美术资源

正式分类与系统入口图标为本项目 AI 辅助生成并整理的静态 PNG，作为项目资源按根目录许可证提供，来源说明见 [docs/ICONS.md](docs/ICONS.md)。

运行时从 Windows 读取的第三方应用图标属于各自权利人，不作为本项目自有资源发布。项目与 Apple、Microsoft 及各应用厂商没有官方隶属或背书关系。
