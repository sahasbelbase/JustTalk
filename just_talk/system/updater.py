"""
Application Updater Module for Just Talk.
Handles checking GitHub Releases for newer versions, downloading installers/DMGs,
and performing seamless in-place updates while preserving all user configurations.
"""

import logging
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Tuple

from just_talk import __version__
from just_talk.config import get_app_data_dir

logger = logging.getLogger(__name__)

GITHUB_REPO = "sahasbelbase/JustTalk"
LATEST_RELEASE_URL = f"https://github.com/{GITHUB_REPO}/releases/latest"
API_RELEASE_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"


@dataclass
class UpdateInfo:
    available: bool
    current_version: str
    latest_version: str
    release_url: str
    download_url: Optional[str] = None
    asset_name: Optional[str] = None
    release_notes: Optional[str] = None


def parse_version_tuple(v_str: str) -> Tuple[int, ...]:
    """Parse version string like 'v1.0.11' or '1.0.10' into a numeric tuple (1, 0, 11)."""
    clean = re.sub(r"^[vV]", "", v_str.strip())
    parts = re.findall(r"\d+", clean)
    if not parts:
        return (0, 0, 0)
    return tuple(int(p) for p in parts)


def is_version_newer(latest: str, current: str) -> bool:
    """Returns True if latest version is strictly greater than current version."""
    return parse_version_tuple(latest) > parse_version_tuple(current)


