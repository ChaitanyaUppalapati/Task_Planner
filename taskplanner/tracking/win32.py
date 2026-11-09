"""Win32 foreground-window, idle and lock detection via ctypes (no native deps)."""

from __future__ import annotations

import ctypes
import os
import sys
import time

from taskplanner.core.models import ActivitySample

if sys.platform == "win32":
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    DESKTOP_SWITCHDESKTOP = 0x0100

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetLastInputInfo.argtypes = [ctypes.POINTER(LASTINPUTINFO)]
    user32.OpenInputDesktop.restype = wintypes.HANDLE
    user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    user32.CloseDesktop.argtypes = [wintypes.HANDLE]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)
    ]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.GetTickCount.restype = wintypes.DWORD


class Win32Sampler:
    """Reads the foreground window's process/title, input idle time and lock state."""

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise RuntimeError("Win32Sampler is only available on Windows")
        self._pid_cache: dict[int, str] = {}

    def idle_seconds(self) -> float:
        info = LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(LASTINPUTINFO)
        if not user32.GetLastInputInfo(ctypes.byref(info)):
            return 0.0
        # Both are 32-bit tick counts; handle wrap-around after ~49.7 days.
        elapsed_ms = (kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF
        return elapsed_ms / 1000.0

    def is_locked(self) -> bool:
        handle = user32.OpenInputDesktop(0, False, DESKTOP_SWITCHDESKTOP)
        if not handle:
            return True  # secure desktop (lock screen / UAC) is active
        user32.CloseDesktop(handle)
        return False

    def _process_name(self, pid: int) -> str:
        cached = self._pid_cache.get(pid)
        if cached:
            return cached
        name = ""
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if handle:
            try:
                size = wintypes.DWORD(1024)
                buf = ctypes.create_unicode_buffer(size.value)
                if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                    name = os.path.basename(buf.value)
            finally:
                kernel32.CloseHandle(handle)
        if len(self._pid_cache) > 512:
            self._pid_cache.clear()
        if name:
            self._pid_cache[pid] = name
        return name

    def sample(self) -> ActivitySample:
        now = time.time()
        locked = self.is_locked()
        hwnd = user32.GetForegroundWindow()
        title = ""
        process = ""
        if hwnd and not locked:
            length = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            process = self._process_name(pid.value)
        return ActivitySample(
            timestamp=now,
            process=process.lower(),
            title=title,
            idle_seconds=self.idle_seconds(),
            locked=locked,
        )
