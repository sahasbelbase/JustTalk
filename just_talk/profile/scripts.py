"""Sentences the user reads during voice setup.

English sentences lean on sounds Nepali speakers often say differently from US/UK English
(v/w/b, f/ph, z/j, s/sh, th, and the extra vowel in "school" → "iskul"), so the profile
learns how *this* speaker says them. Nepali is shown in Devanagari; Nepglish is shown the way
people text it (Romanized Nepali with English words), since that's how they'd say it.
Role sentences carry the jargon of the user's work ("push to git" must not become "push to
gate"), and the role's terms also go into the vocabulary the engines are primed with.
Numbers are avoided because engines write them as digits or words unpredictably.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Dict, List, Tuple

EN = "en"
NE = "ne"
MIXED = "ne_en"


@dataclass(frozen=True)
class Prompt:
    id: str
    text: str
    language: str
    kind: str = "base"  # "base", "role", "word" (the user's own names and terms), "followup", "extra"
    focus: str = ""     # sound a follow-up concentrates on


BASE: Dict[str, List[Prompt]] = {
    EN: [
        Prompt("en1", "I will visit the village on Wednesday with my whole family.", EN),
        Prompt("en3", "She should check the schedule and share it with everyone.", EN),
        Prompt("en4", "I think this thing will work better on the third floor.", EN),
        Prompt("en5", "The school station is a short walk from the main street.", EN),
        Prompt("en6", "The zoo was very crowded, so we went home early.", EN),
    ],
    NE: [
        Prompt("ne1", "म भोलि अफिस जान्छु अनि रिपोर्ट पठाउँछु।", NE),
        Prompt("ne2", "आज बिहान हामीले नयाँ योजनाबारे छलफल गर्यौं।", NE),
        Prompt("ne3", "कृपया यो कागजात साँझ अगाडि पठाइदिनुहोस्।", NE),
    ],
    MIXED: [
        Prompt("mx1", "Aaja ko meeting ma hami project ko update discuss garchau.", MIXED),
        Prompt("mx2", "Malai tyo file email ma pathaidinu na.", MIXED),
        Prompt("mx3", "Yo feature bholi samma deploy garna sakinchha.", MIXED),
    ],
}


@dataclass(frozen=True)
class Role:
    id: str
    label: str
    terms: Tuple[str, ...]          # added to the vocabulary the engines and AI cleanup see
    english: Tuple[str, ...] = ()   # read when the user speaks English
    mixed: Tuple[str, ...] = ()     # read when the user speaks Nepali and English


ROLES: List[Role] = [
    Role(
        "software", "Software engineer",
        ("git", "GitHub", "pull request", "commit", "merge", "branch", "deploy", "staging",
         "API", "JSON", "backend", "frontend", "database", "Docker", "refactor", "repo"),
        english=(
            "Push the fix to git and open a pull request on GitHub.",
            "The API returns an empty JSON object when the cache is cold.",
            "Run the tests locally, then deploy the build to staging.",
        ),
        mixed=(
            "Yo branch lai main ma merge garera deploy garchu.",
            "Bug fix garera git ma push gardinu na.",
        ),
    ),
    Role(
        "design", "Designer",
        ("Figma", "prototype", "wireframe", "typography", "mockup", "component", "design system",
         "UI", "UX", "spacing", "layout", "icon"),
        english=(
            "I updated the Figma prototype with the new typography.",
            "The wireframe needs more white space around the header.",
            "Let's review the user flow before the client presentation.",
        ),
        mixed=(
            "Figma ma naya mockup update gareko chu.",
            "Yo component ko spacing ali badhaunu parcha.",
        ),
    ),
    Role(
        "product", "Product or project manager",
        ("roadmap", "sprint", "backlog", "stakeholder", "Jira", "standup", "retro", "milestone",
         "deliverable", "OKR", "KPI", "deadline"),
        english=(
            "Add this ticket to the sprint backlog in Jira.",
            "The stakeholders want the roadmap before the quarterly review.",
            "We moved the milestone because the deliverable slipped.",
        ),
        mixed=(
            "Bholi ko standup ma sprint ko update dinu parcha.",
            "Yo ticket lai backlog ma rakhdinu.",
        ),
    ),
    Role(
        "student", "Student or researcher",
        ("assignment", "thesis", "semester", "lecture", "professor", "citation", "research paper",
         "abstract", "methodology", "exam", "GPA"),
        english=(
            "I need to submit the assignment before the lecture on Friday.",
            "The professor asked for a citation in the methodology section.",
            "My thesis abstract is due at the end of the semester.",
        ),
        mixed=(
            "Assignment ko deadline bholi samma ho.",
            "Professor le thesis ko draft pathaunu bhannu bhayo.",
        ),
    ),
    Role(
        "health", "Healthcare",
        ("patient", "prescription", "diagnosis", "dosage", "milligram", "blood pressure", "ICU",
         "ECG", "follow-up", "discharge", "symptoms", "antibiotics"),
        english=(
            "The patient's blood pressure was normal after the dosage change.",
            "Please add the prescription to the discharge notes.",
            "Symptoms improved after a week of antibiotics.",
        ),
        mixed=(
            "Patient ko blood pressure aaja normal cha.",
            "Prescription ma dosage milaunu parcha.",
        ),
    ),
    Role(
        "business", "Business, sales or marketing",
        ("invoice", "client", "proposal", "quotation", "revenue", "campaign", "leads", "CRM",
         "follow-up", "conversion", "LinkedIn"),
        english=(
            "Send the proposal and the invoice to the client today.",
            "The campaign brought in more leads than last month.",
            "Update the CRM after every follow-up call.",
        ),
        mixed=(
            "Client lai quotation pathaisakeko chu.",
            "Yo campaign le dherai leads lyayo.",
        ),
    ),
    Role(
        "finance", "Finance or accounting",
        ("ledger", "reconciliation", "VAT", "TDS", "balance sheet", "audit", "fiscal year",
         "payroll", "depreciation", "receivable", "payable", "invoice"),
        english=(
            "The ledger reconciliation must be done before the audit.",
            "Please check the tax on this invoice again.",
            "Payroll for this fiscal year is almost closed.",
        ),
        mixed=(
            "Fiscal year sakinu aghi audit garnu parcha.",
            "Yo invoice ma tax milaunu parcha.",
        ),
    ),
    Role(
        "creator", "Writer or creator",
        ("draft", "headline", "script", "thumbnail", "caption", "upload", "YouTube", "Instagram",
         "newsletter", "publish", "SEO"),
        english=(
            "I finished the draft and wrote a better headline.",
            "Upload the video with the new thumbnail and caption.",
            "Schedule the newsletter for Monday morning.",
        ),
        mixed=(
            "YouTube ma video upload garera caption lekhnu parcha.",
            "Yo script ko draft bholi pathauchu.",
        ),
    ),
]
ROLES_BY_ID: Dict[str, Role] = {r.id: r for r in ROLES}

# One per sound, added when that sound was misheard in the base sentences.
FOLLOWUPS: Dict[str, List[Prompt]] = {
    "v_w": [Prompt("fv1", "We have very valuable work waiting for us this week.", EN, "followup", "v_w")],
    "f": [Prompt("ff1", "Five friends found a fine coffee shop near the office.", EN, "followup", "f")],
    "z": [Prompt("fz1", "The lazy dog was dozing near the busy zebra crossing.", EN, "followup", "z")],
    "th": [Prompt("ft1", "They thought the thunder was coming from the north.", EN, "followup", "th")],
    "sh": [Prompt("fs1", "Sharma shared fresh fish at the shop on Sunday.", EN, "followup", "sh")],
    "s_cluster": [Prompt("fc1", "Speak slowly and stay steady when you start the speech.", EN, "followup", "s_cluster")],
}

# "Keep training" draws from these once the base set is done.
EXTRA: Dict[str, List[Prompt]] = {
    EN: [
        Prompt("ex1", "Please send the final file to the team before the weekend.", EN, "extra"),
        Prompt("ex2", "Can we move the review meeting to Thursday afternoon?", EN, "extra"),
        Prompt("ex3", "Let me know when the invoice is ready to review.", EN, "extra"),
        Prompt("ex4", "Thanks for the quick reply, that really helps.", EN, "extra"),
        Prompt("ex5", "Could you forward the slides to the whole group?", EN, "extra"),
    ],
    NE: [
        Prompt("nx1", "हामी अर्को हप्ता पोखरा घुम्न जाँदैछौं।", NE, "extra"),
        Prompt("nx2", "तपाईंलाई भेटेर धेरै खुसी लाग्यो।", NE, "extra"),
        Prompt("nx3", "यो काम आज साँझसम्म सकिन्छ।", NE, "extra"),
        Prompt("nx4", "मलाई अलि ढिलो हुन्छ, पर्खिनुहोला।", NE, "extra"),
    ],
    MIXED: [
        Prompt("mxx1", "Team lai bhanne ki code review bholi huncha.", MIXED, "extra"),
        Prompt("mxx2", "Client lai invoice pathaisakeko chu.", MIXED, "extra"),
        Prompt("mxx3", "Bholi ko standup ma sabai join garnu hai.", MIXED, "extra"),
    ],
}

WORD_TEMPLATES: Dict[str, List[str]] = {
    EN: [
        "Please send this to {w} today.",
        "I talked with {w} this morning.",
        "Can you add {w} to the list?",
    ],
    NE: [
        "{w} लाई यो सन्देश पठाइदिनुहोस्।",
        "आज {w} सँग कुरा भयो।",
    ],
}

MAX_PERSONAL_WORDS = 3


def _starts_with_s_cluster(w: str) -> bool:
    return bool(re.match(r"s[ptkcmnlw]", w))


# Which English spellings carry each sound.
SOUND_FOCUS: Dict[str, Callable[[str], bool]] = {
    "v_w": lambda w: "v" in w or w.startswith("w"),
    "f": lambda w: "f" in w or "ph" in w,
    "z": lambda w: "z" in w,
    "th": lambda w: "th" in w,
    "sh": lambda w: "sh" in w or ("ch" in w and not w.startswith("sch")),
    "s_cluster": _starts_with_s_cluster,
}


def focus_of(word: str) -> List[str]:
    w = re.sub(r"[^a-z]", "", word.lower())
    return [name for name, test in SOUND_FOCUS.items() if w and test(w)]


def word_prompts(words: List[str], languages: List[str]) -> List[Prompt]:
    """Short sentences built around the user's own names and terms."""
    lang = EN if EN in languages else NE
    templates = WORD_TEMPLATES[lang]
    prompts = []
    for i, w in enumerate([w.strip() for w in words if w.strip()][:MAX_PERSONAL_WORDS]):
        prompts.append(Prompt(f"w{i}", templates[i % len(templates)].format(w=w), lang, "word"))
    return prompts


