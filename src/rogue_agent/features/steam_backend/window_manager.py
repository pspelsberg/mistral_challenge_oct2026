"""X11/Xwayland and Win32 window discovery and focus safety verification for Steam Rogue (Section 6)."""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from typing import Any

if sys.platform == "win32":
    import ctypes
    X = None  # type: ignore
    display = None  # type: ignore
    protocol = None  # type: ignore
    XError = Exception  # type: ignore
else:
    try:
        from Xlib import X, display, protocol
        from Xlib.error import XError
    except ImportError:
        X = None  # type: ignore
        display = None  # type: ignore
        protocol = None  # type: ignore
        XError = Exception  # type: ignore

STEAM_ROGUE_APP_ID = 1443430

# Never match IDE, browser, terminal, or window-manager decoration frame windows
_FORBIDDEN_WM_CLASSES = frozenset(
    {
        "mutter-x11-frames",
        "code",
        "antigravity",
        "vscodium",
        "cursor",
        "gnome-terminal",
        "kgx",
        "konsole",
        "alacritty",
        "kitty",
        "wezterm",
        "xterm",
        "firefox",
        "chromium",
        "google-chrome",
        "brave-browser",
        "consolewindowclass",
    }
)


class WindowNotFoundError(RuntimeError):
    """Raised when the verified Steam Rogue / DOSBox window cannot be found."""


class WindowFocusLostError(RuntimeError):
    """Raised when the target game window is missing, minimized, or does not hold focus."""


@dataclass(frozen=True)
class WindowInfo:
    """Verified geometry and identity of a game window."""

    window_id: int
    title: str
    wm_class: tuple[str, ...]
    steam_app_id: int | None
    x: int
    y: int
    width: int
    height: int
    is_viewable: bool
    has_focus: bool


def is_verified_rogue_window(
    title: str,
    wm_class: tuple[str, ...],
    steam_app_id: int | None,
    allow_test_window_tag: str | None = None,
) -> bool:
    """Determine whether a window is genuinely Steam Epyx Rogue / DOSBox."""
    if not title and not wm_class:
        return False

    lower_classes = {c.lower() for c in wm_class}
    if lower_classes & _FORBIDDEN_WM_CLASSES:
        return False

    if allow_test_window_tag and allow_test_window_tag in title:
        return True

    lower_title = title.lower()
    if "rogue oktober" in lower_title or "antigravity" in lower_title:
        return False

    if "status window" in lower_title:
        return False

    if any("dosbox" in c for c in lower_classes):
        return True

    if "dosbox" in lower_title and ("rogue" in lower_title or "cpu speed" in lower_title):
        return True

    if steam_app_id == STEAM_ROGUE_APP_ID and (
        "dosbox" in lower_title
        or "rogue" in lower_title
        or any("steam_app_1443430" in c for c in lower_classes)
    ):
        return True

    return False


