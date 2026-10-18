"""Windows public window/hotkey APIs only. No game memory or input injection."""
import ctypes
from ctypes import wintypes
import os
from pathlib import PureWindowsPath

from PySide6.QtCore import QAbstractNativeEventFilter, QTimer
from PySide6.QtWidgets import QApplication


def dota_foreground():
    if os.name != "nt":
        return False
    user = ctypes.WinDLL("user32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    user.GetForegroundWindow.restype = wintypes.HWND
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    hwnd = user.GetForegroundWindow()
    process_id = wintypes.DWORD()
    user.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
    handle = kernel.OpenProcess(0x1000, False, process_id.value)  # QUERY_LIMITED_INFORMATION only.
    if not handle:
        return False
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(buffer))
        if not kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return False
        return PureWindowsPath(buffer.value).name.casefold() == "dota2.exe"
    finally:
        kernel.CloseHandle(handle)


def clipboard_sequence():
    if os.name != "nt":
        return -1
    user = ctypes.WinDLL("user32")
    user.GetClipboardSequenceNumber.restype = wintypes.DWORD
    return user.GetClipboardSequenceNumber()


class Hotkeys(QAbstractNativeEventFilter):
    def __init__(self, toggle, lock, outgoing, outgoing_enabled=False):
        super().__init__()
        self.callbacks = {0x4011: toggle, 0x4012: lock, 0x4013: outgoing}
        self.registered, self.failures = [], []
        if os.name != "nt":
            self.failures.append("Global shortcuts require Windows")
            return
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.user.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
        self.user.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        for ident, key in ((0x4011, "T"), (0x4012, "L"), (0x4013, "Y")):
            if ident == 0x4013 and not outgoing_enabled:
                continue
            if self.user.RegisterHotKey(None, ident, 0x4000 | 0x0001 | 0x0002, ord(key)):
                self.registered.append(ident)
            else:
                self.failures.append("Ctrl+Alt+" + key + " unavailable (in use)")
        QApplication.instance().installNativeEventFilter(self)

    def set_outgoing_enabled(self, enabled):
        if os.name != "nt":
            return
        ident = 0x4013
        if enabled and ident not in self.registered:
            if self.user.RegisterHotKey(None, ident, 0x4000 | 0x0001 | 0x0002, ord("Y")):
                self.registered.append(ident)
            else:
                self.failures.append("Ctrl+Alt+Y unavailable (in use)")
        elif not enabled and ident in self.registered:
            self.user.UnregisterHotKey(None, ident)
            self.registered.remove(ident)

    def nativeEventFilter(self, event_type, message):
        if bytes(event_type) in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == 0x0312 and msg.wParam in self.registered:  # WM_HOTKEY
                QTimer.singleShot(0, self.callbacks[msg.wParam])
                return True, 0
        return False, 0

    def close(self):
        if os.name == "nt":
            for ident in self.registered:
                self.user.UnregisterHotKey(None, ident)
            self.registered.clear()
            QApplication.instance().removeNativeEventFilter(self)
