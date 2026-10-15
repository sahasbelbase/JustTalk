"""Score a read-aloud take against the sentence the user was shown.

Engines disagree on spelling (Kriti writes मिटिङ for "meeting"), on word breaks (आजको for
"aaja ko") and even on script, so a plain word comparison would call most Nepali takes wrong.
Each word is compared through a key that suits the pair of scripts involved:

- English vs English: whole words, lower-cased (standard word error rate).
- Devanagari vs Devanagari: characters, ignoring spelling variants people use interchangeably
  (ि/ी, ु/ू, श/ष/स, ब/व, and nasal marks that are often left out).
- Anything mixed (Romanized Nepali, Nepglish, English heard as Devanagari): a consonant
  skeleton that both scripts reduce to, so "meeting" and "मिटिङ" both become "mtng".

Every expected word ends up "ok", "misheard" or "missed"; that drives the live highlight, the
accuracy score and the list of words the app learns to correct.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Sequence, Tuple

OK = "ok"
MISHEARD = "misheard"
MISSED = "missed"

_PUNCT = "\"'“”‘’.,!?;:()[]{}<>…–—-/\\|।॥*_~`"
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_LATIN = re.compile(r"[A-Za-z]")


def has_devanagari(text: str) -> bool:
    return bool(_DEVANAGARI.search(text or ""))


def has_latin(text: str) -> bool:
    return bool(_LATIN.search(text or ""))


def strip_word(word: str) -> str:
    return word.strip(_PUNCT + " ")


# ── Keys ──────────────────────────────────────────────────────────────────────

_NUMBER_WORDS = {
    str(i): w for i, w in enumerate(
        "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
        "fifteen sixteen seventeen eighteen nineteen twenty".split()
    )
}
_NUMBER_WORDS.update({"30": "thirty", "40": "forty", "50": "fifty", "60": "sixty", "70": "seventy",
                      "80": "eighty", "90": "ninety", "100": "hundred"})


def english_key(word: str) -> str:
    key = re.sub(r"[^a-z0-9]", "", strip_word(word).lower())
    return _NUMBER_WORDS.get(key, key)  # engines write "10" for "ten"


_DEV_LENIENT = str.maketrans({
    "ँ": None, "ं": None, "ी": "ि", "ू": "ु", "ई": "इ", "ऊ": "उ",
    "श": "स", "ष": "स", "व": "ब", "ण": "न",
    "़": None, "्": None, "‌": None, "‍": None,
})


def devanagari_key(word: str) -> str:
    return unicodedata.normalize("NFD", strip_word(word)).translate(_DEV_LENIENT)


_DEV_SKELETON = {
    "क": "k", "ख": "k", "ग": "g", "घ": "g", "ङ": "ng",
    "च": "c", "छ": "c", "ज": "j", "झ": "j", "ञ": "n",
    "ट": "t", "ठ": "t", "ड": "t", "ढ": "t", "ण": "n",
    "त": "t", "थ": "t", "द": "t", "ध": "t", "न": "n",
    "प": "p", "फ": "p", "ब": "b", "भ": "b", "म": "m",
    "य": "y", "र": "r", "ल": "l", "व": "b",
    "श": "s", "ष": "s", "स": "s", "ह": "h",
}
_DEV_DIGITS = {chr(0x0966 + i): str(i) for i in range(10)}
_LATIN_ASPIRATED = {"s": "s", "k": "k", "g": "g", "t": "t", "d": "t", "p": "p", "b": "b", "j": "j"}
_LATIN_SINGLE = {"f": "p", "v": "b", "w": "b", "z": "j", "q": "k", "x": "ks", "d": "t"}


def _collapse(chars: List[str]) -> str:
    out: List[str] = []
    for c in "".join(chars):
        if not out or out[-1] != c:
            out.append(c)
    return "".join(out)


def _devanagari_skeleton(word: str) -> str:
    out: List[str] = []
    chars = unicodedata.normalize("NFD", word)
    for i, ch in enumerate(chars):
        if ch in _DEV_DIGITS:
            out.append(_DEV_DIGITS[ch])
            continue
        if ch in "ंँ":
            nasal_before_consonant = i + 1 < len(chars) and chars[i + 1] in _DEV_SKELETON
            if nasal_before_consonant:
                out.append("n")  # पठाउँछु is written "pathaunchu" in Roman script
            continue
        c = _DEV_SKELETON.get(ch)
        if c is None:
            continue  # vowels, vowel signs, virama
        if c in ("y", "h") and out:
            continue  # only kept at the start of a word, as in the Latin rules below
        out.append(c)
    return _collapse(out)


def _latin_skeleton(word: str) -> str:
    w = word.lower()
    out: List[str] = []
    i = 0
    while i < len(w):
        ch = w[i]
        nxt = w[i + 1] if i + 1 < len(w) else ""
        if ch == "c":
            if nxt == "h":
                out.append("c")
                i += 3 if w[i + 2 : i + 3] == "h" else 2  # chh / ch
                continue
            if nxt == "k":
                out.append("k")
                i += 2
                continue
            out.append("s" if nxt and nxt in "eiy" else "k")
            i += 1
            continue
        if ch == "t" and nxt == "u" and w[i + 2 : i + 3] in ("r", "a", "e", "i", "o"):
            out.append("c")  # "feature", "picture", "actual" are said with a ch sound
            i += 1
            continue
        if nxt == "h" and ch in _LATIN_ASPIRATED:
            out.append(_LATIN_ASPIRATED[ch])
            i += 2
            continue
        if ch in "aeiou" or not ch.isalnum():
            i += 1
            continue
        if ch in ("y", "h"):
            if not out:
                out.append(ch)
            i += 1
            continue
        out.append(_LATIN_SINGLE.get(ch, ch))
        i += 1
    return _collapse(out)


def skeleton_key(word: str) -> str:
    """Script-independent consonant skeleton: "meeting", "miting" and "मिटिङ" all give "mtng"."""
    w = strip_word(word)
    if has_devanagari(w):
        return _devanagari_skeleton(w)
    return _latin_skeleton(w)


def sound_overlap(english: str, devanagari: str) -> float:
    """How much of a Devanagari transcript an English transcript of the same audio accounts for,
    by sound (0..1). High when the speaker said English that Kriti spelled in Devanagari ("पुस द
    चेन्जेस टु द गिट" vs "push the changes to git"); low when the English is a guess at Nepali."""
    a = "".join(skeleton_key(w) for w in (english or "").split())
    b = "".join(skeleton_key(w) for w in (devanagari or "").split())
    if not a or not b:
        return 0.0
    matched = sum(1 for op, _, _ in align(b, a) if op == "=")
    return matched / max(len(a), len(b))


# ── Alignment ─────────────────────────────────────────────────────────────────

def align(a: Sequence, b: Sequence) -> List[Tuple[str, Optional[int], Optional[int]]]:
    """Levenshtein alignment. Ops: "=" match, "~" substitution, "-" only in a, "+" only in b."""
    n, m = len(a), len(b)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        dp[i][0] = i
    for j in range(m + 1):
        dp[0][j] = j
    for i in range(1, n + 1):
        ai, row, prev = a[i - 1], dp[i], dp[i - 1]
        for j in range(1, m + 1):
            row[j] = min(prev[j - 1] + (ai != b[j - 1]), prev[j] + 1, row[j - 1] + 1)

    ops: List[Tuple[str, Optional[int], Optional[int]]] = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and dp[i][j] == dp[i - 1][j - 1] + (a[i - 1] != b[j - 1]):
            ops.append(("=" if a[i - 1] == b[j - 1] else "~", i - 1, j - 1))
            i, j = i - 1, j - 1
        elif i > 0 and dp[i][j] == dp[i - 1][j] + 1:
            ops.append(("-", i - 1, None))
            i -= 1
        else:
            ops.append(("+", None, j - 1))
            j -= 1
    ops.reverse()
    return ops


# ── Scoring ───────────────────────────────────────────────────────────────────

@dataclass
class WordMark:
    text: str  # the word as shown to the user, punctuation included
    status: str = MISSED
    heard: str = ""  # what the engine wrote instead (misheard words only)


@dataclass
class TakeScore:
    words: List[WordMark] = field(default_factory=list)
    inserted: int = 0
    mode: str = "english"

    @property
    def accuracy(self) -> float:
        """Share of words heard right; extra words the engine invented count against it."""
        scored = len(self.words)
        if scored == 0:
            return 0.0
        ok = sum(1 for w in self.words if w.status == OK)
        return ok / (scored + self.inserted)

    @property
    def frontier(self) -> int:
        """Index of the last word the engine has reached (-1 if none), for the live highlight."""
        for i in range(len(self.words) - 1, -1, -1):
            if self.words[i].status != MISSED:
                return i
        return -1

    @property
    def mishearings(self) -> List[Tuple[str, str]]:
        """(heard, meant) pairs, e.g. ("bery", "very")."""
        return [(w.heard, strip_word(w.text)) for w in self.words if w.status == MISHEARD and w.heard]


def choose_mode(language: str, expected: str, heard: str) -> str:
    text = f"{expected} {heard}"
    if not has_devanagari(text) and language == "en":
        return "english"
    if not has_latin(text):
        return "devanagari"
    return "skeleton"


def score_take(expected: str, heard: str, language: str = "en") -> TakeScore:
    display = expected.split()
    heard_words = [w for w in (heard or "").split() if strip_word(w)]
    mode = choose_mode(language, expected, heard or "")
    if mode == "english":
        return _score_words(display, heard_words)
    key = devanagari_key if mode == "devanagari" else skeleton_key
    return _score_chars(display, heard_words, key, mode)


def _rejoin(exp_keys: List[str], heard_words: List[str]) -> Tuple[List[str], List[str]]:
    """Engines split and join compounds differently ("Git Hub" / "GitHub", "white space" /
    "whitespace"); line the heard words up with the sentence's choice before comparing."""
    expected = set(exp_keys)
    pairs = {a + b: (a, b) for a, b in zip(exp_keys, exp_keys[1:])}
    keys: List[str] = []
    words: List[str] = []
    j = 0
    while j < len(heard_words):
        k = english_key(heard_words[j])
        nxt = english_key(heard_words[j + 1]) if j + 1 < len(heard_words) else ""
        if nxt and k + nxt in expected and (k not in expected or nxt not in expected):
            keys.append(k + nxt)
            words.append(f"{strip_word(heard_words[j])} {strip_word(heard_words[j + 1])}")
            j += 2
            continue
        if k not in expected and k in pairs:
            keys.extend(pairs[k])
            words.extend([strip_word(heard_words[j])] * 2)
        else:
            keys.append(k)
            words.append(heard_words[j])
        j += 1
    return keys, words


def _score_words(display: List[str], heard_words: List[str]) -> TakeScore:
    exp_idx = [i for i, w in enumerate(display) if english_key(w)]
    exp_keys = [english_key(display[i]) for i in exp_idx]
    heard_keys, heard_words = _rejoin(exp_keys, heard_words)
    marks = [WordMark(w) for w in display]
    inserted = 0
    for op, i, j in align(exp_keys, heard_keys):
        if op == "=":
            marks[exp_idx[i]].status = OK
        elif op == "~":
            marks[exp_idx[i]].status = MISHEARD
            marks[exp_idx[i]].heard = strip_word(heard_words[j])
        elif op == "+":
            inserted += 1
    _fill_unscored(marks, [i for i, w in enumerate(display) if not english_key(w)])
    return TakeScore(words=marks, inserted=inserted, mode="english")


def _score_chars(display: List[str], heard_words: List[str], key: Callable[[str], str], mode: str) -> TakeScore:
    # Concatenate keys without separators so word-break differences don't matter.
    exp_chars: List[str] = []
    exp_owner: List[int] = []
    for i, w in enumerate(display):
        for c in key(w):
            exp_chars.append(c)
            exp_owner.append(i)
    heard_chars: List[str] = []
    heard_owner: List[int] = []
    for j, w in enumerate(heard_words):
        for c in key(w):
            heard_chars.append(c)
            heard_owner.append(j)

    matched = [0] * len(display)
    extra = [0] * len(display)  # heard characters inserted inside a word ("मा" for "म")
    touched: List[set] = [set() for _ in display]
    heard_used = [0] * len(heard_words)
    heard_total = [0] * len(heard_words)
    for j in heard_owner:
        heard_total[j] += 1
    ops = align(exp_chars, heard_chars)
    for k, (op, i, j) in enumerate(ops):
        if i is not None and j is not None:
            owner = exp_owner[i]
            touched[owner].add(heard_owner[j])
            heard_used[heard_owner[j]] += 1
            if op == "=":
                matched[owner] += 1
        elif op == "+":
            owner = _insertion_owner(ops, k, exp_owner, heard_owner)
            if owner is not None:
                extra[owner] += 1

    marks = [WordMark(w) for w in display]
    unscored = []
    for i, w in enumerate(display):
        n = len(key(w))
        if n == 0:
            unscored.append(i)
            continue
        if mode == "devanagari":
            # Spelling variants are already folded into the key, so anything left is a real miss.
            heard_ok = matched[i] == n and extra[i] == 0
        else:
            # Skeletons are lossy (no vowels, merged t/d), so allow one slip in long words.
            heard_ok = matched[i] == n or (n >= 5 and matched[i] >= n - 1)
        if heard_ok:
            marks[i].status = OK
        elif touched[i]:
            marks[i].status = MISHEARD
            marks[i].heard = " ".join(strip_word(heard_words[j]) for j in sorted(touched[i]))
    _fill_unscored(marks, unscored)
    # A heard word counts as invented when most of its characters lined up with nothing.
    inserted = sum(1 for j, total in enumerate(heard_total) if total and heard_used[j] * 2 < total)
    return TakeScore(words=marks, inserted=inserted, mode=mode)


def _insertion_owner(ops, k: int, exp_owner: List[int], heard_owner: List[int]) -> Optional[int]:
    """The expected word an inserted heard character sits inside, if it shares a heard word with it."""
    j = ops[k][2]
    for step in (-1, 1):
        n = k + step
        while 0 <= n < len(ops):
            _, i2, j2 = ops[n]
            if i2 is not None and j2 is not None:
                if heard_owner[j2] == heard_owner[j]:
                    return exp_owner[i2]
                break
            n += step
    return None


def _fill_unscored(marks: List[WordMark], unscored: List[int]) -> None:
    """Words with no key (a lone "—", or "a"/"I" in skeleton mode) follow their neighbour."""
    for i in unscored:
        neighbour = next((marks[k] for k in range(i - 1, -1, -1) if k not in unscored), None)
        if neighbour is None:
            neighbour = next((marks[k] for k in range(i + 1, len(marks)) if k not in unscored), None)
        marks[i].status = OK if neighbour is None else neighbour.status
        marks[i].heard = ""
