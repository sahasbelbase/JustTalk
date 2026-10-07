"""Decide whether a dictation came from an enrolled voice, and enrollment quality checks.

Speaker embeddings are compared on the *speech-only* part of the *raw* microphone audio, the
same way enrollment captures them. A dictation is only ignored when it clearly belongs to
someone else; uncertain scores keep the text, because silently losing the user's own words
is worse than occasionally typing a colleague's.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple

import numpy as np

SAMPLE_RATE = 16000

# Defaults for profiles enrolled before per-profile thresholds existed
DEFAULT_ACCEPT = 0.55  # at or above: confidently this person
DEFAULT_REJECT = 0.30  # below: confidently someone else

ENROLL_MIN_SPEECH_SEC = 2.0
ENROLL_MIN_SPEECH_RMS = 0.01
ENROLL_MIN_SNR_DB = 8.0


@dataclass
class VoiceProfile:
    name: str
    embedding: np.ndarray
    accept_threshold: Optional[float] = None
    sample_count: int = 1

    @property
    def thresholds(self) -> Tuple[float, float]:
        accept = self.accept_threshold if self.accept_threshold is not None else DEFAULT_ACCEPT
        reject = round(float(np.clip(accept - 0.25, 0.20, 0.40)), 3)
        return round(accept, 3), min(reject, round(accept - 0.05, 3))


@dataclass
class VoiceDecision:
    action: str  # "match" | "uncertain" | "other"
    speaker: Optional[str]
    score: float


def _frame_rms(audio: np.ndarray, sr: int, frame_sec: float) -> Tuple[np.ndarray, int]:
    frame = max(1, int(sr * frame_sec))
    n = len(audio) // frame
    if n == 0:
        return np.zeros(0, dtype=np.float32), frame
    frames = audio[: n * frame].reshape(n, frame)
    return np.sqrt(np.mean(np.square(frames), axis=1)), frame


def speech_only(audio: np.ndarray, sr: int = SAMPLE_RATE, frame_sec: float = 0.03,
                min_speech_sec: float = 0.8) -> np.ndarray:
    """Keep the frames that carry speech (relative to this recording's own noise floor)."""
    audio = np.asarray(audio, dtype=np.float32)
    rms, frame = _frame_rms(audio, sr, frame_sec)
    if rms.size == 0:
        return audio
    floor = float(np.percentile(rms, 20))
    threshold = max(floor * 2.5, 0.003)
    voiced = rms >= threshold
    # Keep a frame of context either side so word edges aren't clipped
    voiced = voiced | np.roll(voiced, 1) | np.roll(voiced, -1)
    if voiced.sum() * frame_sec < min_speech_sec:
        return audio
    frames = audio[: rms.size * frame].reshape(rms.size, frame)
    return frames[voiced].reshape(-1)


def decide(embedding: np.ndarray, profiles: Sequence[VoiceProfile]) -> VoiceDecision:
    best: Optional[VoiceProfile] = None
    best_score = -1.0
    for p in profiles:
        if p.embedding is None or p.embedding.shape != embedding.shape:
            continue
        score = float(np.dot(embedding, p.embedding))
        if score > best_score:
            best, best_score = p, score
    if best is None:
        return VoiceDecision("uncertain", None, 0.0)
    accept, reject = best.thresholds
    if best_score >= accept:
        return VoiceDecision("match", best.name, best_score)
    if best_score < reject:
        return VoiceDecision("other", None, best_score)
    return VoiceDecision("uncertain", None, best_score)


def _normalize(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return (v / n).astype(np.float32) if n > 1e-6 else v.astype(np.float32)


def combine_enrollment(takes: Iterable[np.ndarray]) -> Tuple[np.ndarray, float, float]:
    """
    Average several enrollment takes into one profile.
    Returns (profile_embedding, accept_threshold, consistency) where consistency is the lowest
    similarity between any two takes; the threshold sits a little below it.
    """
    embs = [_normalize(np.asarray(t, dtype=np.float32)) for t in takes]
    if not embs:
        raise ValueError("no enrollment takes")
    profile = _normalize(np.mean(embs, axis=0))
    if len(embs) == 1:
        return profile, DEFAULT_ACCEPT, 1.0
    sims = [float(np.dot(a, b)) for i, a in enumerate(embs) for b in embs[i + 1:]]
    consistency = min(sims)
    accept = float(np.clip(consistency - 0.12, 0.40, 0.70))
    return profile, accept, consistency


def adapt_profile(profile: np.ndarray, new_embedding: np.ndarray, sample_count: int) -> np.ndarray:
    """Fold a confirmed sample ("that was me") into the profile as a running mean."""
    weight = max(0.1, 1.0 / (sample_count + 1))
    return _normalize((1 - weight) * _normalize(profile) + weight * _normalize(new_embedding))


def check_take_quality(audio: np.ndarray, sr: int = SAMPLE_RATE) -> Optional[str]:
    """Return a short, actionable problem description, or None if the take is usable."""
    audio = np.asarray(audio, dtype=np.float32)
    if audio.size == 0 or float(np.max(np.abs(audio))) < 1e-4:
        return "No sound from the microphone. Check that the right microphone is selected."
    if float(np.max(np.abs(audio))) >= 0.99:
        return "Too loud — the microphone is clipping. Move back a little and try again."
    rms, _ = _frame_rms(audio, sr, 0.03)
    noise = float(np.percentile(rms, 10))
    speech_level = float(np.percentile(rms, 97))  # loud frames, even when speech is brief
    if speech_level < ENROLL_MIN_SPEECH_RMS:
        return "Too quiet. Move closer to the microphone or speak up a little."
    # Noise first: in a loud room speech can't be told apart, which would otherwise
    # be misreported as "not enough speech".
    snr_db = 20 * np.log10(max(speech_level, 1e-8) / max(noise, 1e-8))
    if snr_db < ENROLL_MIN_SNR_DB:
        return "Too much background noise. Try a quieter spot for enrollment."
    speech = speech_only(audio, sr, min_speech_sec=0.0)
    if len(speech) / sr < ENROLL_MIN_SPEECH_SEC:
        return "Not enough speech. Read the whole phrase at a normal pace."
    return None


def profiles_from_records(records: List[dict]) -> List[VoiceProfile]:
    return [
        VoiceProfile(
            name=r["name"],
            embedding=r["embedding"],
            accept_threshold=r.get("threshold"),
            sample_count=int(r.get("sample_count") or 1),
        )
        for r in records
        if r.get("embedding") is not None
    ]
