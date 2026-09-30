"""Dynamic Caret and Input Field Locator for macOS and desktop platforms.

Finds the real-time screen coordinates of the active text caret or focused input field
across any application (VS Code, Chrome, Brave, Safari, Slack, Terminal, Notes, etc.) so that
the voice pill can float directly beneath the text insertion point, exactly like Wispr Flow and Typeless.
"""

from __future__ import annotations

import sys
from typing import Optional, Tuple

from PySide6.QtCore import QPoint
from PySide6.QtGui import QCursor, QGuiApplication


class CaretLocator:
    """Discovers screen coordinates for active text insertion points and input fields."""

    @classmethod
    def get_target_position(
        cls,
        pill_width: int = 216,
        pill_height: int = 48,
        offset_y: int = 8,
    ) -> Tuple[int, int]:
        """
        Calculates optimal (x, y) coordinates for the floating pill.
        Prioritizes:
          1. Exact text caret screen position (AXSelectedTextRange + AXBoundsForRange).
          2. Focused input box bounding box (AXPosition + AXSize).
          3. Frontmost active window + Mouse cursor position (where user clicked).
          4. Mouse cursor position (QCursor.pos()).
          5. Center of active screen (fallback).
        """
        target_x: Optional[float] = None
        target_y: Optional[float] = None
        top_anchor: Optional[float] = None

        if sys.platform == "darwin":
            target_x, target_y, top_anchor = cls._get_macos_caret_coords(
                pill_width=pill_width,
                pill_height=pill_height,
                offset_y=offset_y,
            )
        elif sys.platform == "win32":
            target_x, target_y, top_anchor = cls._get_windows_caret_coords(
                pill_width=pill_width,
                pill_height=pill_height,
                offset_y=offset_y,
            )

        # Fallback to mouse cursor position
        if target_x is None or target_y is None:
            mouse = QCursor.pos()
            target_x = float(mouse.x()) - (pill_width / 2.0)
            target_y = float(mouse.y()) + 24.0
            top_anchor = float(mouse.y())

        # Determine target display screen for bounds clamping
        probe_point = QPoint(int(target_x + pill_width / 2.0), int(target_y))
        screen = QGuiApplication.screenAt(probe_point)
        if not screen:
            screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()

        if screen:
            avail = screen.availableGeometry()
            # Horizontal bounds clamping with comfortable padding
            min_x = float(avail.x() + 16)
            max_x = float(avail.x() + avail.width() - pill_width - 16)
            target_x = max(min_x, min(target_x, max_x))

            # Vertical bounds clamping & flipping
            min_y = float(avail.y() + 16)
            max_y = float(avail.y() + avail.height() - pill_height - 16)

            if target_y > max_y:
                # Caret or input box is near the bottom edge of the screen or Dock.
                # Flip the pill to float ABOVE the input box / caret!
                if top_anchor is not None and top_anchor > min_y:
                    flipped_y = top_anchor - pill_height - offset_y - 4.0
                    target_y = flipped_y if flipped_y >= min_y else (max_y - 20.0)
                else:
                    target_y = max_y - 20.0
            elif target_y < min_y:
                target_y = min_y
        else:
            # Absolute fallback
            target_x = 400.0
            target_y = 400.0

        return int(target_x), int(target_y)

    @classmethod
    def _get_macos_caret_coords(
        cls,
        pill_width: int,
        pill_height: int,
        offset_y: int,
    ) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        """Query macOS Accessibility (AXUIElement) for active caret and input box bounds."""
        try:
            from AppKit import NSWorkspace
            import ApplicationServices

            front_app = NSWorkspace.sharedWorkspace().frontmostApplication()
            if not front_app:
                return None, None, None

            pid = front_app.processIdentifier()
            app_elem = ApplicationServices.AXUIElementCreateApplication(pid)
            if not app_elem:
                return None, None, None

            focused = None
            err, focused = ApplicationServices.AXUIElementCopyAttributeValue(
                app_elem, ApplicationServices.kAXFocusedUIElementAttribute, None
            )

            win = None
            err_win, win = ApplicationServices.AXUIElementCopyAttributeValue(
                app_elem, ApplicationServices.kAXFocusedWindowAttribute, None
            )

            # Fallback to focused window's focused element if app-level focused element is not returned
            if (err != 0 or not focused) and err_win == 0 and win:
                err_f, focused = ApplicationServices.AXUIElementCopyAttributeValue(
                    win, ApplicationServices.kAXFocusedUIElementAttribute, None
                )

            # NOTE: DO NOT query AXUIElementCreateSystemWide() when focused is None!
            # On macOS, SystemWide element returns the entire desktop background,
            # which misidentifies as an input field and pushes coordinates off screen.

            if focused:
                # --- Attempt 1: Exact text selection / caret bounds ---
                err_r, range_val = ApplicationServices.AXUIElementCopyAttributeValue(
                    focused, ApplicationServices.kAXSelectedTextRangeAttribute, None
                )
                if err_r == 0 and range_val:
                    err_b, bounds_val = ApplicationServices.AXUIElementCopyParameterizedAttributeValue(
                        focused,
                        ApplicationServices.kAXBoundsForRangeParameterizedAttribute,
                        range_val,
                        None,
                    )
                    if err_b == 0 and bounds_val:
                        ok, rect = ApplicationServices.AXValueGetValue(
                            bounds_val, ApplicationServices.kAXValueTypeCGRect, None
                        )
                        # Ensure rect is within realistic caret bounds
                        if ok and rect.origin.x > 0 and 0 < rect.size.height <= 80:
                            cx = rect.origin.x + (rect.size.width / 2.0)
                            caret_h = max(rect.size.height, 16.0)
                            cy = rect.origin.y + caret_h + offset_y
                            tx = cx - (pill_width / 2.0)
                            return tx, cy, rect.origin.y

                # --- Attempt 2: Focused UI Element Bounds (Input Box, Search Bar, Text Field) ---
                err_p, pos_val = ApplicationServices.AXUIElementCopyAttributeValue(
                    focused, ApplicationServices.kAXPositionAttribute, None
                )
                err_s, sz_val = ApplicationServices.AXUIElementCopyAttributeValue(
                    focused, ApplicationServices.kAXSizeAttribute, None
                )
                if err_p == 0 and pos_val and err_s == 0 and sz_val:
                    ok_p, pt = ApplicationServices.AXValueGetValue(
                        pos_val, ApplicationServices.kAXValueTypeCGPoint, None
                    )
                    ok_s, sz = ApplicationServices.AXValueGetValue(
                        sz_val, ApplicationServices.kAXValueTypeCGSize, None
                    )
                    # Real input elements are larger than 20x14, but NEVER larger than 1200x500
                    # (which would be an entire window or web viewport, not an input box!)
                    if ok_p and ok_s and 20.0 <= sz.width <= 1200.0 and 14.0 <= sz.height <= 500.0:
                        bw = sz.width
                        bh = sz.height
                        mouse = QCursor.pos()
                        # If mouse is inside this multi-line input box (e.g. textarea, chat box)
                        if (pt.x <= mouse.x() <= pt.x + bw) and (pt.y <= mouse.y() <= pt.y + bh):
                            tx = float(mouse.x()) - (pill_width / 2.0)
                            ty = float(mouse.y()) + 22.0
                            return tx, ty, float(mouse.y())
                        else:
                            tx = pt.x + (bw - pill_width) / 2.0
                            ty = pt.y + bh + offset_y
                            return tx, ty, pt.y

            # --- Attempt 3: Focused Window Bounds (Frontmost App Window) ---
            if win:
                err_p, pos_val = ApplicationServices.AXUIElementCopyAttributeValue(
                    win, ApplicationServices.kAXPositionAttribute, None
                )
                err_s, sz_val = ApplicationServices.AXUIElementCopyAttributeValue(
                    win, ApplicationServices.kAXSizeAttribute, None
                )
                if err_p == 0 and err_s == 0 and pos_val and sz_val:
                    ok_p, pt = ApplicationServices.AXValueGetValue(
                        pos_val, ApplicationServices.kAXValueTypeCGPoint, None
                    )
                    ok_s, sz = ApplicationServices.AXValueGetValue(
                        sz_val, ApplicationServices.kAXValueTypeCGSize, None
                    )
                    if ok_p and ok_s and sz.width > 50 and sz.height > 50:
                        # Cleanly center at the bottom of the active target window (VS Code, Brave, Chrome, Antigravity)
                        tx = pt.x + (sz.width - pill_width) / 2.0
                        ty = pt.y + sz.height - pill_height - 32.0
                        return tx, ty, None

        except Exception as e:
            print(f"[CaretLocator] Error resolving caret coordinates: {e}", file=sys.stderr)

        return None, None, None

    @classmethod
    def _get_windows_caret_coords(
        cls,
        pill_width: int,
        pill_height: int,
        offset_y: int,
    ) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        """Query Windows Win32 API (GetGUIThreadInfo) for active caret and focused window bounds."""
        try:
            import ctypes
            from ctypes import wintypes

            class GUITHREADINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.DWORD),
                    ("flags", wintypes.DWORD),
                    ("hwndActive", wintypes.HWND),
                    ("hwndFocus", wintypes.HWND),
                    ("hwndCapture", wintypes.HWND),
                    ("hwndMenuOwner", wintypes.HWND),
                    ("hwndMoveSize", wintypes.HWND),
                    ("hwndCaret", wintypes.HWND),
                    ("rcCaret", wintypes.RECT),
                ]

            user32 = ctypes.windll.user32
            gui_info = GUITHREADINFO()
            gui_info.cbSize = ctypes.sizeof(GUITHREADINFO)

            if user32.GetGUIThreadInfo(0, ctypes.byref(gui_info)):
                rc = gui_info.rcCaret
                if gui_info.hwndCaret and (rc.right > rc.left or rc.bottom > rc.top):
                    pt = wintypes.POINT(rc.left, rc.bottom)
                    if user32.ClientToScreen(gui_info.hwndCaret, ctypes.byref(pt)):
                        caret_screen_x = float(pt.x)
                        caret_screen_y = float(pt.y)
                        caret_top = float(pt.y - (rc.bottom - rc.top))
                        target_x = caret_screen_x - (pill_width / 2.0)
                        target_y = caret_screen_y + offset_y
                        return target_x, target_y, caret_top

                hwnd_target = gui_info.hwndFocus or gui_info.hwndActive
                if hwnd_target:
                    rect = wintypes.RECT()
                    if user32.GetWindowRect(hwnd_target, ctypes.byref(rect)):
                        box_w = rect.right - rect.left
                        box_h = rect.bottom - rect.top
                        if 10 < box_w < 1600 and 10 < box_h < 1200:
                            center_x = float(rect.left + (box_w / 2.0))
                            bottom_y = float(rect.bottom)
                            return center_x - (pill_width / 2.0), bottom_y + offset_y, float(rect.top)
        except Exception:
            pass

        return None, None, None
