"""
Context detector: inspect the frontmost window to determine what kind of
content the user is editing (SQL, Python, JavaScript, etc.).

Non-intrusive — read-only, no UI automation or key injection.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path


# ── Extension → context label ──────────────────────────────────────────────
_EXT_MAP: dict[str, str] = {
    ".sql": "sql",
    ".ddl": "sql",
    ".dml": "sql",
    ".py": "python",
    ".pyw": "python",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".java": "java",
    ".kt": "java",        # Kotlin — close enough for formatting intent
    ".cs": "csharp",
    ".go": "go",
    ".rs": "rust",
    ".php": "php",
    ".rb": "ruby",
    ".swift": "swift",
    ".cpp": "cpp",
    ".c": "cpp",
    ".h": "cpp",
    ".hpp": "cpp",
}

# ── App name → context label (when no file extension is available) ──────────
_APP_CTX_MAP: dict[str, str] = {
    # SQL tools
    "tableplus": "sql",
    "sequel pro": "sql",
    "sequel ace": "sql",
    "dbeaver": "sql",
    "datagrip": "sql",
    "mysql workbench": "sql",
    "pgadmin": "sql",
    "azure data studio": "sql",
    "sql server management studio": "sql",
    "ssms": "sql",
    "dbeavercommunity": "sql",
    "dbeaverce": "sql",
    # Code editors / IDEs  (the file-ext check overrides these for real files)
    "pycharm": "python",
    "pycharm professional": "python",
    "spyder": "python",
    "jupyter": "python",
    "jupyterlab": "python",
    "webstorm": "javascript",
    "intellij idea": "java",
    "clion": "cpp",
    "rider": "csharp",
    "goland": "go",
    "rustrover": "rust",
    "phpstorm": "php",
    "rubymine": "ruby",
}


@dataclass
class ContextInfo:
    """Result of a context detection pass."""

    context: str = "text"    # One of: sql, python, javascript, typescript, java, csharp, go, rust, php, text
    app_name: str = "Unknown"
    file_ext: str = ""


def detect_context() -> ContextInfo:
    """
    Inspect the frontmost application and open document to infer editing context.
    Falls back gracefully on any platform or permission error.
    """
    try:
        if sys.platform == "darwin":
            return _detect_macos()
        elif sys.platform == "win32":
            return _detect_windows()
    except Exception:
        pass
    return ContextInfo()


# ── macOS ──────────────────────────────────────────────────────────────────

def _detect_macos() -> ContextInfo:
    """Use NSWorkspace + Accessibility API (read-only) to detect context."""
    app_name = "Unknown"
    file_ext = ""

    try:
        from AppKit import NSWorkspace  # type: ignore
        ws = NSWorkspace.sharedWorkspace()
        active = ws.frontmostApplication()
        if active:
            app_name = str(active.localizedName() or "Unknown")
    except Exception:
        pass

    # Try to read the focused document path via Accessibility (kAXDocumentAttribute)
    try:
        from ApplicationServices import (  # type: ignore
            AXUIElementCreateApplication,
            AXUIElementCopyAttributeValue,
        )
        from AppKit import NSWorkspace  # type: ignore

        ws = NSWorkspace.sharedWorkspace()
        active = ws.frontmostApplication()
        if active:
            pid = active.processIdentifier()
            app_ref = AXUIElementCreateApplication(pid)
            # Try to get the focused window's document URL
            err, doc_url = AXUIElementCopyAttributeValue(app_ref, "AXFocusedWindow", None)
            if err == 0 and doc_url:
                err2, doc_val = AXUIElementCopyAttributeValue(doc_url, "AXDocument", None)
                if err2 == 0 and doc_val:
                    doc_str = str(doc_val)
                    file_ext = Path(doc_str.split("?")[0]).suffix.lower()
    except Exception:
        pass

    # Also try window title for file extension hints (e.g. "main.py — VS Code")
    if not file_ext:
        try:
            from Quartz import CGWindowListCopyWindowInfo, kCGWindowListOptionOnScreenOnly, kCGNullWindowID  # type: ignore
            wins = CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly, kCGNullWindowID) or []
            for win in wins:
                owner = str(win.get("kCGWindowOwnerName", ""))
                if owner.lower() == app_name.lower():
                    title = str(win.get("kCGWindowName", ""))
                    for part in title.replace("—", "–").replace("–", "-").split("-"):
                        candidate = part.strip()
                        if "." in candidate:
                            ext = Path(candidate.split(" ")[0]).suffix.lower()
                            if ext in _EXT_MAP:
                                file_ext = ext
                                break
                    if file_ext:
                        break
        except Exception:
            pass

    return _build_context(app_name, file_ext)


# ── Windows ────────────────────────────────────────────────────────────────

def _detect_windows() -> ContextInfo:
    """Use win32api to read the foreground window title and derive context."""
    app_name = "Unknown"
    file_ext = ""

    try:
        import ctypes
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value

        # Try to extract a filename from the title (e.g. "main.py - VS Code")
        for sep in [" - ", " – ", " — "]:
            parts = title.split(sep)
            if len(parts) >= 2:
                candidate = parts[0].strip()
                if "." in candidate:
                    ext = Path(candidate.split(" ")[0]).suffix.lower()
                    if ext:
                        file_ext = ext

                # Last part is usually the app name
                app_name = parts[-1].strip()
                break
        else:
            app_name = title.strip()

    except Exception:
        pass

    # Try to get the process name for app-based context
    try:
        import ctypes
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        pid = ctypes.c_ulong()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        PROCESS_QUERY_INFO = 0x1000
        h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_INFO, False, pid)
        if h:
            buf = ctypes.create_unicode_buffer(260)
            ctypes.windll.kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(ctypes.c_ulong(260)))
            ctypes.windll.kernel32.CloseHandle(h)
            exe_name = Path(buf.value).stem.lower()
            if not app_name or app_name == "Unknown":
                app_name = exe_name
    except Exception:
        pass

    return _build_context(app_name, file_ext)


# ── Shared logic ───────────────────────────────────────────────────────────

def _build_context(app_name: str, file_ext: str) -> ContextInfo:
    """Resolve context from extension (preferred) or app name (fallback)."""
    ctx = "text"

    if file_ext and file_ext in _EXT_MAP:
        ctx = _EXT_MAP[file_ext]
    else:
        # Try app-name based mapping
        lower_app = app_name.lower()
        for key, label in _APP_CTX_MAP.items():
            if key in lower_app:
                ctx = label
                break

    return ContextInfo(context=ctx, app_name=app_name, file_ext=file_ext)
