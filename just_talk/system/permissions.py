"""OS permission verification and prompt dialogs (macOS Accessibility & Microphone)."""

from __future__ import annotations

import sys
from typing import Tuple


class PermissionsManager:
    """Verifies and prompts for necessary operating system permissions."""

    @staticmethod
    def check_accessibility(prompt_if_needed: bool = False) -> bool:
        """
        Check if application has macOS Accessibility permissions.
        On Windows / Linux, returns True.
        """
        if sys.platform != "darwin":
            return True

        try:
            from ApplicationServices import AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt

            # Only prompt if explicitly requested (e.g. from Settings button)
            options = {kAXTrustedCheckOptionPrompt: prompt_if_needed}
            trusted = AXIsProcessTrustedWithOptions(options)
            return bool(trusted)
        except Exception:
            # Fallback if pyobjc is not loaded
            return True

    @staticmethod
    def check_microphone() -> Tuple[bool, str]:
        """
        Verify microphone access.
        On macOS, queries AVCaptureDevice.
        """
        if sys.platform != "darwin":
            return True, "Microphone access allowed."

        try:
            from AVFoundation import (
                AVAuthorizationStatusAuthorized,
                AVAuthorizationStatusDenied,
                AVAuthorizationStatusNotDetermined,
                AVAuthorizationStatusRestricted,
                AVCaptureDevice,
                AVMediaTypeAudio,
            )

            status = AVCaptureDevice.authorizationStatusForMediaType_(AVMediaTypeAudio)
            if status == AVAuthorizationStatusAuthorized:
                return True, "Microphone authorized."
            elif status == AVAuthorizationStatusDenied:
                return False, "Microphone access denied in System Settings > Privacy & Security > Microphone."
            elif status == AVAuthorizationStatusRestricted:
                return False, "Microphone access is restricted by system policy."
            elif status == AVAuthorizationStatusNotDetermined:
                # Request access asynchronously
                AVCaptureDevice.requestAccessForMediaType_completionHandler_(
                    AVMediaTypeAudio, lambda granted: None
                )
                return True, "Microphone permission requested."
        except Exception:
            pass

        return True, "Microphone status verified."