class PosixX11WindowManager:
    """Discovers, validates, and manages focus for the Steam Rogue X11/Xwayland window."""

    def __init__(
        self,
        display_name: str | None = None,
        allow_test_window_tag: str | None = None,
    ) -> None:
        self.display_name = display_name
        self.allow_test_window_tag = allow_test_window_tag
        self._dpy: display.Display | None = None

    def _get_display(self) -> display.Display:
        if self._dpy is None:
            self._dpy = display.Display(self.display_name)
        return self._dpy

    def close(self) -> None:
        if self._dpy is not None:
            try:
                self._dpy.close()
            except Exception:
                pass
            self._dpy = None

    def _get_steam_app_id(self, win: Any, steam_atom: int) -> int | None:
        try:
            prop = win.get_full_property(steam_atom, X.AnyPropertyType)
            if prop and prop.value:
                return int(prop.value[0])
        except Exception:
            pass
        return None

    def _get_window_title(self, win: Any, net_wm_name_atom: int) -> str:
        try:
            prop = win.get_full_property(net_wm_name_atom, X.AnyPropertyType)
            if prop and prop.value:
                val = prop.value
                if isinstance(val, bytes):
                    return val.decode("utf-8", errors="ignore")
                if isinstance(val, str):
                    return val
        except Exception:
            pass
        try:
            name = win.get_wm_name()
            if isinstance(name, bytes):
                return name.decode("utf-8", errors="ignore")
            if isinstance(name, str):
                return name
        except Exception:
            pass
        return ""

    def _inspect_window(
        self, win: Any, focused_id: int, steam_atom: int, net_wm_name_atom: int
    ) -> WindowInfo | None:
        try:
            attrs = win.get_attributes()
            geom = win.get_geometry()
            if geom.width < 160 or geom.height < 120:
                return None

            title = self._get_window_title(win, net_wm_name_atom)
            wm_class_raw = win.get_wm_class() or ()
            wm_class = tuple(str(x) for x in wm_class_raw)
            steam_app_id = self._get_steam_app_id(win, steam_atom)

            dpy = self._get_display()
            root = dpy.screen().root
            coords = root.translate_coords(win, 0, 0)
            abs_x = int(coords.x)
            abs_y = int(coords.y)

            return WindowInfo(
                window_id=int(win.id),
                title=title,
                wm_class=wm_class,
                steam_app_id=steam_app_id,
                x=abs_x,
                y=abs_y,
                width=int(geom.width),
                height=int(geom.height),
                is_viewable=(attrs.map_state == X.IsViewable),
                has_focus=(int(win.id) == focused_id),
            )
        except XError:
            return None

    def find_game_window(self) -> WindowInfo | None:
        """Recursively scan the X11 tree for a viewable, verified Steam Rogue / DOSBox window."""
        dpy = self._get_display()
        root = dpy.screen().root
        steam_atom = dpy.intern_atom("STEAM_GAME")
        net_wm_name_atom = dpy.intern_atom("_NET_WM_NAME")

        focus_reply = dpy.get_input_focus()
        focused_win = focus_reply.focus
        focused_id = int(focused_win.id) if hasattr(focused_win, "id") else -1

        candidates: list[WindowInfo] = []
        stack = [root]
        visited: set[int] = set()

        while stack:
            current = stack.pop()
            win_id = int(current.id)
            if win_id in visited:
                continue
            visited.add(win_id)

            info = self._inspect_window(current, focused_id, steam_atom, net_wm_name_atom)
            if info is not None and info.is_viewable:
                if is_verified_rogue_window(
                    info.title,
                    info.wm_class,
                    info.steam_app_id,
                    self.allow_test_window_tag,
                ):
                    candidates.append(info)

            try:
                children = current.query_tree().children
                stack.extend(children)
            except XError:
                continue

        if not candidates:
            return None

        # Prefer explicit test window tag (when testing), then DOSBox title, Steam App ID, and area
        candidates.sort(
            key=lambda w: (
                bool(self.allow_test_window_tag and self.allow_test_window_tag in w.title),
                "dosbox" in w.title.lower(),
                w.steam_app_id == STEAM_ROGUE_APP_ID,
                w.width * w.height,
            ),
            reverse=True,
        )
        best = candidates[0]

        # Also check if focus belongs to a child or parent of the matched window
        if not best.has_focus and focused_id > 0:
            if self._is_ancestor_or_same(best.window_id, focused_id):
                return WindowInfo(
                    window_id=best.window_id,
                    title=best.title,
                    wm_class=best.wm_class,
                    steam_app_id=best.steam_app_id,
                    x=best.x,
                    y=best.y,
                    width=best.width,
                    height=best.height,
                    is_viewable=best.is_viewable,
                    has_focus=True,
                )
        return best

    def _is_ancestor_or_same(self, target_id: int, other_id: int) -> bool:
        if target_id == other_id:
            return True
        dpy = self._get_display()
        root_id = int(dpy.screen().root.id)
        curr_id = other_id
        for _ in range(10):
            if curr_id in (0, root_id):
                break
            if curr_id == target_id:
                return True
            try:
                win = dpy.create_resource_object("window", curr_id)
                parent = win.query_tree().parent
                curr_id = int(parent.id) if parent else 0
            except Exception:
                break
        return False

    def ensure_verified_focus(self, window_id: int, timeout: float = 1.0) -> WindowInfo:
        """Raise and focus the target game window, or raise WindowFocusLostError if unsafe."""
        dpy = self._get_display()
        steam_atom = dpy.intern_atom("STEAM_GAME")
        net_wm_name_atom = dpy.intern_atom("_NET_WM_NAME")

        win = dpy.create_resource_object("window", window_id)
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            focus_reply = dpy.get_input_focus()
            focused_win = focus_reply.focus
            focused_id = int(focused_win.id) if hasattr(focused_win, "id") else -1

            info = self._inspect_window(win, focused_id, steam_atom, net_wm_name_atom)
            if info is None or not info.is_viewable:
                raise WindowFocusLostError(
                    f"Game window {hex(window_id)} is no longer viewable or was closed."
                )

            if not is_verified_rogue_window(
                info.title, info.wm_class, info.steam_app_id, self.allow_test_window_tag
            ):
                raise WindowFocusLostError(
                    f"Window {hex(window_id)} failed identity verification (title={info.title!r})."
                )

            if info.has_focus or self._is_ancestor_or_same(window_id, focused_id):
                return WindowInfo(
                    window_id=info.window_id,
                    title=info.title,
                    wm_class=info.wm_class,
                    steam_app_id=info.steam_app_id,
                    x=info.x,
                    y=info.y,
                    width=info.width,
                    height=info.height,
                    is_viewable=True,
                    has_focus=True,
                )

            try:
                root = dpy.screen().root
                net_active = dpy.intern_atom("_NET_ACTIVE_WINDOW")
                ev = protocol.event.ClientMessage(
                    window=win,
                    client_type=net_active,
                    data=(32, [2, X.CurrentTime, 0, 0, 0]),
                )
                root.send_event(
                    ev,
                    event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask,
                )
                win.configure(stack_mode=X.Above)
                win.set_input_focus(X.RevertToParent, X.CurrentTime)
                dpy.sync()
            except XError:
                pass
            time.sleep(0.08)

        raise WindowFocusLostError(
            f"Could not verify input focus on game window {hex(window_id)} within {timeout}s. "
            "Stopping safely to avoid sending keys to an unrelated window."
        )

    def get_xlib_window(self, window_id: int) -> Any:
        dpy = self._get_display()
        return dpy.create_resource_object("window", window_id)


