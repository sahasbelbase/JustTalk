"""One voice-setup session: which sentence comes next, what each engine heard, and the result.

Engines finish at different times (Kriti in a tenth of a second, Whisper Turbo in seconds), so
results are added per take and per engine as they arrive, and the summary uses whatever is in.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .scoring import MISHEARD, MISSED, OK, TakeScore, score_take, strip_word
from .scripts import BASE, EN, EXTRA, FOLLOWUPS, MIXED, NE, Prompt, focus_of, role_prompts, word_prompts
from .store import VoiceProfile

TARGET_ACCURACY = 0.98
MAX_FOLLOWUPS = 3
FOLLOWUP_MISS_RATE = 0.34   # add a follow-up when a third or more of a sound's words were misheard
KEEP_CURRENT_MARGIN = 0.03  # don't suggest switching engines over a difference this small
MIXUP_MIN_TAKE_ACCURACY = 0.6  # a take this far off the sentence was probably read differently
OFF_SCRIPT_ACCURACY = 0.3      # below this, ask the user to read the sentence again


@dataclass
class Take:
    prompt: Prompt
    clip_id: str
    heard: Dict[str, str] = field(default_factory=dict)
    scores: Dict[str, TakeScore] = field(default_factory=dict)


@dataclass
class LanguageSummary:
    language: str
    accuracy: Dict[str, float]  # engine id -> accuracy over all takes
    best: str
    current: str
    takes: int
    mishearings: List[Tuple[str, str]]  # (heard, meant) from the engine in use
    confirmed: set = field(default_factory=set)  # those another engine heard right: certainly the engine's fault

    @property
    def in_use(self) -> str:
        """The engine the app uses for this language (the best one if the current one never ran)."""
        return self.current if self.current in self.accuracy else self.best

    @property
    def best_accuracy(self) -> float:
        return self.accuracy.get(self.best, 0.0)

    @property
    def in_use_accuracy(self) -> float:
        return self.accuracy.get(self.in_use, 0.0)

    @property
    def suggest_switch(self) -> bool:
        return self.best != self.current and self.current in self.accuracy


def languages_to_profile(spoken: List[str]) -> List[str]:
    """English and Nepali get their own sets; speaking both adds Nepglish."""
    langs = [l for l in (EN, NE) if l in spoken]
    if EN in langs and NE in langs:
        langs.append(MIXED)
    return langs


class ProfileSession:
    def __init__(
        self,
        languages: List[str],
        personal_words: Optional[List[str]] = None,
        role: str = "",
        current_engine: Optional[Dict[str, str]] = None,
        live_engine: Optional[Dict[str, str]] = None,
    ):
        self.languages = [l for l in languages if l in BASE]
        self.personal_words = [w.strip() for w in (personal_words or []) if w.strip()]
        self.role = role
        self.current_engine = current_engine or {}
        self.live_engine = live_engine or {}
        self.takes: Dict[str, Take] = {}
        self._order: List[str] = []
        self._followups_added = False
        self._used_extra: Dict[str, int] = {l: 0 for l in self.languages}

        queue: List[Prompt] = []
        for lang in self.languages:
            queue.extend(BASE[lang])
            queue.extend(role_prompts(role, lang))
            if lang == EN or (lang == NE and EN not in self.languages):
                queue.extend(word_prompts(self.personal_words, self.languages))
        self.queue: List[Prompt] = queue
        self._total = len(queue)

    # ── Progress ─────────────────────────────────────────────────────────────

    @property
    def done_count(self) -> int:
        return len(self._order)

    @property
    def total(self) -> int:
        return self._total

    def next_prompt(self) -> Optional[Prompt]:
        if not self.queue and not self._followups_added:
            self._followups_added = True
            extra = self._followups()
            self.queue.extend(extra)
            self._total += len(extra)
        return self.queue.pop(0) if self.queue else None

    def put_back(self, prompt: Prompt) -> None:
        """Re-queue a prompt (the user asked to read it again)."""
        self.queue.insert(0, prompt)

    def keep_training(self) -> int:
        """Queue more sentences for languages still under the target. Returns how many."""
        added = 0
        for s in self.summary():
            if s.in_use_accuracy >= TARGET_ACCURACY:
                continue
            pool = EXTRA.get(s.language, [])
            start = self._used_extra.get(s.language, 0)
            batch = pool[start : start + 2]
            self._used_extra[s.language] = start + len(batch)
            self.queue.extend(batch)
            added += len(batch)
        self._total += added
        return added

    # ── Results ──────────────────────────────────────────────────────────────

    def start_take(self, prompt: Prompt, clip_id: str) -> Take:
        take = Take(prompt=prompt, clip_id=clip_id)
        if clip_id in self.takes:
            self._order.remove(clip_id)
        self.takes[clip_id] = take
        self._order.append(clip_id)
        return take

    def discard_take(self, clip_id: str) -> None:
        if clip_id in self.takes:
            del self.takes[clip_id]
            self._order.remove(clip_id)

    def add_result(self, clip_id: str, engine_id: str, text: str) -> Optional[TakeScore]:
        take = self.takes.get(clip_id)
        if take is None:
            return None
        take.heard[engine_id] = text or ""
        score = score_take(take.prompt.text, text or "", take.prompt.language)
        take.scores[engine_id] = score
        return score

    def _reference_score(self, take: Take) -> Optional[TakeScore]:
        lang = take.prompt.language
        for engine in (self.current_engine.get(lang), self.live_engine.get(lang)):
            if engine and engine in take.scores:
                return take.scores[engine]
        return next(iter(take.scores.values()), None)

    def _followups(self) -> List[Prompt]:
        """Extra English sentences for the sounds this speaker's engine got wrong most."""
        counts: Dict[str, List[int]] = {}
        for clip_id in self._order:
            take = self.takes[clip_id]
            if take.prompt.language != EN:
                continue
            score = self._reference_score(take)
            if score is None:
                continue
            for mark in score.words:
                for focus in focus_of(strip_word(mark.text)):
                    c = counts.setdefault(focus, [0, 0])
                    c[0] += 1
                    c[1] += mark.status in (MISHEARD, MISSED)
        ranked = sorted(
            ((miss / total, focus) for focus, (total, miss) in counts.items() if total >= 2),
            reverse=True,
        )
        picked = [focus for rate, focus in ranked if rate >= FOLLOWUP_MISS_RATE][:MAX_FOLLOWUPS]
        return [p for focus in picked for p in FOLLOWUPS.get(focus, [])[:1]]

    def summary(self) -> List[LanguageSummary]:
        out = []
        for lang in self.languages:
            takes = [self.takes[c] for c in self._order if self.takes[c].prompt.language == lang]
            if not takes:
                continue
            # An engine that never returned text didn't run (no permission, offline); leave it out.
            ran = {e for t in takes for e in t.scores if (t.heard.get(e) or "").strip()}
            accuracy = {e: _accuracy(takes, e) for e in ran}
            accuracy = {e: a for e, a in accuracy.items() if a is not None}
            if not accuracy:
                continue
            current = self.current_engine.get(lang, "")
            best = _best_engine(takes, accuracy, current)
            in_use = current if current in accuracy else best
            mixups = _collect_mishearings(takes, in_use)
            out.append(LanguageSummary(
                language=lang,
                accuracy=accuracy,
                best=best,
                current=current,
                takes=len(takes),
                mishearings=[(h, m) for h, m, _ in mixups],
                confirmed={(h, m) for h, m, sure in mixups if sure},
            ))
        return out

    def overall_accuracy(self) -> Optional[float]:
        summaries = self.summary()
        if not summaries:
            return None
        weight = sum(s.takes for s in summaries)
        return sum(s.in_use_accuracy * s.takes for s in summaries) / weight

    def to_profile(self, labels: Dict[str, str], clip_files: Dict[str, str], previous: Optional[VoiceProfile] = None) -> VoiceProfile:
        profile = VoiceProfile()
        for s in self.summary():
            profile.languages[s.language] = {
                "engine": s.in_use,
                "label": labels.get(s.in_use, s.in_use),
                "best": s.best,
                "accuracy": {e: round(a, 4) for e, a in s.accuracy.items()},
                "takes": s.takes,
            }
        merged: Dict[Tuple[str, str, str], dict] = {}
        for m in (previous.mishearings if previous else []):
            merged[(m["heard"].lower(), m["meant"].lower(), m.get("language", ""))] = dict(m)
        for s in self.summary():
            for heard, meant in s.mishearings:
                key = (heard.lower(), meant.lower(), s.language)
                entry = merged.setdefault(key, {"heard": heard, "meant": meant, "language": s.language, "count": 0})
                entry["count"] += 1
                entry["confirmed"] = entry.get("confirmed", False) or (heard, meant) in s.confirmed
        profile.mishearings = sorted(merged.values(), key=lambda m: -m["count"])
        profile.words = list(dict.fromkeys((previous.words if previous else []) + self.personal_words))
        profile.role = self.role or (previous.role if previous else "")
        # Earlier sessions' clips stay part of the personal test set.
        profile.clips = [c for c in (previous.clips if previous else []) if c.get("id") not in self.takes]
        for clip_id in self._order:
            take = self.takes[clip_id]
            profile.clips.append({
                "id": clip_id,
                "file": clip_files.get(clip_id, ""),
                "text": take.prompt.text,
                "language": take.prompt.language,
                "heard": dict(take.heard),
            })
        return profile