class UpdateChecker:
    """Checks for new releases on GitHub and downloads/installs updates."""

    @staticmethod
    def check_for_updates(current_version: Optional[str] = None) -> UpdateInfo:
        """
        Check for the latest release on GitHub.
        Uses HTTP HEAD / redirect on https://github.com/sahasbelbase/JustTalk/releases/latest
        to avoid GitHub API rate limits.
        """
        curr_ver = current_version or __version__
        latest_tag = None
        release_url = LATEST_RELEASE_URL

        # Method 1: Check HTTP redirect of /releases/latest (No rate limits)
        try:
            req = urllib.request.Request(
                LATEST_RELEASE_URL,
                headers={"User-Agent": f"JustTalk-Updater/{curr_ver}"},
                method="HEAD",
            )

            class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, req, fp, code, msg, headers, newurl):
                    nonlocal latest_tag, release_url
                    release_url = newurl
                    if "/releases/tag/" in newurl:
                        latest_tag = newurl.split("/releases/tag/")[-1].strip("/")
                    return None  # Stop automatic redirect follow

            opener = urllib.request.build_opener(NoRedirectHandler)
            try:
                opener.open(req, timeout=5)
            except urllib.error.HTTPError as e:
                if e.code in (301, 302, 307, 308):
                    loc = e.headers.get("Location") or ""
                    release_url = loc
                    if "/releases/tag/" in loc:
                        latest_tag = loc.split("/releases/tag/")[-1].strip("/")
        except Exception as e:
            logger.debug(f"Direct redirect check failed ({e}), falling back to API...")

        # Method 2: Fallback to GitHub API if method 1 did not find tag
        if not latest_tag:
            try:
                import json

                api_req = urllib.request.Request(
                    API_RELEASE_URL,
                    headers={
                        "User-Agent": f"JustTalk-Updater/{curr_ver}",
                        "Accept": "application/vnd.github.v3+json",
                    },
                )
                with urllib.request.urlopen(api_req, timeout=5) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read().decode("utf-8"))
                        latest_tag = data.get("tag_name", "")
                        release_url = data.get("html_url", LATEST_RELEASE_URL)
            except Exception as e:
                logger.warning(f"Failed to check GitHub releases: {e}")
                return UpdateInfo(
                    available=False,
                    current_version=curr_ver,
                    latest_version=curr_ver,
                    release_url=release_url,
                )

        if not latest_tag:
            return UpdateInfo(
                available=False,
                current_version=curr_ver,
                latest_version=curr_ver,
                release_url=release_url,
            )

        clean_latest = latest_tag.lstrip("v")
        is_newer = is_version_newer(clean_latest, curr_ver)

        # Determine download URL for the target platform
        download_url = None
        asset_name = None
        if sys.platform == "darwin":
            asset_name = "JustTalk-macOS.dmg"
            download_url = f"https://github.com/{GITHUB_REPO}/releases/download/{latest_tag}/{asset_name}"
        elif sys.platform == "win32":
            asset_name = "JustTalk-Windows.exe"
            download_url = f"https://github.com/{GITHUB_REPO}/releases/download/{latest_tag}/{asset_name}"

        return UpdateInfo(
            available=is_newer,
            current_version=curr_ver,
            latest_version=clean_latest,
            release_url=release_url,
            download_url=download_url,
            asset_name=asset_name,
        )

    @staticmethod
    def get_updates_cache_dir() -> Path:
        """Returns the local updates download directory inside ~/.justtalk/updates."""
        updates_dir = get_app_data_dir() / "updates"
        updates_dir.mkdir(parents=True, exist_ok=True)
        return updates_dir

    @staticmethod
    def download_update(
        download_url: str,
        target_path: Path,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> Path:
        """Download update package with progress reporting."""
        target_path.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(
            download_url,
            headers={"User-Agent": "JustTalk-Updater"},
        )

        with urllib.request.urlopen(req, timeout=60) as response:
            total_size = int(response.headers.get("content-length", 0))
            downloaded = 0
            chunk_size = 64 * 1024  # 64 KB chunks

            with open(target_path, "wb") as f:
                while True:
                    chunk = response.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback and total_size > 0:
                        progress_callback(downloaded, total_size)

        return target_path

    @staticmethod
    def install_update(installer_path: Path) -> bool:
        """
        Execute in-place installer for the current OS.
        On macOS: Mount DMG and copy JustTalk.app to /Applications.
        On Windows: Execute Setup.exe with /SILENT flag to install in-place.
        """
        if not installer_path.exists():
            logger.error(f"Installer path does not exist: {installer_path}")
            return False

        if sys.platform == "darwin":
            try:
                # 1. Mount DMG quietly
                mount_cmd = ["hdiutil", "attach", str(installer_path), "-nobrowse", "-readonly"]
                mount_res = subprocess.run(mount_cmd, capture_output=True, text=True, check=True)
                mount_point = None
                for line in mount_res.stdout.splitlines():
                    if "/Volumes/" in line:
                        mount_point = line.split("/Volumes/")[-1]
                        mount_point = f"/Volumes/{mount_point.strip()}"
                        break

                if not mount_point or not Path(mount_point).exists():
                    mount_point = "/Volumes/Just Talk"

                app_in_dmg = Path(mount_point) / "Just Talk.app"
                if not app_in_dmg.exists():
                    app_in_dmg = Path(mount_point) / "JustTalk.app"

                if app_in_dmg.exists():
                    dest_app = Path("/Applications") / app_in_dmg.name
                    logger.info(f"Copying {app_in_dmg} to {dest_app}...")
                    if dest_app.exists():
                        shutil.rmtree(dest_app, ignore_errors=True)
                    shutil.copytree(app_in_dmg, dest_app)

                    # Remove quarantine attribute
                    subprocess.run(["xattr", "-cr", str(dest_app)], capture_output=True)

                    # Detach DMG
                    subprocess.run(["hdiutil", "detach", mount_point, "-force"], capture_output=True)

                    # Relaunch newly installed app cleanly (terminate current process so single-instance lock releases)
                    current_pid = os.getpid()
                    relaunch_script = f"sleep 0.5; kill -9 {current_pid} 2>/dev/null; open -n '{dest_app}'"
                    subprocess.Popen(["bash", "-c", relaunch_script])
                    return True
                else:
                    # Fallback: Just open DMG in Finder so user sees drag-to-Applications
                    subprocess.Popen(["open", str(installer_path)])
                    return True
            except Exception as e:
                logger.error(f"macOS in-place update failed: {e}")
                subprocess.Popen(["open", str(installer_path)])
                return False

        elif sys.platform == "win32":
            try:
                cmd = [
                    str(installer_path),
                    "/SILENT",
                    "/CLOSEAPPLICATIONS",
                    "/RESTARTAPPLICATIONS",
                    "/SUPPRESSMSGBOXES",
                ]
                subprocess.Popen(cmd, shell=True)
                return True
            except Exception as e:
                logger.error(f"Windows in-place update failed: {e}")
                os.startfile(str(installer_path))
                return False

        return False
