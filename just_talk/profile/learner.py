"""Learns each user's own words and the speech engine's mix-ups from their own data.

Nothing here is specific to one person or field. Evidence comes from:
- voice setup: sentences the user read, scored against what each engine heard;
- every dictation: words shaped like names and jargon (GitHub, API, DMG) in the final text,
  and words AI cleanup swapped for one the user is known to use;
- an optional AI review of past dictations (text only), which can spot that "push to the
  gate" means "git" because the same person also says "git push" and "GitHub";
- the user, who can remove anything learned wrongly (it is then never learned again).

Everything is stored in the user's own app-data folder, so app updates never reset it and
every user ends up with a profile of their own accent and vocabulary.
"""

from __future__ import annotations

import json
import re
import sys
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from .scoring import align, english_key, has_devanagari, strip_word
from .store import profile_dir

# How much evidence before something learned is used. A word or mix-up seen once in passing
# can be noise; one from the AI review or the user's own fix has already been checked.
TRUSTED_SOURCES = ("review", "user", "setup-confirmed")
MIN_EVIDENCE = 2
REVIEW_EVERY = 40      # new dictations between automatic AI reviews
REVIEW_DICTATIONS = 150
MAX_TERMS = 80
MAX_MIXUPS = 30

_SHAPED_TERM = re.compile(r"^(?:[A-Z]{2,6}s?|[A-Za-z]+[A-Z][A-Za-z]*|[A-Za-z]+\d+[A-Za-z\d]*|\w+\.(?:exe|dmg|js|py|ts|md|json|io|ai|com))$")


def shaped_terms(text: str) -> List[str]:
    """Words whose shape marks them as names or jargon: GitHub, LinkedIn, API, DMG, M2, app.py.
    Lowercase jargon ("git") can't be told from ordinary words by shape; setup and review find it."""
    out = []
    for raw in (text or "").split():
        w = strip_word(raw)
        if len(w) < 2 or w in ("I", "OK", "AM", "PM", "TV", "US", "UK") or not _SHAPED_TERM.match(w):
            continue
        out.append(w)
    return out


@dataclass
class Evidence:
    count: int = 0
    sources: Tuple[str, ...] = ()
    example: str = ""

    @property
    def trusted(self) -> bool:
        return any(s in TRUSTED_SOURCES for s in self.sources) or self.count >= MIN_EVIDENCE


