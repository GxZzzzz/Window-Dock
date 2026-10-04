// 只连接当前进程、当前线程拥有的 Shell 视图；跨进程连接由 bridge.cpp 建立。
// 保留 Explorer 原有绘制、鼠标和菜单，只修改视图项目，不操作磁盘文件。
#define UNICODE
#define _UNICODE
#define NOMINMAX
#include <windows.h>
#include <commctrl.h>
#include <shlobj.h>
#include <wrl/client.h>
#include <memory>
#include <map>
#include <set>
#include <string>
#include <cstdint>
#include <vector>
#include <algorithm>

using Microsoft::WRL::ComPtr;
struct FreePidl {
    using pointer = PIDLIST_RELATIVE;
    void operator()(pointer p) const { CoTaskMemFree(p); }
};
using Pidl = std::unique_ptr<ITEMIDLIST, FreePidl>;
constexpr auto RecycleKey = L"::{645FF040-5081-101B-9F08-00AA002F954E}";
struct PathLess {
    bool operator()(const std::wstring& a, const std::wstring& b) const {
        return CompareStringOrdinal(a.c_str(), -1, b.c_str(), -1, TRUE) == CSTR_LESS_THAN;
    }
};
struct HiddenItem { Pidl pidl; POINT position; };
struct Filter;
struct FilterCallback : IShellFolderViewCB {
    LONG references = 1;
    Filter* owner;
    explicit FilterCallback(Filter* f) : owner(f) {}
    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID iid, void** out) override;
    ULONG STDMETHODCALLTYPE AddRef() override { return InterlockedIncrement(&references); }
    ULONG STDMETHODCALLTYPE Release() override {
        auto remaining = InterlockedDecrement(&references);
        if (!remaining) delete this;
        return remaining;
    }
    HRESULT STDMETHODCALLTYPE MessageSFVCB(UINT message, WPARAM wp, LPARAM lp) override;
};
struct Filter {
    ComPtr<IFolderView2> view;
    ComPtr<IShellFolderView> legacy;
    ComPtr<IShellFolderViewCB> previous;
    ComPtr<FilterCallback> callback;
    Pidl root;
    Pidl recycle;
    HWND window = nullptr;
    HWND list = nullptr;
    DWORD thread = 0;
    UINT message = 0;
    bool queued = false;
    bool timer = false;
    bool busy = false;
    unsigned callbackDepth = 0;
    HRESULT error = S_OK;
    HWND errorWindow = nullptr;
    UINT errorMessage = 0;
    uint64_t passes = 0, events = 0, removed = 0, restored = 0;
    std::set<std::wstring, PathLess> wanted;
    std::map<std::wstring, HiddenItem, PathLess> hidden;

    std::wstring Path(PCUITEMID_CHILD child) {
        Pidl absolute(ILCombine(root.get(), child));
        if (absolute && recycle && ILIsEqual(absolute.get(), recycle.get())) return RecycleKey;
        wchar_t path[32768];
        if (!absolute || !SHGetPathFromIDListEx(absolute.get(), path, ARRAYSIZE(path), 0))
            return {};
        return path;
    }

