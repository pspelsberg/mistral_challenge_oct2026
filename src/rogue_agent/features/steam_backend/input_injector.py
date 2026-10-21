"""Safe, focus-verified keyboard input injection for Steam Epyx Rogue 1.49 (Section 6)."""

from __future__ import annotations

import time
from typing import Any

from Xlib import XK, X
from Xlib.ext import xtest

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


class X11KeyInjector:
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
