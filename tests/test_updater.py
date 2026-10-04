"""Unit tests for Just Talk in-place updater."""

import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

from just_talk.system.updater import (
    UpdateChecker,
    UpdateInfo,
    is_version_newer,
    parse_version_tuple,
)


def test_parse_version_tuple():
    assert parse_version_tuple("1.0.0") == (1, 0, 0)
    assert parse_version_tuple("v1.0.11") == (1, 0, 11)
    assert parse_version_tuple("V2.1.3-beta") == (2, 1, 3)
    assert parse_version_tuple("0.9") == (0, 9)
    assert parse_version_tuple("") == (0, 0, 0)


def test_is_version_newer():
    assert is_version_newer("1.0.11", "1.0.10") is True
    assert is_version_newer("v1.1.0", "1.0.10") is True
    assert is_version_newer("2.0.0", "1.9.9") is True
    assert is_version_newer("1.0.10", "1.0.10") is False
    assert is_version_newer("1.0.9", "1.0.10") is False
    assert is_version_newer("0.9.0", "1.0.0") is False


def test_check_for_updates_via_redirect():
    """Test Method 1: HTTP 302 redirect from /releases/latest."""
    mock_opener = MagicMock()
    # Simulate HTTP 302 redirect with Location header
    http_error = urllib.error.HTTPError(
        url="https://github.com/sahasbelbase/JustTalk/releases/latest",
        code=302,
        msg="Found",
        hdrs={"Location": "https://github.com/sahasbelbase/JustTalk/releases/tag/v1.2.0"},
        fp=None,
    )
    mock_opener.open.side_effect = http_error

    with patch("urllib.request.build_opener", return_value=mock_opener):
        info = UpdateChecker.check_for_updates(current_version="1.0.0")
        assert info.available is True
        assert info.latest_version == "1.2.0"
        assert "v1.2.0" in info.release_url
        assert info.download_url is not None


def test_check_for_updates_fallback_api():
    """Test Method 2: API fallback when redirect check fails."""
    mock_opener = MagicMock()
    mock_opener.open.side_effect = Exception("Network offline for HEAD")

    mock_response = MagicMock()
    mock_response.__enter__.return_value = mock_response
    mock_response.status = 200
    mock_response.read.return_value = b'{"tag_name": "v1.3.0", "html_url": "https://github.com/sahasbelbase/JustTalk/releases/tag/v1.3.0"}'

    with patch("urllib.request.build_opener", return_value=mock_opener), \
         patch("urllib.request.urlopen", return_value=mock_response):
        info = UpdateChecker.check_for_updates(current_version="1.0.0")
        assert info.available is True
        assert info.latest_version == "1.3.0"


def test_check_for_updates_already_latest():
    mock_opener = MagicMock()
    http_error = urllib.error.HTTPError(
        url="https://github.com/sahasbelbase/JustTalk/releases/latest",
        code=302,
        msg="Found",
        hdrs={"Location": "https://github.com/sahasbelbase/JustTalk/releases/tag/v1.0.0"},
        fp=None,
    )
    mock_opener.open.side_effect = http_error

    with patch("urllib.request.build_opener", return_value=mock_opener):
        info = UpdateChecker.check_for_updates(current_version="1.0.0")
        assert info.available is False
        assert info.latest_version == "1.0.0"


def test_updates_cache_dir(tmp_path):
    with patch("just_talk.system.updater.get_app_data_dir", return_value=tmp_path):
        cache_dir = UpdateChecker.get_updates_cache_dir()
        assert cache_dir.exists()
        assert cache_dir.name == "updates"