def role_prompts(role_id: str, language: str) -> List[Prompt]:
    role = ROLES_BY_ID.get(role_id)
    if role is None:
        return []
    texts = role.english if language == EN else role.mixed if language == MIXED else ()
    return [Prompt(f"{role.id}-{language}{i}", t, language, "role") for i, t in enumerate(texts)]


def role_terms(role_id: str) -> List[str]:
    role = ROLES_BY_ID.get(role_id)
    return list(role.terms) if role else []


SEED_UNTIL_TERMS = 8  # the role's built-in words are only a day-one seed, until this many are learned


def vocabulary_terms(config, learner=None) -> List[str]:
    """What the speech engines are primed with: words the user typed in, words learned from
    their own speech and dictations, and (until enough are learned) their field's seed words."""
    own = [w.strip() for w in (getattr(config, "custom_vocabulary", "") or "").split(",") if w.strip()]
    learned = learner.known_terms() if learner is not None else []
    seed = role_terms(getattr(config, "user_role", "")) if len(learned) < SEED_UNTIL_TERMS else []
    return list(dict.fromkeys(own + learned + seed))


# Apple hears "git" as "get" or "gate", and the on-device model can't tell which was meant. Fixed
# only where git is the one sensible reading, after a version-control verb ("push the changes to
# get"), and only for people who use the word: "get the file" is left alone.
_GIT_MISHEARD = re.compile(
    r"\b((?:push|pushed|pushing|pull|pulled|pulling|commit|committed|merge|merged|clone|cloned)\b"
    r"[^.?!]{0,40}?\b(?:to|from|in|into|on|with)\s+)(?:the\s+)?(?:get|gate)\b",
    re.IGNORECASE,
)
_GITHUB_MISHEARD = re.compile(r"\b(?:get|git)\s?hub\b", re.IGNORECASE)


def fix_known_mishearings(text: str, terms) -> str:
    words = {t.lower() for t in terms}
    if "git" in words:
        text = _GIT_MISHEARD.sub(lambda m: m.group(1) + "git", text)
    if "github" in words:
        text = _GITHUB_MISHEARD.sub("GitHub", text)
    return text
