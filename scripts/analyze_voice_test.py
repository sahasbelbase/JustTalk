"""Re-run every local speech engine on the recordings from scripts/try_voice_setup.py.

    PYTHONPATH=. .venv/bin/python scripts/analyze_voice_test.py [--json report.json]

For each sentence it prints what every engine heard, its score and how long it took, then a
per-language summary: accuracy per engine, speed, and the mix-ups each engine made.
"""

from __future__ import annotations

import argparse
import json
import time
import wave
from collections import defaultdict
from pathlib import Path

import numpy as np

from just_talk.profile.scoring import score_take
from just_talk.profile.session import is_learnable_mixup
from just_talk.stt.kriti_engine import KritiEngine
from just_talk.stt.model_manager import ModelManager
from just_talk.stt.whisper_engine import WhisperSTTEngine

OUT = Path.home() / "Documents" / "JustTalk-voice-test"
WHISPER_TIERS = {"en": ["base.en", "small.en", "quality"], "ne": ["quality"], "ne_en": ["quality"]}


def load_wav(path: Path) -> np.ndarray:
    with wave.open(str(path)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path, default=OUT)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()

    profile = json.loads((args.dir / "profile.json").read_text(encoding="utf-8"))
    mm = ModelManager()
    kriti = KritiEngine(mm.models_dir)
    whisper = {}

    def engines_for(lang):
        out = []
        if lang in ("ne", "ne_en") and kriti.is_available():
            out.append(("kriti", lambda a: kriti.transcribe(a, language="ne")))
        for tier in WHISPER_TIERS[lang]:
            if not mm.is_model_downloaded(tier):
                continue
            if tier not in whisper:
                whisper[tier] = WhisperSTTEngine(mm)
                whisper[tier].load(tier)
            engine = whisper[tier]
            out.append((f"whisper:{tier}", lambda a, e=engine: e.transcribe(a, language=None if lang == "ne_en" else lang)))
        return out

    rows = []
    totals = defaultdict(lambda: [0, 0, 0.0, 0.0, 0])  # ok, denominator, seconds, audio seconds, takes
    mixups = defaultdict(set)
    for clip in profile["clips"]:
        path = args.dir / clip["file"]
        if not path.exists():
            continue
        audio = load_wav(path)
        lang, text = clip["language"], clip["text"]
        print(f"\n[{lang}] {text}   ({len(audio) / 16000:.1f}s)")
        for name, run in engines_for(lang):
            t0 = time.monotonic()
            heard = run(audio) or ""
            dt = time.monotonic() - t0
            s = score_take(text, heard, lang)
            t = totals[(lang, name)]
            t[0] += sum(1 for w in s.words if w.status == "ok")
            t[1] += len(s.words) + s.inserted
            t[2] += dt
            t[3] += len(audio) / 16000
            t[4] += 1
            slips = [(h, m) for h, m in s.mishearings if is_learnable_mixup(m)]
            if s.accuracy >= 0.6:
                mixups[(lang, name)].update(slips)
            print(f"  {name:18s} {s.accuracy:5.0%}  {dt:4.1f}s  {heard}")
            if slips:
                print(f"  {'':18s}        mix-ups: " + ", ".join(f"{h} → {m}" for h, m in slips))
            rows.append({"language": lang, "text": text, "engine": name, "heard": heard,
                         "accuracy": round(s.accuracy, 4), "seconds": round(dt, 2)})
        live = clip.get("heard") or {}
        if live:
            print("  during setup: " + "; ".join(f"{e}: {h}" for e, h in live.items()))

    print("\n=== Summary ===")
    for lang in ("en", "ne", "ne_en"):
        keys = [k for k in totals if k[0] == lang]
        if not keys:
            continue
        print(f"\n{lang}")
        for key in sorted(keys, key=lambda k: -(totals[k][0] / max(totals[k][1], 1))):
            ok, den, sec, audio_sec, n = totals[key]
            speed = sec / max(audio_sec, 1e-6)
            print(f"  {key[1]:18s} {ok / max(den, 1):5.0%}  over {n} sentences   {sec / n:4.1f}s per sentence ({speed:.2f}× real time)")
            if mixups[key]:
                print(f"  {'':18s} mix-ups: " + ", ".join(f"{h} → {m}" for h, m in sorted(mixups[key])))
    if args.json:
        args.json.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nWrote {args.json}")
    for engine in whisper.values():
        engine.unload()


if __name__ == "__main__":
    main()
