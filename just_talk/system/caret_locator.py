"""Dynamic Caret and Input Field Locator for macOS and desktop platforms.

Finds the real-time screen coordinates of the active text caret or focused input field
across any application (VS Code, Chrome, Safari, Slack, Terminal, Notes, etc.) so that
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
          3. Mouse cursor position (QCursor.pos()).
          4. Bottom-center of the active screen (fallback).
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
            # Horizontal bounds clamping
            min_x = float(avail.x() + 12)
            max_x = float(avail.x() + avail.width() - pill_width - 12)
            target_x = max(min_x, min(target_x, max_x))

            # Vertical bounds clamping & flipping
            min_y = float(avail.y() + 12)
            max_y = float(avail.y() + avail.height() - pill_height - 12)

            if target_y > max_y:
                # Caret or input box is near the bottom edge of the screen or Dock.
                # Flip the pill to float ABOVE the input box / caret!
                if top_anchor is not None:
                    flipped_y = top_anchor - pill_height - offset_y - 2.0
                    target_y = flipped_y if flipped_y >= min_y else max_y
                else:
                    target_y = max_y
            elif target_y < min_y:
                target_y = min_y
        else:
            # Absolute fallback
            target_x = 100.0
            target_y = 100.0

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

            if not focused:
                # Try system-wide focused element
                system_wide = ApplicationServices.AXUIElementCreateSystemWide()
                if system_wide:
                    err_sys, focused = ApplicationServices.AXUIElementCopyAttributeValue(
                        system_wide, ApplicationServices.kAXFocusedUIElementAttribute, None
                    )

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
                        if ok and (rect.size.height > 0 or rect.origin.x > 0):
                            cx = rect.origin.x + (rect.size.width / 2.0)
                            caret_h = max(rect.size.height, 16.0)
                            cy = rect.origin.y + caret_h + offset_y
                            tx = cx - (pill_width / 2.0)
                            return tx, cy, rect.origin.y

                # --- Attempt 2: Focused UI Element Bounds (Input Box, Search Bar, Text Field) ---
                err_p, pos_val = ApplicationServices.AXUIElementCopyAttributeValue(
                    focused, ApplicationServices.kAXPositionAttribute, None
                )
                if err_p == 0 and pos_val:
                    ok_p, pt = ApplicationServices.AXValueGetValue(
                        pos_val, ApplicationServices.kAXValueTypeCGPoint, None
                    )
                    err_s, sz_val = ApplicationServices.AXUIElementCopyAttributeValue(
                        focused, ApplicationServices.kAXSizeAttribute, None
                    )
                    if err_s == 0 and sz_val:
                        ok_s, sz = ApplicationServices.AXValueGetValue(
                            sz_val, ApplicationServices.kAXValueTypeCGSize, None
                        )
                        # Require a realistic input box dimension (>= 20px wide, >= 14px tall)
                        # to filter out dummy 1x0 or 1x1 elements from browsers like Brave/Chrome
                        if ok_p and ok_s and sz.width >= 20.0 and sz.height >= 14.0:
                            bw = sz.width
                            bh = sz.height
                            mouse = QCursor.pos()
                            # For large multi-line editors (e.g. VS Code, TextEdit) where mouse was used to position focus
                            if bh > 100.0 and (pt.x <= mouse.x() <= pt.x + bw) and (pt.y <= mouse.y() <= pt.y + bh):
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
                        mouse = QCursor.pos()
                        # If mouse is inside this active window, anchor beneath the mouse position
                        if pt.x <= mouse.x() <= pt.x + sz.width and pt.y <= mouse.y() <= pt.y + sz.height:
                            tx = float(mouse.x()) - (pill_width / 2.0)
                            ty = float(mouse.y()) + 20.0
                            return tx, ty, float(mouse.y())
                        tx = pt.x + (sz.width - pill_width) / 2.0
                        ty = pt.y + sz.height - pill_height - 24.0
                        return tx, ty, pt.y

        except Exception as e:
            print(f"[CaretLocator] Error resolving caret coordinates: {e}", file=sys.stderr)

        return None, None, None