    HRESULT Apply() {
        if (busy || !IsWindow(window)) return S_FALSE;
        busy = true;
        struct Finish { Filter* f; ~Finish() { f->view->SetRedraw(TRUE); f->busy = false; } } finish{this};
        view->SetRedraw(FALSE);
        ++passes;
        std::vector<POINT> occupied;
        int visibleCount = 0;
        bool restoring = std::any_of(hidden.begin(), hidden.end(), [&](const auto& entry) {
            return !wanted.count(entry.first);
        });
        HRESULT read = restoring ? view->ItemCount(SVGIO_ALLVIEW, &visibleCount) : S_OK;
        if (FAILED(read)) return error = read;
        POINT spacing{80, 100};
        if (restoring) view->GetSpacing(&spacing);
        for (int i = 0; i < visibleCount; ++i) {
            PITEMID_CHILD raw = nullptr;
            if (FAILED(view->Item(i, &raw))) continue;
            Pidl child(raw);
            POINT p{};
            if (SUCCEEDED(view->GetItemPosition(child.get(), &p))) occupied.push_back(p);
        }
        RECT bounds{};
        GetClientRect(list, &bounds);
        auto freePosition = [&](POINT p) {
            // 多个新文件可能先后占用相同空位；恢复时避开仍显示的图标与本批已恢复项。
            auto collides = [&](POINT candidate) {
                return std::any_of(occupied.begin(), occupied.end(), [&](POINT other) {
                    return abs(candidate.x - other.x) < spacing.x && abs(candidate.y - other.y) < spacing.y;
                });
            };
            LONG origin = p.x % spacing.x;
            while (collides(p)) {
                p.x += spacing.x;
                if (p.x + spacing.x > bounds.right) { p.x = origin; p.y += spacing.y; }
            }
            occupied.push_back(p);
            return p;
        };
        // 只还原刚取消收纳的项目；已经删除或改名的文件不会重新显示成幽灵图标。
        for (auto it = hidden.begin(); it != hidden.end();) {
            if (wanted.count(it->first)) { ++it; continue; }
            if (it->first == RecycleKey || GetFileAttributesW(it->first.c_str()) != INVALID_FILE_ATTRIBUTES) {
                UINT index = 0;
                HRESULT hr = legacy->AddObject(it->second.pidl.get(), &index);
                if (FAILED(hr)) return error = hr;
                PCUITEMID_CHILD id = it->second.pidl.get();
                POINT restoredPosition = freePosition(it->second.position);
                hr = view->SelectAndPositionItems(1, &id, &restoredPosition,
                    SVSI_POSITIONITEM | SVSI_NOSTATECHANGE | SVSI_NOTAKEFOCUS);
                if (FAILED(hr)) return error = hr;
                ++restored;
            }
            it = hidden.erase(it);
        }
        int count = 0;
        HRESULT hr = view->ItemCount(SVGIO_ALLVIEW, &count);
        if (FAILED(hr)) return error = hr;
        // 逆序删除视图项目，避免删除导致后续索引改变；匹配依据始终是完整路径。
        for (int index = count - 1; index >= 0; --index) {
            PITEMID_CHILD raw = nullptr;
            hr = view->Item(index, &raw);
            if (FAILED(hr)) return error = hr;
            Pidl child(raw);
            auto path = Path(child.get());
            if (!wanted.count(path)) continue;
            POINT position{};
            hr = view->GetItemPosition(child.get(), &position);
            if (FAILED(hr)) return error = hr;
            auto found = hidden.find(path);
            if (found == hidden.end()) {
                Pidl saved(ILClone(child.get()));
                if (!saved) return error = E_OUTOFMEMORY;
                hidden.emplace(path, HiddenItem{std::move(saved), position});
            }
            UINT removedIndex = 0;
            hr = legacy->RemoveObject(child.get(), &removedIndex);
            if (FAILED(hr)) return error = hr;
            ++removed;
        }
        return error = S_OK;
    }

    void Schedule(bool afterFileChange = false) {
        if (busy || wanted.empty()) return;
        if (afterFileChange) {
            // FSNOTIFY 发生在模型更新之前；仅在事件后延迟一次，合并同一批变化。
            timer = SetTimer(window, reinterpret_cast<UINT_PTR>(this), 60, nullptr) != 0;
            return;
        }
        if (queued) return;
        queued = PostMessageW(window, message, reinterpret_cast<WPARAM>(this), 0) != FALSE;
    }

    static LRESULT CALLBACK WindowProc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp,
                                        UINT_PTR id, DWORD_PTR data) {
        auto f = reinterpret_cast<Filter*>(data);
        if (msg == WM_TIMER && wp == reinterpret_cast<UINT_PTR>(f)) {
            KillTimer(hwnd, wp);
            f->timer = false;
            try { f->Apply(); }
            catch (...) { f->error = E_FAIL; }
            if (FAILED(f->error) && f->errorWindow)
                PostMessageW(f->errorWindow, f->errorMessage, 0, f->error);
            return 0;
        }
        if (msg == f->message && wp == reinterpret_cast<WPARAM>(f)) {
            f->queued = false;
            try { f->Apply(); }
            catch (...) { f->error = E_FAIL; }
            if (FAILED(f->error) && f->errorWindow)
                PostMessageW(f->errorWindow, f->errorMessage, 0, f->error);
            return 0;
        }
        if (msg == WM_NCDESTROY) {
            RemoveWindowSubclass(hwnd, WindowProc, id);
            f->window = nullptr;
            f->queued = false;
            f->timer = false;
        }
        return DefSubclassProc(hwnd, msg, wp, lp);
    }
};

HRESULT FilterCallback::QueryInterface(REFIID iid, void** out) {
    if (!out) return E_POINTER;
    *out = nullptr;
    if (iid == IID_IUnknown || iid == __uuidof(IShellFolderViewCB)) {
        *out = static_cast<IShellFolderViewCB*>(this);
        AddRef();
        return S_OK;
    }
    // 保留原宿主可能提供的扩展接口，避免只转发回调方法却丢失宿主能力。
    return owner && owner->previous ? owner->previous->QueryInterface(iid, out) : E_NOINTERFACE;
}

HRESULT FilterCallback::MessageSFVCB(UINT message, WPARAM wp, LPARAM lp) {
    if (!owner) return E_NOTIMPL;
    // Shell 回调可能泵送窗口消息；在回调栈退出前不允许释放过滤上下文。
    ++owner->callbackDepth;
    struct Leave { Filter* f; ~Leave() { --f->callbackDepth; } } leave{owner};
    HRESULT result = owner->previous ? owner->previous->MessageSFVCB(message, wp, lp) : E_NOTIMPL;
    // 保留宿主回调的返回值与行为；只在枚举完成、文件变化后合并处理。
    // Shell 可能绕过 ListView 窗口消息直接更新模型，必须监听 Shell 自身通知。
    if (message == SFVM_BACKGROUNDENUMDONE || message == SFVM_FSNOTIFY) {
        ++owner->events;
        owner->Schedule(message == SFVM_FSNOTIFY);
    }
    return result;
}

