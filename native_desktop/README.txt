Window Dock 原生桌面组件

用途
desktop_manager.py 将共用分类结果传给 native_desktop_host.py。
连接进程通过本地管道接收路径，DLL 在 Explorer 现有桌面视图中收起或恢复项目。
不移动文件，不更改文件隐藏属性，不绘制替代桌面。
桌面图标、字体、右键菜单和拖放仍由 Explorer 处理。

构建
需要 Visual Studio 2022 Build Tools 的 C++ 桌面开发组件（MSVC x64 + Windows SDK）。
在仓库根目录执行：
powershell -NoProfile -ExecutionPolicy Bypass -File .\native_desktop\build.ps1

默认在本目录输出 WindowDockDesktop.dll，使用静态 C++ 运行库。
WindowDock.spec 会把 DLL 放到打包资源的 native_desktop 子目录。
不要提交 obj、lib、exp、dll 等本机构建产物。

职责
bridge.cpp：启动时用 WH_GETMESSAGE 线程钩子连接 Explorer 桌面线程，完成后解除启动钩子。
filter.cpp：使用原 IShellView / IShellFolderView 收纳和恢复项目，维护退出时的恢复流程。
recycle.cpp：在 Dock 后台 STA 使用 IFileOperation 回收项目，不在 Explorer 回调内操作文件。
PreDeleteItem 拒绝非回收操作，没有永久删除重试；清空回收站使用系统确认。

事件与生命周期
分类结果变化时更新；Shell 事件在短时间内合并，不进行高频扫描。
每次处理需要遍历桌面顶层视图，不代表逐个事件都能直接定位唯一项目。
正常断开、主进程或连接进程退出时尝试恢复桌面项目。
Explorer 退出通过内核事件感知；重连最多 20 次，间隔 500 ms，初次连接最多等待 8 秒。
失败时尝试恢复原生桌面并提示，不无限重试。

已验证与限制
已在 Windows 11 x64 的真实 Explorer 桌面完成连接、收纳、文件变化、
正常退出及连接进程意外退出后的恢复验证。
IShellFolderView 是旧接口，微软文档已标记不再可用，当前系统可获取并不代表跨版本保证。
完整 Explorer 重启、多显示器、运行中切换 DPI、多个桌面管理器共存尚未完整验证。
旧实验与含本机路径的诊断记录不在公开仓库中。

接口资料
https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setwindowshookexw
https://learn.microsoft.com/en-us/windows/win32/api/shlobj_core/nn-shlobj_core-ishellfolderview
https://learn.microsoft.com/en-us/windows/win32/api/shlobj_core/nf-shlobj_core-ishellfolderview-removeobject
https://learn.microsoft.com/en-us/windows/win32/api/shobjidl_core/nf-shobjidl_core-ifileoperation-setoperationflags
https://learn.microsoft.com/en-us/windows/win32/api/shobjidl_core/nf-shobjidl_core-ifileoperationprogresssink-predeleteitem
https://learn.microsoft.com/en-us/windows/win32/api/shlobj_core/nf-shlobj_core-shchangenotifyregister