class Learner:
    def __init__(self, path: Optional[Path] = None):
        self.path = path or (profile_dir() / "learned.json")
        self._lock = threading.Lock()
        self.terms: Dict[str, Evidence] = {}
        self.mixups: Dict[Tuple[str, str], Evidence] = {}
        self.blocked_terms: set = set()
        self.blocked_mixups: set = set()
        self.dictations_seen = 0
        self.reviewed_at_count = 0
        self.last_review = ""

    # ── Persistence ──────────────────────────────────────────────────────────

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "Learner":
        learner = cls(path)
        try:
            data = json.loads(learner.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return learner
        except Exception as e:
            print(f"[Learner] Couldn't read {learner.path}: {e}", file=sys.stderr)
            return learner
        for t in data.get("terms", []):
            learner.terms[t["term"]] = Evidence(t.get("count", 1), tuple(t.get("sources", [])), t.get("example", ""))
        for m in data.get("mixups", []):
            learner.mixups[(m["heard"], m["meant"])] = Evidence(m.get("count", 1), tuple(m.get("sources", [])), m.get("example", ""))
        learner.blocked_terms = {t.lower() for t in data.get("blocked_terms", [])}
        learner.blocked_mixups = {(h.lower(), m.lower()) for h, m in data.get("blocked_mixups", [])}
        learner.dictations_seen = int(data.get("dictations_seen", 0))
        learner.reviewed_at_count = int(data.get("reviewed_at_count", 0))
        learner.last_review = data.get("last_review", "")
        return learner

    def save(self) -> None:
        with self._lock:
            data = {
                "terms": [{"term": t, "count": e.count, "sources": list(e.sources), "example": e.example}
                          for t, e in sorted(self.terms.items(), key=lambda kv: -kv[1].count)],
                "mixups": [{"heard": h, "meant": m, "count": e.count, "sources": list(e.sources), "example": e.example}
                           for (h, m), e in sorted(self.mixups.items(), key=lambda kv: -kv[1].count)],
                "blocked_terms": sorted(self.blocked_terms),
                "blocked_mixups": sorted([list(p) for p in self.blocked_mixups]),
                "dictations_seen": self.dictations_seen,
                "reviewed_at_count": self.reviewed_at_count,
                "last_review": self.last_review,
            }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.path)
        except Exception as e:
            print(f"[Learner] Couldn't save: {e}", file=sys.stderr)

    # ── Evidence ─────────────────────────────────────────────────────────────

    def add_term(self, term: str, source: str, example: str = "") -> None:
        term = strip_word(term)
        if not term or term.lower() in self.blocked_terms:
            return
        with self._lock:
            # One entry per word regardless of case; keep the most recent spelling
            existing = next((t for t in self.terms if t.lower() == term.lower()), None)
            ev = self.terms.pop(existing) if existing else Evidence()
            self.terms[term] = Evidence(ev.count + 1, tuple(dict.fromkeys(ev.sources + (source,))), example or ev.example)

    def add_mixup(self, heard: str, meant: str, source: str, example: str = "") -> None:
        heard, meant = strip_word(heard), strip_word(meant)
        if not heard or not meant or heard.lower() == meant.lower():
            return
        if (heard.lower(), meant.lower()) in self.blocked_mixups:
            return
        with self._lock:
            key = next((k for k in self.mixups if (k[0].lower(), k[1].lower()) == (heard.lower(), meant.lower())), (heard, meant))
            ev = self.mixups.get(key, Evidence())
            self.mixups[key] = Evidence(ev.count + 1, tuple(dict.fromkeys(ev.sources + (source,))), example or ev.example)
        self.add_term(meant, source, example)

    def forget_term(self, term: str) -> None:
        with self._lock:
            for t in [t for t in self.terms if t.lower() == term.lower()]:
                del self.terms[t]
            for k in [k for k in self.mixups if k[1].lower() == term.lower()]:
                del self.mixups[k]
            self.blocked_terms.add(term.lower())

    def forget_mixup(self, heard: str, meant: str) -> None:
        with self._lock:
            for k in [k for k in self.mixups if (k[0].lower(), k[1].lower()) == (heard.lower(), meant.lower())]:
                del self.mixups[k]
            self.blocked_mixups.add((heard.lower(), meant.lower()))

    # ── What gets used ───────────────────────────────────────────────────────

    def known_terms(self, limit: int = MAX_TERMS) -> List[str]:
        with self._lock:
            ranked = sorted(self.terms.items(), key=lambda kv: (-kv[1].trusted, -kv[1].count))
            return [t for t, e in ranked if e.trusted][:limit]

    def known_mixups(self, limit: int = MAX_MIXUPS) -> List[Tuple[str, str]]:
        with self._lock:
            ranked = sorted(self.mixups.items(), key=lambda kv: -kv[1].count)
            return [k for k, e in ranked if e.trusted][:limit]

    # ── Learning sources ─────────────────────────────────────────────────────

    def learn_from_setup(self, mishearings: Iterable[dict], words: Iterable[str] = ()) -> None:
        """Mix-ups from voice setup. confirmed=True means another engine heard the word right."""
        for m in mishearings:
            self.add_mixup(m["heard"], m["meant"], "setup-confirmed" if m.get("confirmed") else "setup")
        for w in words:
            self.add_term(w, "user")
        self.save()

    def observe_dictation(self, raw: str, final: str, translated: bool = False) -> None:
        """Learn from one finished dictation, locally. A translated dictation still teaches the
        user's words (from the English text), but its words don't line up with what was said."""
        with self._lock:
            self.dictations_seen += 1
        for term in shaped_terms(final):
            self.add_term(term, "dictation", final[:120])
        if raw and final and raw != final and not translated and not has_devanagari(raw + final):
            known = {t.lower() for t in self.terms}
            raw_words, final_words = raw.split(), final.split()
            for op, i, j in align([english_key(w) for w in raw_words], [english_key(w) for w in final_words]):
                if op != "~":
                    continue
                heard, meant = strip_word(raw_words[i]), strip_word(final_words[j])
                # Only swaps into a word this user is known to use count; anything else is ordinary editing
                if meant.lower() in known and heard.lower() not in known:
                    self.add_mixup(heard, meant, "cleanup", final[:120])
        self.save()

    def review_due(self) -> bool:
        return self.dictations_seen - self.reviewed_at_count >= REVIEW_EVERY

    def review(self, dictations: List[Tuple[str, str]], ask: Callable[[str, str], Optional[str]]) -> Tuple[int, int]:
        """Ask an AI model to find this user's terms and the engine's mix-ups in past dictations.

        dictations: (raw, final) pairs, newest first. ask(system, user) returns the reply text.
        Returns how many terms and mix-ups were learned.
        """
        lines = []
        seen = set()
        for raw, final in dictations[:REVIEW_DICTATIONS]:
            raw, final = (raw or "").strip()[:300], (final or "").strip()[:300]
            if not raw or (raw, final) in seen:
                continue
            seen.add((raw, final))
            lines.append(f"RAW: {raw}\nFINAL: {final}" if final and final != raw else f"RAW: {raw}")
        if not lines:
            return 0, 0
        reply = ask(REVIEW_PROMPT, "\n\n".join(lines))
        parsed = _parse_json(reply or "")
        if parsed is None:
            print(f"[Learner] Review reply wasn't JSON: {(reply or '')[:200]!r}", file=sys.stderr)
            return 0, 0
        terms = [t for t in parsed.get("terms", []) if isinstance(t, str)][:MAX_TERMS]
        mixups = [m for m in parsed.get("mixups", []) if isinstance(m, dict)][:MAX_MIXUPS]
        for t in terms:
            self.add_term(t, "review")
        added = 0
        for m in mixups:
            heard, meant = str(m.get("heard", "")), str(m.get("meant", ""))
            if heard and meant:
                self.add_mixup(heard, meant, "review", str(m.get("evidence", ""))[:160])
                added += 1
        with self._lock:
            self.reviewed_at_count = self.dictations_seen
            self.last_review = datetime.now().isoformat(timespec="seconds")
        self.save()
        return len(terms), added


REVIEW_PROMPT = """You help a dictation app learn one person's vocabulary.
Below are their dictations. RAW is what the speech engine wrote (Nepali speech is written in Devanagari, often with English words spelled in Devanagari); FINAL (when present) is the text after cleanup or translation to English.

Reply with JSON only, no prose, in exactly this shape:
{"terms": ["..."], "mixups": [{"heard": "...", "meant": "...", "evidence": "..."}]}

"terms": names, products, tools, commands and specialised words this person really uses, spelled the way they should be written (for example "git", "GitHub", "LinkedIn"). At most 40. Leave out ordinary everyday words.
"mixups": places where the speech engine (or the translation) wrote a different, similar-sounding word instead of one of those terms, and the surrounding words make the intended term clear (for example "push to the gate" meant "git", or Devanagari "गेट" in "पुस द चेन्जेस टु द गेट" meant "git"). "heard" is the wrong word exactly as written (in any script), "meant" is the intended term, "evidence" is a short quote. At most 20.
Never list grammar fixes, filler words, style changes, or guesses without clear context. An empty list is fine."""


def _parse_json(text: str) -> Optional[dict]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```\w*\s*|\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None