def _accuracy(takes: List[Take], engine: str) -> Optional[float]:
    ok = den = 0
    for take in takes:
        score = take.scores.get(engine)
        if score is not None:
            ok += sum(1 for w in score.words if w.status == "ok")
            den += len(score.words) + score.inserted
    return ok / den if den else None


def _best_engine(takes: List[Take], accuracy: Dict[str, float], current: str) -> str:
    """Slow engines are only compared on a few sentences, so each challenger is measured
    against the current engine on the sentences both of them heard."""
    if current not in accuracy:
        return max(accuracy, key=accuracy.get)
    best, best_gain = current, KEEP_CURRENT_MARGIN
    for engine in accuracy:
        if engine == current:
            continue
        shared = [t for t in takes if engine in t.scores and current in t.scores]
        if len(shared) < 2:
            continue
        gain = (_accuracy(shared, engine) or 0.0) - (_accuracy(shared, current) or 0.0)
        if gain >= best_gain:
            best, best_gain = engine, gain
    return best


def is_learnable_mixup(meant: str) -> bool:
    return sum(c.isalpha() for c in meant) >= 2


def _collect_mishearings(takes: List[Take], engine: str) -> List[Tuple[str, str, bool]]:
    """(heard, meant, confirmed): confirmed when another engine heard the word right."""
    seen = {}
    for take in takes:
        score = take.scores.get(engine)
        if score is None or score.accuracy < MIXUP_MIN_TAKE_ACCURACY:
            continue
        others = [s for e, s in take.scores.items() if e != engine and (take.heard.get(e) or "").strip()]
        for i, mark in enumerate(score.words):
            meant = strip_word(mark.text)
            if mark.status != MISHEARD or not mark.heard or not is_learnable_mixup(meant):
                continue
            # When every other engine also missed the word, the speaker most likely said it that
            # way ("could" for "should", "test" for "tests"). Correcting it later would be wrong.
            confirmed = any(i < len(o.words) and o.words[i].status == OK for o in others)
            if others and not confirmed:
                continue
            seen.setdefault((mark.heard.lower(), meant.lower()), (mark.heard, meant, confirmed))
    return list(seen.values())
