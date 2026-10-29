"""Client-area screenshot capture, DOSBox titlebar stripping, and token-efficient encoding."""

from __future__ import annotations

import io
import sys
from dataclasses import dataclass

if sys.platform == "win32":
    import ctypes
    import struct
    X = None  # type: ignore
else:
    try:
        from Xlib import X
    except ImportError:
        X = None  # type: ignore

import mss
from PIL import Image

from rogue_agent.features.steam_backend.window_manager import WindowInfo, X11WindowManager


@dataclass(frozen=True)
class CropMargins:
    """Configurable pixel margins to trim window borders if needed."""

    top: int = 0
    bottom: int = 0
    left: int = 0
    right: int = 0


def strip_wine_dosbox_chrome(image: Image.Image) -> Image.Image:
    """Strip the Wine/DOSBox window title bar (29px) and 3px frame in both 320x200 and 640x400 modes."""
    w, h = image.size
    if 642 <= w <= 660 and 420 <= h <= 450:
        pad_x = (w - 640) // 2
        pad_bottom = 3
        pad_top = h - 400 - pad_bottom
        if pad_top >= 20:
            return image.crop((pad_x, pad_top, pad_x + 640, pad_top + 400))
    if 322 <= w <= 340 and 220 <= h <= 250:
        pad_x = (w - 320) // 2
        pad_bottom = 3
        pad_top = h - 200 - pad_bottom
        if pad_top >= 20:
            return image.crop((pad_x, pad_top, pad_x + 320, pad_top + 200))
    return image


def _capture_win32_window(hwnd: int, width: int, height: int) -> Image.Image | None:
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    hwnd_dc = 0
    mem_dc = 0
    bitmap = 0
    try:
        hwnd_dc = user32.GetDC(hwnd)
        if not hwnd_dc:
            return None
        mem_dc = gdi32.CreateCompatibleDC(hwnd_dc)
        if not mem_dc:
            return None
        bitmap = gdi32.CreateCompatibleBitmap(hwnd_dc, width, height)
        if not bitmap:
            return None
        gdi32.SelectObject(mem_dc, bitmap)

        res = user32.PrintWindow(hwnd, mem_dc, 2)
        if not res:
            res = user32.PrintWindow(hwnd, mem_dc, 0)

        if not res:
            return None

        bmi = bytearray(40)
        struct.pack_into(
            "<lllhhllllll", bmi, 0, 40, width, -height, 1, 32, 0, width * height * 4, 0, 0, 0, 0
        )
        buf = ctypes.create_string_buffer(width * height * 4)
        gdi32.GetDIBits(mem_dc, bitmap, 0, height, buf, bytes(bmi), 0)
        return Image.frombuffer("RGB", (width, height), buf, "raw", "BGRX", 0, 1)
    except Exception:
        return None
    finally:
        if bitmap:
            try:
                gdi32.DeleteObject(bitmap)
            except Exception:
                pass
        if mem_dc:
            try:
                gdi32.DeleteDC(mem_dc)
            except Exception:
                pass
        if hwnd_dc:
            try:
                user32.ReleaseDC(hwnd, hwnd_dc)
            except Exception:
                pass


def capture_window_client_area(
    window_manager: X11WindowManager,
    win_info: WindowInfo,
    crop_margins: CropMargins | None = None,
    compact_for_api: bool = True,
) -> tuple[Image.Image, bytes]:
    """Capture strictly the client area of the verified game window and encode compactly."""
    width = win_info.width
    height = win_info.height

    img: Image.Image | None = None
    if sys.platform == "win32":
        h_default = 0
        try:
            user32 = ctypes.windll.user32
            h_default = user32.OpenDesktopW("Default", 0, False, 0x0101)
            if h_default:
                user32.SetThreadDesktop(h_default)

            class _RECT(ctypes.Structure):
                _fields_ = [
                    ("left", ctypes.c_long),
                    ("top", ctypes.c_long),
                    ("right", ctypes.c_long),
                    ("bottom", ctypes.c_long),
                ]

            class _POINT(ctypes.Structure):
                _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

            c_rect = _RECT()
            user32.GetClientRect(win_info.window_id, ctypes.byref(c_rect))
            pt = _POINT(0, 0)
            user32.ClientToScreen(win_info.window_id, ctypes.byref(pt))

            grab_w = c_rect.right if c_rect.right > 0 else width
            grab_h = c_rect.bottom if c_rect.bottom > 0 else height
            grab_x = pt.x
            grab_y = pt.y

            with mss.mss() as sct:
                region = {
                    "left": max(0, grab_x),
                    "top": max(0, grab_y),
                    "width": grab_w,
                    "height": grab_h,
                }
                shot = sct.grab(region)
                img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        except Exception:
            img = None
        finally:
            if h_default:
                try:
                    ctypes.windll.user32.CloseDesktop(h_default)
                except Exception:
                    pass

        if img is None:
            img = _capture_win32_window(win_info.window_id, width, height)
        if img is None:
            img = Image.new("RGB", (width, height), (0, 0, 0))
    else:
        win = window_manager.get_xlib_window(win_info.window_id)
        try:
            raw = win.get_image(0, 0, width, height, X.ZPixmap, 0xFFFFFFFF)
            data = raw.data
            if isinstance(data, str):
                data = data.encode("latin1")
            img = Image.frombytes("RGB", (width, height), data, "raw", "BGRX")
        except Exception:
            with mss.mss() as sct:
                region = {
                    "left": max(0, win_info.x),
                    "top": max(0, win_info.y),
                    "width": width,
                    "height": height,
                }
                shot = sct.grab(region)
                img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")

    img = strip_wine_dosbox_chrome(img)

    if crop_margins and (
        crop_margins.top or crop_margins.bottom or crop_margins.left or crop_margins.right
    ):
        cw, ch = img.size
        left = min(crop_margins.left, cw // 4)
        top = min(crop_margins.top, ch // 4)
        right = max(left + 64, cw - min(crop_margins.right, cw // 4))
        bottom = max(top + 64, ch - min(crop_margins.bottom, ch // 4))
        img = img.crop((left, top, right, bottom))

    encode_img = img
    if compact_for_api and img.width > 480:
        # Downscale 640x400 -> 480x300 with nearest-neighbor and 32-color CGA/EGA palette
        # to minimize vision token footprint and PNG byte size without losing CP437 legibility
        target_h = max(150, int(round(img.height * (480.0 / img.width))))
        resized = img.resize((480, target_h), Image.Resampling.NEAREST)
        encode_img = resized.quantize(colors=32, method=Image.Quantize.FASTOCTREE)

    buf = io.BytesIO()
    encode_img.save(buf, format="PNG", optimize=True)
    return img, buf.getvalue()
