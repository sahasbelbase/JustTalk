"""Try the new setup and voice profile on your own voice, without touching Just Talk itself.

    PYTHONPATH=. .venv/bin/python scripts/try_voice_setup.py

Your current settings are loaded into a copy that is never saved, and "open at login" is left
alone. The voice profile and every recording go to ~/Documents/JustTalk-voice-test, which
scripts/analyze_voice_test.py reads afterwards. Apple's recognizer is skipped: it needs the
built app's own Speech Recognition permission and stalls when run from Terminal.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

import just_talk.profile.store as store
from just_talk.app import onboarding_window
from just_talk.app.theme import ThemeManager
from just_talk.config import AppConfig
from just_talk.profile.engines import ProfileEngines
from just_talk.profile.learner import Learner
from just_talk.stt.kriti_engine import KritiEngine
from just_talk.stt.model_manager import ModelManager
from just_talk.system.autostart import AutostartManager

OUT = Path.home() / "Documents" / "JustTalk-voice-test"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    store.profile_dir = lambda: OUT
    AutostartManager.set_autostart = staticmethod(lambda enabled: None)
    build = ProfileEngines._build
    ProfileEngines._build = lambda self, engine_id: None if engine_id == "apple" else build(self, engine_id)

    config = AppConfig.load()
    config.save = lambda *a, **k: None
    config.has_completed_onboarding = False

    app = QApplication(sys.argv)
    ThemeManager.load_fonts()
    ThemeManager.apply_theme(app, config.appearance)
    mm = ModelManager()
    window = onboarding_window.OnboardingWindow(
        config=config,
        model_manager=mm,
        kriti=KritiEngine(mm.models_dir),
        on_engines_changed=lambda: print(f"[test] Would switch the main engine to {config.stt_provider} ({config.model_tier})"),
        learner=Learner(OUT / "learned.json"),
    )
    window.show()
    window.raise_()
    window.activateWindow()
    app.exec()

    path = OUT / "profile.json"
    if not path.exists():
        print("\nNo profile saved (setup closed before 'Save profile').")
        return
    profile = json.loads(path.read_text(encoding="utf-8"))
    print(f"\nSaved {len(profile['clips'])} recordings to {OUT}")
    for lang, info in profile["languages"].items():
        acc = ", ".join(f"{e} {a:.0%}" for e, a in sorted(info["accuracy"].items(), key=lambda x: -x[1]))
        print(f"  {lang}: {acc}")
    if profile["mishearings"]:
        print("  mix-ups: " + ", ".join(f"{m['heard']} → {m['meant']}" for m in profile["mishearings"]))
    print("\nNow run: PYTHONPATH=. .venv/bin/python scripts/analyze_voice_test.py")


if __name__ == "__main__":
    main()
