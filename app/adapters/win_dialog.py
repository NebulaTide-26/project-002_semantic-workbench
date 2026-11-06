"""Windows 原生文件 / 文件夹选择器。

使用 IFileOpenDialog（Win11 现代原生外观）：
- 初始位置固定为「此电脑」
- 文件选择带 FOS_NODEREFERENCELINKS，保留 .lnk 快捷方式本身
- 文件夹选择使用 FOS_PICKFOLDERS，允许系统解析文件夹快捷方式
"""

from __future__ import annotations

import ctypes
import uuid
from ctypes import POINTER, byref, c_ulong, c_uint32, c_void_p, c_wchar_p
from ctypes import wintypes
from pathlib import Path


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_ulong),
        ("Data2", ctypes.c_ushort),
        ("Data3", ctypes.c_ushort),
        ("Data4", ctypes.c_ubyte * 8),
    ]


def _guid(text: str) -> GUID:
    value = uuid.UUID(text)
    return GUID(
        value.fields[0],
        value.fields[1],
        value.fields[2],
        (ctypes.c_ubyte * 8)(*value.bytes[8:]),
    )


CLSID_FileOpenDialog = _guid("{DC1C5A9C-E88A-4dde-A5A1-60F82A20AEF7}")
IID_IFileOpenDialog = _guid("{d57c7288-d4ad-4768-be02-9d969532d960}")
IID_IShellItem = _guid("{43826d1e-e718-42ee-bc55-a1e261c37bfe}")
FOLDERID_ComputerFolder = _guid("{0AC0837C-BBF8-452A-850D-79D08E667CA7}")

CLSCTX_INPROC_SERVER = 1
COINIT_APARTMENTTHREADED = 2

FOS_PICKFOLDERS = 0x00000020
FOS_FORCEFILESYSTEM = 0x00000040
FOS_FILEMUSTEXIST = 0x00001000
FOS_PATHMUSTEXIST = 0x00000800
FOS_NODEREFERENCELINKS = 0x00100000

SIGDN_FILESYSPATH = 0x80058000
ERROR_CANCELLED_HRESULT = 0x800704C7
RPC_E_CHANGED_MODE = 0x80010106


class COMDLG_FILTERSPEC(ctypes.Structure):
    _fields_ = [
        ("pszName", wintypes.LPCWSTR),
        ("pszSpec", wintypes.LPCWSTR),
    ]


ole32 = ctypes.windll.ole32
shell32 = ctypes.windll.shell32

ole32.CoInitializeEx.argtypes = [c_void_p, wintypes.DWORD]
ole32.CoInitializeEx.restype = ctypes.c_long
ole32.CoCreateInstance.argtypes = [
    POINTER(GUID),
    c_void_p,
    wintypes.DWORD,
    POINTER(GUID),
    POINTER(c_void_p),
]
ole32.CoCreateInstance.restype = ctypes.c_long
ole32.CoTaskMemFree.argtypes = [c_void_p]
ole32.CoUninitialize.restype = None
shell32.SHGetKnownFolderItem.argtypes = [
    POINTER(GUID),
    wintypes.DWORD,
    c_void_p,
    POINTER(GUID),
    POINTER(c_void_p),
]
shell32.SHGetKnownFolderItem.restype = ctypes.c_long


def _hresult(value: int) -> int:
    return value & 0xFFFFFFFF


def _method(obj, index: int, restype, *argtypes):
    vtable = ctypes.cast(obj, POINTER(POINTER(c_void_p))).contents
    return ctypes.WINFUNCTYPE(restype, c_void_p, *argtypes)(vtable[index])


def _release(obj) -> None:
    release = _method(obj, 2, c_ulong)
    release(obj)


