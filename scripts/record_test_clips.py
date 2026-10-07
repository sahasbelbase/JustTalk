"""Record the voice-isolation / Nepali evaluation clips (developer tool, not shipped).

Usage (one group at a time, so you can change rooms or hand the mic to someone else):
    uv run python scripts/record_test_clips.py A      # you, quiet room, normal voice
    uv run python scripts/record_test_clips.py B      # you, quiet room, low voice
    uv run python scripts/record_test_clips.py C      # you, in noise (office, cafe, TV playing)
    uv run python scripts/record_test_clips.py D      # someone else, same microphone
    uv run python scripts/record_test_clips.py E      # background only: nobody speaks into the mic
    uv run python scripts/record_test_clips.py F      # you, Nepali reading for accuracy scoring

Clips are saved as 16 kHz mono WAV in ~/Documents/JustTalk-test-clips/ with the expected
text in transcripts.json. Uses the input device selected in Just Talk's settings.
"""

from __future__ import annotations

import json
import sys
import time
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd

SR = 16000
OUT = Path.home() / "Documents" / "JustTalk-test-clips"

S_EN1 = "Tomorrow's meeting is at ten, so please send me the report before then."
S_EN2 = "Can you check the settings page, it keeps going back to home."
S_NE = "Ma bholi office jaanchu ani report pathaunchu."
S_NG = "Yo code ma error aayo, fix garnu paryo, testing pani garnu parcha."

GROUPS = {
    "A": ("You, quiet room, NORMAL voice", [("a1_en", S_EN1), ("a2_en", S_EN2), ("a3_ne", S_NE), ("a4_nepglish", S_NG)]),
    "B": ("You, quiet room, LOW voice (as if people are nearby)", [("b1_low_en", S_EN1), ("b2_low_ne", S_NE)]),
    "C": ("You, in NOISE (office, cafe, or TV playing)", [
        ("c1_noisy_en", S_EN1), ("c2_noisy_ne", S_NE),
        ("c3_noisy_low_en", S_EN1 + "  (LOW voice)"), ("c4_noisy_low_ne", S_NE + "  (LOW voice)"),
    ]),
    "D": ("SOMEONE ELSE reads, same microphone", [("d1_other_en", S_EN1), ("d2_other_ne", S_NE), ("d3_other_nepglish", S_NG)]),
    "E": ("BACKGROUND ONLY — nobody speaks into the mic", [
        ("e1_chatter", "(people talking nearby; you stay silent)"), ("e2_tv", "(TV or a video playing; you stay silent)"),
    ]),
    "F": ("You, NEPALI reading (for accuracy scoring)", [
        ("f1_ne", "Nepal ko rajdhani Kathmandu ho, ra yaha dherai mandir haru chan."),
        ("f2_ne", "Aaja mausam ramro cha, tara beluka pani parna sakcha."),
        ("f3_ne", "Mero phone ko battery chado sakinchha, charger kinnu parcha."),
    ]),
}
SECONDS = 7


def device_index():
    try:
        cfg = json.loads((Path.home() / "Library/Application Support/JustTalk/config.json").read_text())
        return cfg.get("audio_device_index")
    except Exception:
        return None


def save_wav(path: Path, audio: np.ndarray) -> None:
    pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def main() -> int:
    group = (sys.argv[1] if len(sys.argv) > 1 else "").upper()
    if group not in GROUPS:
        print(__doc__)
        return 1
    title, clips = GROUPS[group]
    OUT.mkdir(parents=True, exist_ok=True)
    meta_path = OUT / "transcripts.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    dev = device_index()

    print(f"\n=== Group {group}: {title} ===", flush=True)
    print(f"Saving to {OUT}  (device: {dev if dev is not None else 'system default'})\n", flush=True)
    for name, text in clips:
        print(f"Next: {name}\n   >>> {text}", flush=True)
        for n in (3, 2, 1):
            print(f"   starting in {n}…", flush=True)
            time.sleep(1)
        print(f"   ● RECORDING ({SECONDS} s) — speak now", flush=True)
        audio = sd.rec(int(SR * SECONDS), samplerate=SR, channels=1, dtype="float32", device=dev)
        sd.wait()
        audio = audio[:, 0]
        save_wav(OUT / f"{name}.wav", audio)
        meta[name] = text
        peak = float(np.max(np.abs(audio)))
        warn = "  ⚠ very quiet — check the microphone" if peak < 0.01 else ""
        print(f"   saved {name}.wav (peak {peak:.2f}){warn}\n", flush=True)
        time.sleep(1.5)
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False))
    print("Done. Run the next group when you're ready.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
