"""Safe, focus-verified keyboard input injection for Steam Epyx Rogue 1.49 (Section 6)."""

from __future__ import annotations

import sys
import time
from typing import Any

if sys.platform == "win32":
    import ctypes
    XK = None  # type: ignore
    X = None  # type: ignore
    xtest = None  # type: ignore
else:
    try:
        from Xlib import XK, X
        from Xlib.ext import xtest
    except ImportError:
        XK = None  # type: ignore
        X = None  # type: ignore
        xtest = None  # type: ignore

from rogue_agent.features.steam_backend.window_manager import X11WindowManager

_CHAR_TO_KEYSYM_NAME: dict[str, tuple[str, bool]] = {
    " ": ("space", False),
    ".": ("period", False),
    ",": ("comma", False),
    ">": ("period", True),
    "<": ("comma", True),
    "?": ("slash", True),
    "/": ("slash", False),
    "-": ("minus", False),
    "=": ("equal", False),
    "+": ("equal", True),
    "*": ("8", True),
    "_": ("minus", True),
}


class PosixX11KeyInjector:
    """Injects keystrokes only when the verified Steam Rogue window holds input focus."""

    def __init__(self, window_manager: X11WindowManager) -> None:
        self.window_manager = window_manager

    def _resolve_keycode_and_shift(self, dpy: Any, token: str) -> tuple[int, bool]:
        if token in _CHAR_TO_KEYSYM_NAME:
            sym_name, needs_shift = _CHAR_TO_KEYSYM_NAME[token]
            keysym = XK.string_to_keysym(sym_name)
        elif len(token) == 1 and token.isalpha():
            needs_shift = token.isupper()
            keysym = XK.string_to_keysym(token.lower())
        else:
            needs_shift = False
            keysym = XK.string_to_keysym(token)

        if keysym == 0:
            raise ValueError(f"Cannot resolve X11 keysym for token {token!r}")

        keycode = dpy.keysym_to_keycode(keysym)
        if keycode == 0:
            raise ValueError(f"Cannot resolve X11 keycode for token {token!r} (keysym={keysym})")

        return int(keycode), needs_shift

    def send_key_sequence(
        self,
        window_id: int,
        keys: list[str],
        hold_seconds: float = 0.04,
        inter_key_delay: float = 0.06,
    ) -> None:
        """Verify window focus before each key and inject press/release safely."""
        dpy = self.window_manager._get_display()
        shift_keycode = int(dpy.keysym_to_keycode(XK.string_to_keysym("Shift_L")))

        for idx, token in enumerate(keys):
            # Critical safety invariant: verify target window identity and focus before EVERY key
            self.window_manager.ensure_verified_focus(window_id)
            keycode, needs_shift = self._resolve_keycode_and_shift(dpy, token)

            try:
                if needs_shift and shift_keycode:
                    xtest.fake_input(dpy, X.KeyPress, shift_keycode)
                    dpy.sync()
                    time.sleep(0.01)

                xtest.fake_input(dpy, X.KeyPress, keycode)
                dpy.sync()
                time.sleep(hold_seconds)
            finally:
                # Guaranteed key release so keys never remain stuck
                xtest.fake_input(dpy, X.KeyRelease, keycode)
                if needs_shift and shift_keycode:
                    xtest.fake_input(dpy, X.KeyRelease, shift_keycode)
                dpy.sync()

            if idx + 1 < len(keys):
                time.sleep(inter_key_delay)

    def send_alt_enter(self, window_id: int) -> None:
        """Toggle DOSBox out of fullscreen mode (Alt+Return) so windowed X11 focus is reliable."""
        dpy = self.window_manager._get_display()
        self.window_manager.ensure_verified_focus(window_id)
        alt_kc = int(dpy.keysym_to_keycode(XK.string_to_keysym("Alt_L")))
        ret_kc = int(dpy.keysym_to_keycode(XK.string_to_keysym("Return")))
        try:
            xtest.fake_input(dpy, X.KeyPress, alt_kc)
            dpy.sync()
            time.sleep(0.02)
            xtest.fake_input(dpy, X.KeyPress, ret_kc)
            dpy.sync()
            time.sleep(0.05)
        finally:
            xtest.fake_input(dpy, X.KeyRelease, ret_kc)
            xtest.fake_input(dpy, X.KeyRelease, alt_kc)
            dpy.sync()