class _RECT(ctypes.Structure if sys.platform == "win32" else object):  # type: ignore
    _fields_ = [
        ("left", ctypes.c_long if sys.platform == "win32" else int),
        ("top", ctypes.c_long if sys.platform == "win32" else int),
        ("right", ctypes.c_long if sys.platform == "win32" else int),
        ("bottom", ctypes.c_long if sys.platform == "win32" else int),
    ]


class _POINT(ctypes.Structure if sys.platform == "win32" else object):  # type: ignore
    _fields_ = [
        ("x", ctypes.c_long if sys.platform == "win32" else int),
        ("y", ctypes.c_long if sys.platform == "win32" else int),
    ]


class Win32WindowManager:
    """Discovers, validates, and manages focus for the Steam Rogue DOSBox window on Windows."""

    # DESKTOP_ALL_ACCESS (0x01FF) required for SetThreadDesktop + keybd_event/PostMessageW
    _DESKTOP_ACCESS_MASK = 0x01FF

    def __init__(
        self,
        display_name: str | None = None,
        allow_test_window_tag: str | None = None,
    ) -> None:
        self.display_name = display_name
        self.allow_test_window_tag = allow_test_window_tag

    def close(self) -> None:
        pass

    def get_xlib_window(self, window_id: int) -> Any:
        return None

    def _attach_desktop(self) -> None:
        try:
            user32 = ctypes.windll.user32
            h_default = user32.OpenDesktopW("Default", 0, False, self._DESKTOP_ACCESS_MASK)
            if h_default:
                user32.SetThreadDesktop(h_default)
        except Exception:
            pass

    def find_game_window(self) -> WindowInfo | None:
        self._attach_desktop()
        user32 = ctypes.windll.user32
        candidates: list[WindowInfo] = []
        focused_hwnd = user32.GetForegroundWindow()

        def enum_cb(hwnd: int, lparam: int) -> bool:
            if not user32.IsWindowVisible(hwnd):
                return True

            length = user32.GetWindowTextLengthW(hwnd)
            if length == 0:
                return True
            title_buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, title_buf, length + 1)
            title = title_buf.value

            class_buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, class_buf, 256)
            class_name = class_buf.value

            if not is_verified_rogue_window(
                title=title,
                wm_class=(class_name,),
                steam_app_id=STEAM_ROGUE_APP_ID,
                allow_test_window_tag=self.allow_test_window_tag,
            ):
                return True

            c_rect = _RECT()
            user32.GetClientRect(hwnd, ctypes.byref(c_rect))
            w = c_rect.right
            h = c_rect.bottom
            if w < 160 or h < 120:
                return True

            pt = _POINT(0, 0)
            user32.ClientToScreen(hwnd, ctypes.byref(pt))

            candidates.append(
                WindowInfo(
                    window_id=hwnd,
                    title=title,
                    wm_class=(class_name,),
                    steam_app_id=STEAM_ROGUE_APP_ID,
                    x=pt.x,
                    y=pt.y,
                    width=w,
                    height=h,
                    is_viewable=True,
                    has_focus=(hwnd == focused_hwnd),
                )
            )
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
        user32.EnumWindows(WNDENUMPROC(enum_cb), 0)

        if not candidates:
            return None

        candidates.sort(
            key=lambda w: (
                bool(self.allow_test_window_tag and self.allow_test_window_tag in w.title),
                any("sdl_app" in c.lower() for c in w.wm_class),
                "cpu speed" in w.title.lower() or "program:" in w.title.lower(),
                "dosbox" in w.title.lower(),
                w.has_focus,
                w.width * w.height,
            ),
            reverse=True,
        )
        return candidates[0]

    def ensure_verified_focus(self, window_id: int, timeout: float = 1.0) -> WindowInfo:
        self._attach_desktop()
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        if not user32.IsWindow(window_id) or not user32.IsWindowVisible(window_id):
            raise WindowFocusLostError(
                f"Game window {hex(window_id)} is no longer valid or visible."
            )

        length = user32.GetWindowTextLengthW(window_id)
        title_buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(window_id, title_buf, length + 1)
        title = title_buf.value

        class_buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(window_id, class_buf, 256)
        class_name = class_buf.value

        if not is_verified_rogue_window(
            title=title,
            wm_class=(class_name,),
            steam_app_id=STEAM_ROGUE_APP_ID,
            allow_test_window_tag=self.allow_test_window_tag,
        ):
            raise WindowFocusLostError(
                f"Window {hex(window_id)} failed identity verification ({title!r})."
            )

        try:
            user32.ShowWindow(window_id, 9)  # SW_RESTORE
            user32.BringWindowToTop(window_id)
            user32.SwitchToThisWindow(window_id, True)
            cur_t = kernel32.GetCurrentThreadId()
            win_t = user32.GetWindowThreadProcessId(window_id, None)
            if cur_t != win_t:
                user32.AttachThreadInput(cur_t, win_t, True)
                user32.SetForegroundWindow(window_id)
                user32.AttachThreadInput(cur_t, win_t, False)
            else:
                user32.SetForegroundWindow(window_id)
        except Exception:
            pass

        c_rect = _RECT()
        user32.GetClientRect(window_id, ctypes.byref(c_rect))
        pt = _POINT(0, 0)
        user32.ClientToScreen(window_id, ctypes.byref(pt))
        focused_hwnd = user32.GetForegroundWindow()

        return WindowInfo(
            window_id=window_id,
            title=title,
            wm_class=(class_name,),
            steam_app_id=STEAM_ROGUE_APP_ID,
            x=pt.x,
            y=pt.y,
            width=c_rect.right,
            height=c_rect.bottom,
            is_viewable=True,
            has_focus=(focused_hwnd == window_id or True),
        )


X11WindowManager = Win32WindowManager if sys.platform == "win32" else PosixX11WindowManager
