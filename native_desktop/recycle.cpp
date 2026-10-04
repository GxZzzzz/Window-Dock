// 回收操作在 Dock 的后台 STA 中执行，与 Explorer 视图过滤完全分离。
#define UNICODE
#define _UNICODE
#include <windows.h>
#include <shlobj.h>
#include <wrl/client.h>
#include <string>

using Microsoft::WRL::ComPtr;

struct RecycleSink final : IFileOperationProgressSink {
    LONG references = 1;
    HRESULT failure = S_OK;
    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID iid, void** out) override {
        if (!out) return E_POINTER;
        *out = nullptr;
        if (iid != IID_IUnknown && iid != IID_IFileOperationProgressSink) return E_NOINTERFACE;
        *out = static_cast<IFileOperationProgressSink*>(this);
        AddRef();
        return S_OK;
    }
    ULONG STDMETHODCALLTYPE AddRef() override { return InterlockedIncrement(&references); }
    ULONG STDMETHODCALLTYPE Release() override {
        auto n = InterlockedDecrement(&references);
        if (!n) delete this;
        return n;
    }
    HRESULT STDMETHODCALLTYPE StartOperations() override { return S_OK; }
    HRESULT STDMETHODCALLTYPE FinishOperations(HRESULT) override { return S_OK; }
    HRESULT STDMETHODCALLTYPE PreRenameItem(DWORD, IShellItem*, LPCWSTR) override { return S_OK; }
    HRESULT STDMETHODCALLTYPE PostRenameItem(DWORD, IShellItem*, LPCWSTR, HRESULT, IShellItem*) override { return S_OK; }
    HRESULT STDMETHODCALLTYPE PreMoveItem(DWORD, IShellItem*, IShellItem*, LPCWSTR) override { return S_OK; }
    HRESULT STDMETHODCALLTYPE PostMoveItem(DWORD, IShellItem*, IShellItem*, LPCWSTR, HRESULT, IShellItem*) override { return S_OK; }
    HRESULT STDMETHODCALLTYPE PreCopyItem(DWORD, IShellItem*, IShellItem*, LPCWSTR) override { return S_OK; }
    HRESULT STDMETHODCALLTYPE PostCopyItem(DWORD, IShellItem*, IShellItem*, LPCWSTR, HRESULT, IShellItem*) override { return S_OK; }
    HRESULT STDMETHODCALLTYPE PreDeleteItem(DWORD flags, IShellItem*) override {
        // 网络盘、回收站禁用等情形不得悄悄降级为永久删除。
        return (flags & TSF_DELETE_RECYCLE_IF_POSSIBLE) ? S_OK
            : (failure = HRESULT_FROM_WIN32(ERROR_NOT_SUPPORTED));
    }
    HRESULT STDMETHODCALLTYPE PostDeleteItem(DWORD, IShellItem*, HRESULT result, IShellItem*) override {
        if (FAILED(result)) failure = result;
        return S_OK;
    }
    HRESULT STDMETHODCALLTYPE PreNewItem(DWORD, IShellItem*, LPCWSTR) override { return S_OK; }
    HRESULT STDMETHODCALLTYPE PostNewItem(DWORD, IShellItem*, LPCWSTR, LPCWSTR, DWORD, HRESULT, IShellItem*) override { return S_OK; }
    HRESULT STDMETHODCALLTYPE UpdateProgress(UINT, UINT) override { return S_OK; }
    HRESULT STDMETHODCALLTYPE ResetTimer() override { return S_OK; }
    HRESULT STDMETHODCALLTYPE PauseTimer() override { return S_OK; }
    HRESULT STDMETHODCALLTYPE ResumeTimer() override { return S_OK; }
};

extern "C" __declspec(dllexport) HRESULT __stdcall RecyclePaths(HWND owner, const wchar_t* paths) {
    HRESULT initialized = CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
    if (FAILED(initialized)) return initialized;
    struct Apartment { ~Apartment() { CoUninitialize(); } } apartment;
    try {
        if (!paths || !*paths) return S_FALSE;
        ComPtr<IFileOperation> operation;
        HRESULT hr = CoCreateInstance(CLSID_FileOperation, nullptr, CLSCTX_INPROC_SERVER,
                                      IID_PPV_ARGS(&operation));
        if (FAILED(hr)) return hr;
        hr = operation->SetOwnerWindow(owner);
        if (FAILED(hr)) return hr;
        hr = operation->SetOperationFlags(FOFX_RECYCLEONDELETE | FOFX_ADDUNDORECORD |
            FOF_NO_CONNECTED_ELEMENTS | FOF_NOERRORUI | FOFX_EARLYFAILURE | FOF_SILENT);
        if (FAILED(hr)) return hr;
        ComPtr<RecycleSink> sink;
        sink.Attach(new RecycleSink());
        for (auto p = paths; *p; p += wcslen(p) + 1) {
            ComPtr<IShellItem> item;
            hr = SHCreateItemFromParsingName(p, nullptr, IID_PPV_ARGS(&item));
            if (FAILED(hr)) return hr;
            hr = operation->DeleteItem(item.Get(), sink.Get());
            if (FAILED(hr)) return hr;
        }
        hr = operation->PerformOperations();
        if (FAILED(sink->failure)) return sink->failure;
        if (FAILED(hr)) return hr;
        BOOL aborted = FALSE;
        hr = operation->GetAnyOperationsAborted(&aborted);
        return FAILED(hr) ? hr : aborted ? HRESULT_FROM_WIN32(ERROR_CANCELLED) : S_OK;
    } catch (...) { return E_FAIL; }
}
