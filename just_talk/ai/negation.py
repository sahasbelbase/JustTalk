"""Does a Nepali (or Nepali-English) sentence say "not", and does its English translation?

Rules, not a model, so they are fast and their mistakes can be read. Copied from Just Notes
(lab/translate_bench/negation.py), where run.py measures them on 40 minimal pairs (pairs.jsonl).

Nepali "not" shows up as:
- the copula and its tenses: छैन (and छैनन्, छैनौँ), होइन/हैन, थिएन
- the negative habitual/future: -दैन, -दिनँ, -न्नँ (जान्नँ), हुन्न (पठाउनुहुन्न, हुनुहुन्नथ्यो)
- the negative past: -एन, -ेन (गरेन, भएन), -नन् (गरिनन्, खाएनन्), -िनँ (गरिनँ), -ेनौँ (भेटेनौँ)
- the prefix न- on a verb: नभन्नू, नखान, नगर्ने, नभएका (a list of common verb stems, see _PREFIX).
The traps are affirmative look-alikes: गरिन्, पठाइन्, तिरिन् ("she did/sent/paid") end in -इन्, not -इनन्.
"""

from __future__ import annotations

import re

_WORD = re.compile("[\u0900-\u0963\u0966-\u097F]+")  # Devanagari letters, without the danda (।, ॥)
_SUFFIX = re.compile(r"(छैन|छैनन्|छैनौँ|छैनौं|छैनौ|छैनस्|होइन|हैन|थिएन|थिएनन्|थिइन|थिइनँ|दैन|दैनन्|दैनौँ|दैनौं|दैनौ|दिनँ|न्नँ|"
                     r"एन|ेन|नन्|िनँ|इनँ|एनौँ|एनौं|ेनौँ|ेनौं|एनौ|ेनौ)$")
_CONTAINS = re.compile(r"हुन्न|छैन")
# न + a verb stem: नभएका, नहोस्, नसकी, नगर्दा, नभुल्नुहोला, नखान. A stem list, not "any word starting
# with न", because नदी (river), नगर (city), नयाँ (new), नजिक (near) and names start the same way.
# गर needs a following ्, े, ि or ा so that नगर, नगरको, नगरपालिका (city) stay out.
_PREFIX = re.compile(r"^न(भए|भै|भइ|भई|मार्|भन|भ[ुू]ल|हो|हु|सक|पा|पर|रह|लाग|बित|लि|मान|चाह|दिए|दिन|दिई|दिँ|जा|आ|खा|बुझ|देख|"
                     r"ल्या|छोड|राख|बस|गए|चल|सुन|फर्क|लेख|बोल|पढ|खेल|मिल|बिर्स|उठ|गर[्ेिा])")
# Words that look negated but aren't, found by running these rules over the SLR54 transcripts
_PREFIX_NOT = {"नरहरि", "नलिनी", "नलिन"}  # names that start like न + a verb stem
_EN_NAMES = {"भीमसेन", "जयसेन", "कारमेन", "एलेन", "सिएनएन", "आईएसबीएन", "एएसइएएन"}
_VIRAMA = "\u094d"
_NAN_BEFORE = set("िेैएइ")  # -नन् is a negative verb after these: गरिनन्, छोडेनन्, छैनन्, खाएनन्, होइनन्


def _loanword(w: str) -> bool:
    """English and other names ending in -en (स्पेन, ब्रिटेन, क्रेन, सेन) that the -ेन rule would take for a
    negative past: very short words, a consonant cluster or ट right before the ending, and known names."""
    if w in _EN_NAMES or w.endswith("टेन") or len(w) <= 3:
        return True
    return w.endswith("ेन") and len(w) >= 4 and w[-4] == _VIRAMA

_EN = re.compile(r"\b(not|no|never|nobody|none|nothing|neither|nor|without|unable|cannot|absent|fail(ed|s)?|"
                 r"refus\w*|declin\w*|reject\w*|den(y|ied|ies)|miss(ed|es)?)\b|n't\b", re.IGNORECASE)


def nepali_cues(text: str) -> list:
    out = []
    for w in _WORD.findall(text):
        if w in _PREFIX_NOT:
            continue
        suffix = _SUFFIX.search(w) and not (w.endswith(("ेन", "एन")) and _loanword(w))
        if suffix and w.endswith("नन्") and w[-4:-3] not in _NAN_BEFORE:  # हनन्, प्रजनन् are nouns
            suffix = False
        prefix = _PREFIX.match(w)
        if suffix or _CONTAINS.search(w) or prefix:
            out.append(w)
    return out


def english_cues(text: str) -> list:
    return [m.group(0) for m in _EN.finditer(text.replace("’", "'"))]


def says_not(text: str) -> bool:
    return bool(nepali_cues(text) or english_cues(text))


def flipped(source: str, english: str) -> bool:
    """The translation lost a "not" the speaker said, or added one they didn't. The source counts
    English words too, since mixed speech keeps them ("approve गर्दिनँ", "not ready छ")."""
    return says_not(source) != bool(english_cues(english))
