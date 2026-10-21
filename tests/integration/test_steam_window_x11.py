"""Level 2 Integration Test: Real X11/Xwayland window discovery and client-area capture."""

from __future__ import annotations

import os
import time

import pytest
from Xlib import X, display

from rogue_agent.features.steam_backend.capture import capture_window_client_area
from rogue_agent.features.steam_backend.visual_state import analyze_steam_screenshot
from rogue_agent.features.steam_backend.window_manager import X11WindowManager
from rogue_agent.shared.domain import GameState


@pytest.mark.integration
@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="Requires X11/Xwayland DISPLAY")
def test_x11_window_discovery_and_client_capture() -> None:
    """Create a real X11 window on Xwayland, discover it, and capture its client pixels."""
    test_tag = "ROGUE_X11_INTEGRATION_TEST_WIN"
    dpy = display.Display()
    screen = dpy.screen()
    win = screen.root.create_window(
        100,
        100,
        320,
        200,
        0,
        screen.root_depth,
        X.InputOutput,
        X.CopyFromParent,
        background_pixel=screen.black_pixel,
        event_mask=X.ExposureMask | X.StructureNotifyMask,
    )
    win.set_wm_name(test_tag)
    win.set_wm_class("dosbox_test", "DOSBoxTest")
    win.map()
    dpy.sync()
    time.sleep(0.15)

    wm = X11WindowManager(allow_test_window_tag=test_tag)
    try:
        found = wm.find_game_window()
        assert found is not None, "Expected X11WindowManager to discover mapped X11 test window"
        assert found.window_id == int(win.id)
        assert found.width == 320
        assert found.height == 200

        img, png_bytes = capture_window_client_area(wm, found)
        assert img.size == (320, 200)
        assert png_bytes.startswith(b"\x89PNG")

        analysis = analyze_steam_screenshot(img)
        assert analysis.inferred_state in (GameState.UNKNOWN, GameState.PLAYING)
    finally:
        wm.close()
        win.unmap()
        win.destroy()
        dpy.sync()
        dpy.close()