#define API extern "C" __declspec(dllexport) HRESULT WINAPI
API ObserveFailure(void* context, HWND window, UINT message) {
    auto f = static_cast<Filter*>(context);
    if (!f) return E_POINTER;
    if (f->thread != GetCurrentThreadId()) return RPC_E_WRONG_THREAD;
    f->errorWindow = window;
    f->errorMessage = message;
    return S_OK;
}

API Attach(IShellView* shellView, PCIDLIST_ABSOLUTE root, void** result) {
    if (!shellView || !root || !result) return E_POINTER;
    *result = nullptr;
    try {
        auto f = std::make_unique<Filter>();
        HRESULT hr = shellView->GetWindow(&f->window);
        if (FAILED(hr)) return hr;
        DWORD owner = 0;
        f->thread = GetWindowThreadProcessId(f->window, &owner);
        if (owner != GetCurrentProcessId() || f->thread != GetCurrentThreadId()) return E_ACCESSDENIED;
        hr = shellView->QueryInterface(IID_PPV_ARGS(&f->view));
        if (FAILED(hr)) return hr;
        hr = shellView->QueryInterface(IID_PPV_ARGS(&f->legacy));
        if (FAILED(hr)) return hr;
        f->root.reset(ILCloneFull(root));
        if (!f->root) return E_OUTOFMEMORY;
        // 回收站是 Shell 命名空间对象；只缓存这个已知对象，不解析任意虚拟路径。
        PIDLIST_ABSOLUTE recycle = nullptr;
        hr = SHGetKnownFolderIDList(FOLDERID_RecycleBinFolder, 0, nullptr, &recycle);
        if (FAILED(hr)) return hr;
        f->recycle.reset(recycle);
        f->list = FindWindowExW(f->window, nullptr, WC_LISTVIEW, nullptr);
        // DirectUI 等其他视图类型需要单独验证，不能套用此 ListView 实验。
        if (!f->list) return E_NOINTERFACE;
        f->callback.Attach(new FilterCallback(f.get()));
        f->message = RegisterWindowMessageW(L"WindowDock.NativeFilter.Lab.Apply.v1");
        if (!f->message || !SetWindowSubclass(f->window, Filter::WindowProc,
            reinterpret_cast<UINT_PTR>(f.get()), reinterpret_cast<DWORD_PTR>(f.get())))
            return E_FAIL; // SetWindowSubclass 不保证设置 LastError，不能把失败误报为成功。
        hr = f->legacy->SetCallback(f->callback.Get(), &f->previous);
        if (FAILED(hr)) {
            RemoveWindowSubclass(f->window, Filter::WindowProc, reinterpret_cast<UINT_PTR>(f.get()));
            return hr;
        }
        *result = f.release();
        return S_OK;
    } catch (...) { return E_FAIL; }
}

API SetPaths(void* context, const wchar_t* const* paths, UINT count) {
    auto f = static_cast<Filter*>(context);
    if (!f) return E_POINTER;
    if (f->thread != GetCurrentThreadId()) return RPC_E_WRONG_THREAD;
    try {
        std::set<std::wstring, PathLess> next;
        for (UINT i = 0; i < count; ++i) next.insert(paths[i]);
        f->wanted.swap(next);
        return f->Apply();
    } catch (...) { return E_FAIL; }
}

API GetStats(void* context, uint64_t* values) {
    auto f = static_cast<Filter*>(context);
    if (!f || !values) return E_POINTER;
    if (f->thread != GetCurrentThreadId()) return RPC_E_WRONG_THREAD;
    values[0] = f->passes; values[1] = f->events;
    values[2] = f->removed; values[3] = f->restored;
    values[4] = f->hidden.size(); values[5] = f->queued || f->timer;
    return f->error;
}

API Detach(void* context) {
    auto f = static_cast<Filter*>(context);
    if (!f) return E_POINTER;
    if (f->thread != GetCurrentThreadId()) return RPC_E_WRONG_THREAD;
    if (f->busy || f->callbackDepth) return E_PENDING;
    try {
        if (f->timer && f->window) KillTimer(f->window, reinterpret_cast<UINT_PTR>(f));
        f->timer = false;
        f->wanted.clear();
        HRESULT hr = f->Apply();
        if (FAILED(hr)) return hr; // 保留句柄，让宿主能报告并重试恢复。
        ComPtr<IShellFolderViewCB> replaced;
        hr = f->legacy->SetCallback(f->previous.Get(), &replaced);
        if (FAILED(hr)) return hr;
        f->callback->owner = nullptr;
        if (f->window) RemoveWindowSubclass(f->window, Filter::WindowProc, reinterpret_cast<UINT_PTR>(f));
        delete f;
        return S_OK;
    } catch (...) { return E_FAIL; }
}