def _item_path(item) -> str:
    name = wintypes.LPWSTR()
    get_display = _method(
        item, 5, ctypes.c_long, c_uint32, POINTER(wintypes.LPWSTR)
    )
    hr = get_display(item, SIGDN_FILESYSPATH, byref(name))
    if _hresult(hr) != 0:
        raise OSError(f"读取选择结果失败：{_hresult(hr):#x}")
    value = name.value
    ole32.CoTaskMemFree(ctypes.cast(name, c_void_p))
    return value


def _open_dialog(
    parent_hwnd: int,
    title: str,
    *,
    folder: bool,
    file_types: list[tuple[str, str]] | None,
) -> Path | None:
    initialized = False
    init_code = _hresult(ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED))
    if init_code in (0, 1):
        initialized = True
    elif init_code != RPC_E_CHANGED_MODE:
        raise OSError(f"COM 初始化失败：{init_code:#x}")

    dialog = c_void_p()
    try:
        hr = ole32.CoCreateInstance(
            byref(CLSID_FileOpenDialog),
            None,
            CLSCTX_INPROC_SERVER,
            byref(IID_IFileOpenDialog),
            byref(dialog),
        )
        if _hresult(hr) != 0 or not dialog:
            raise OSError(f"创建文件对话框失败：{_hresult(hr):#x}")

        options = FOS_FORCEFILESYSTEM | FOS_PATHMUSTEXIST
        if folder:
            options |= FOS_PICKFOLDERS
        else:
            options |= FOS_FILEMUSTEXIST | FOS_NODEREFERENCELINKS

        set_options = _method(dialog, 9, ctypes.c_long, c_uint32)
        set_options(dialog, options)

        set_title = _method(dialog, 17, ctypes.c_long, c_wchar_p)
        set_title(dialog, title)

        if file_types:
            specs = (COMDLG_FILTERSPEC * len(file_types))(
                *[
                    COMDLG_FILTERSPEC(name, pattern)
                    for name, pattern in file_types
                ]
            )
            set_file_types = _method(
                dialog,
                4,
                ctypes.c_long,
                c_uint32,
                POINTER(COMDLG_FILTERSPEC),
            )
            set_file_types(dialog, len(file_types), specs)
            set_file_type_index = _method(
                dialog, 5, ctypes.c_long, c_uint32
            )
            set_file_type_index(dialog, 1)

        this_pc = c_void_p()
        hr = shell32.SHGetKnownFolderItem(
            byref(FOLDERID_ComputerFolder),
            0,
            None,
            byref(IID_IShellItem),
            byref(this_pc),
        )
        if _hresult(hr) == 0 and this_pc:
            set_folder = _method(dialog, 12, ctypes.c_long, c_void_p)
            set_folder(dialog, this_pc)
            _release(this_pc)

        show = _method(dialog, 3, ctypes.c_long, wintypes.HWND)
        hr = show(dialog, parent_hwnd)
        code = _hresult(hr)
        if code == ERROR_CANCELLED_HRESULT:
            return None
        if code != 0:
            raise OSError(f"打开文件对话框失败：{code:#x}")

        result = c_void_p()
        get_result = _method(dialog, 20, ctypes.c_long, POINTER(c_void_p))
        hr = get_result(dialog, byref(result))
        if _hresult(hr) != 0 or not result:
            raise OSError(f"读取选择结果失败：{_hresult(hr):#x}")

        try:
            return Path(_item_path(result))
        finally:
            _release(result)
    finally:
        if dialog:
            _release(dialog)
        if initialized:
            ole32.CoUninitialize()


def open_file_dialog(
    parent_hwnd: int,
    title: str = "选择文件",
    file_types: list[tuple[str, str]] | None = None,
) -> Path | None:
    return _open_dialog(
        parent_hwnd,
        title,
        folder=False,
        file_types=file_types,
    )


def open_folder_dialog(
    parent_hwnd: int, title: str = "选择文件夹"
) -> Path | None:
    return _open_dialog(
        parent_hwnd,
        title,
        folder=True,
        file_types=None,
    )