class Win32KeyInjector:
    """Injects keystrokes to the verified Steam Rogue DOSBox window on Windows."""

    _WM_KEYDOWN = 0x0100
    _WM_KEYUP = 0x0101
    _VK_SHIFT = 0x10
    _VK_MENU = 0x12
    _VK_RETURN = 0x0D
    _SHIFT_SCAN = 0x2A
    _KEYEVENTF_EXTENDEDKEY = 0x0001
    _KEYEVENTF_KEYUP = 0x0002

    _SPECIAL_KEYS: dict[str, tuple[int, bool]] = {
        "Up": (0x26, True),
        "Down": (0x28, True),
        "Left": (0x25, True),
        "Right": (0x27, True),
        "Home": (0x24, True),
        "Prior": (0x21, True),  # PageUp
        "End": (0x23, True),
        "Next": (0x22, True),   # PageDown
        "space": (0x20, False),
        "Return": (0x0D, False),
        "Escape": (0x1B, False),
    }

    def __init__(self, window_manager: Any) -> None:
        self.window_manager = window_manager

    def send_key_sequence(
        self,
        window_id: int,
        keys: list[str],
        hold_seconds: float = 0.04,
        inter_key_delay: float = 0.06,
    ) -> None:
        user32 = ctypes.windll.user32

        for idx, token in enumerate(keys):
            # Verify window identity, visibility, and raise/focus DOSBox before every key
            self.window_manager.ensure_verified_focus(window_id)

            if token in self._SPECIAL_KEYS:
                vk, is_extended = self._SPECIAL_KEYS[token]
                needs_shift = False
            elif len(token) == 1:
                vk_scan = user32.VkKeyScanW(ord(token))
                vk = vk_scan & 0xFF
                needs_shift = bool(vk_scan & 0x0100)
                is_extended = False
            else:
                vk_scan = user32.VkKeyScanW(ord(token[0]))
                vk = vk_scan & 0xFF
                needs_shift = bool(vk_scan & 0x0100)
                is_extended = False

            scan = user32.MapVirtualKeyW(vk, 0)
            ext_flag = (1 << 24) if is_extended else 0
            flags_down = self._KEYEVENTF_EXTENDEDKEY if is_extended else 0
            flags_up = flags_down | self._KEYEVENTF_KEYUP
            lparam_down = 1 | (scan << 16) | ext_flag
            lparam_up = 1 | (scan << 16) | ext_flag | (1 << 30) | (1 << 31)

            try:
                if needs_shift:
                    user32.keybd_event(self._VK_SHIFT, self._SHIFT_SCAN, 0, 0)
                    user32.PostMessageW(
                        window_id,
                        self._WM_KEYDOWN,
                        self._VK_SHIFT,
                        1 | (self._SHIFT_SCAN << 16),
                    )
                    time.sleep(0.01)

                user32.keybd_event(vk, scan, flags_down, 0)
                user32.PostMessageW(window_id, self._WM_KEYDOWN, vk, lparam_down)
                time.sleep(hold_seconds)
            finally:
                user32.keybd_event(vk, scan, flags_up, 0)
                user32.PostMessageW(window_id, self._WM_KEYUP, vk, lparam_up)

                if needs_shift:
                    time.sleep(0.01)
                    user32.keybd_event(
                        self._VK_SHIFT,
                        self._SHIFT_SCAN,
                        self._KEYEVENTF_KEYUP,
                        0,
                    )
                    user32.PostMessageW(
                        window_id,
                        self._WM_KEYUP,
                        self._VK_SHIFT,
                        1 | (self._SHIFT_SCAN << 16) | (1 << 30) | (1 << 31),
                    )

            if idx + 1 < len(keys):
                time.sleep(inter_key_delay)

    def send_alt_enter(self, window_id: int) -> None:
        self.window_manager.ensure_verified_focus(window_id)
        user32 = ctypes.windll.user32
        try:
            user32.keybd_event(self._VK_MENU, 0x38, 0, 0)
            user32.keybd_event(self._VK_RETURN, 0x1C, 0, 0)
            user32.PostMessageW(window_id, self._WM_KEYDOWN, self._VK_MENU, 1 | (0x38 << 16))
            user32.PostMessageW(window_id, self._WM_KEYDOWN, self._VK_RETURN, 1 | (0x1C << 16))
            time.sleep(0.05)
        finally:
            user32.keybd_event(self._VK_RETURN, 0x1C, self._KEYEVENTF_KEYUP, 0)
            user32.keybd_event(self._VK_MENU, 0x38, self._KEYEVENTF_KEYUP, 0)
            user32.PostMessageW(
                window_id,
                self._WM_KEYUP,
                self._VK_RETURN,
                1 | (0x1C << 16) | (1 << 30) | (1 << 31),
            )
            user32.PostMessageW(
                window_id,
                self._WM_KEYUP,
                self._VK_MENU,
                1 | (0x38 << 16) | (1 << 30) | (1 << 31),
            )


X11KeyInjector = Win32KeyInjector if sys.platform == "win32" else PosixX11KeyInjector
