"""On-device AI for dictation cleanup and translation to English (llama.cpp, no cloud).

Speed comes from four things:
- llama.cpp on the GPU (Metal on Macs): ~6x faster than CTranslate2's CPU path;
- a short, fixed system prompt, so llama.cpp reuses its KV cache across calls
  (re-reading the full cloud prompt each time cost 2-5 s before the first word);
- greedy decoding with an output cap tied to the input length and a light repeat penalty,
  which stops small models looping ("all all all ...") — worst case went from 3.3 s to 1.3 s;
- staying loaded while the user is active (the app's idle unloader frees it later).

The model is Just Talk's own fine-tune of Qwen3-1.7B (MODEL_FILE). Anything that fails the
sanity checks below is rejected so the caller keeps the raw draft (or asks the cloud model).
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
import threading
from pathlib import Path
from typing import Callable, Optional, Tuple

try:
    from .negation import flipped
except ImportError:  # loaded on its own by the training scripts, which score the model without the check
    flipped = None

# The model the app downloads: Just Talk's fine-tune of Qwen3-1.7B, hosted on Hugging Face.
MODEL_REPO = "SahasBelbase/justtalk-qwen3-1.7b-gguf"
MODEL_FILE = "justtalk-qwen3-1.7b-v6.2-Q8_0.gguf"
MODEL_URL = f"https://huggingface.co/{MODEL_REPO}/resolve/main/{MODEL_FILE}"
MODEL_SHA256 = "f5cca61f76b4e9a5195f1345f52ae3dd19f05670e82ffa9140b5e6521989980e"
MODEL_SIZE = 1834426656
MODEL_DOWNLOAD_MB = round(MODEL_SIZE / 1e6)
# Older models already on disk, best first: they keep working until MODEL_FILE has downloaded
OLDER_MODEL_FILES = ("justtalk-qwen3-1.7b-v2-Q4_K_M.gguf", "Qwen3-1.7B-Q8_0.gguf")

_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_PROMPT_LEAKS = ("output only", "keep every detail", "this dictation", "<think", "</think", "translate this")

SYSTEM = {
    # The prompts the tuned model was trained with. Don't list "na" or "like" as fillers: न is
    # Nepali for "not"/"please", and "like" is often a real word.
    "translate": "Translate this Nepali or Nepali-English dictation into fluent English. Keep every detail. Output only the translation.",
    "cleanup": "Clean up this dictation: fix punctuation, capitalisation and grammar, drop filler words, keep the meaning and every detail. Output only the cleaned text.",
    "generate": (
        "Execute this spoken instruction directly and produce the final, polished content. "
        "If a list is requested, format as clean bullet points. "
        "Do not include conversational preamble or filler. Output only the requested text."
    ),
    "edit": (
        "Edit the selected text according to the user's spoken instruction. "
        "Fix grammar, punctuation, and wording. Preserve the core meaning. "
        "Output only the edited text."
    ),
}
# Added to the translate prompt when the first answer lost or added a "not" (negation.flipped). Together
# with temperature 0.3 and a fixed seed it fixed 5 of v6.2's 16 flips on Just Notes'
# lab/translate_bench (retry.py).
KEEP_NOT = 'Keep every "not": if the Nepali says not, the English must say not.'
RETRY_SEED = 7


def model_path(models_dir: Path) -> Path:
    """The model to load: the current one, else an older one already on disk, else where the
    current one will be downloaded to."""
    folder = Path(models_dir) / "local-ai"
    for name in (MODEL_FILE,) + OLDER_MODEL_FILES:
        if (folder / name).exists():
            return folder / name
    return folder / MODEL_FILE


def is_tuned(models_dir: Path) -> bool:
    return model_path(models_dir).name.startswith("justtalk-")


def is_current(models_dir: Path) -> bool:
    """The latest model is on disk (an older one may still be in use until it downloads)."""
    path = model_path(models_dir)
    return path.name == MODEL_FILE and path.exists()


def auto_download_plan(models_dir: Path, enabled: bool, auto_done: bool, offline: bool) -> str:
    """What to do on its own at start-up: "download", "switch_on" or "" (nothing).

    The first time (after updating to 3.0, or after setup) the model downloads and switches on
    without asking. From then on the user's choice stands: newer models are fetched only while
    it's on, and it is never switched back on after being turned off."""
    if offline or not runtime_available():
        return ""
    if is_current(models_dir):
        return "" if auto_done else "switch_on"
    if auto_done and not enabled:
        return ""
    return "download"


def runtime_available() -> bool:
    try:
        import llama_cpp  # noqa: F401
        return True
    except Exception:
        return False


def download_model(models_dir: Path, progress: Optional[Callable[[float], None]] = None) -> Tuple[bool, str]:
    import httpx

    final = Path(models_dir) / "local-ai" / MODEL_FILE
    final.parent.mkdir(parents=True, exist_ok=True)
    partial = final.with_suffix(".part")
    try:
        digest = hashlib.sha256()
        done = 0
        with httpx.Client(follow_redirects=True, timeout=60.0) as client:
            with client.stream("GET", MODEL_URL) as resp:
                resp.raise_for_status()
                with open(partial, "wb") as out:
                    for chunk in resp.iter_bytes(1 << 20):
                        out.write(chunk)
                        digest.update(chunk)
                        done += len(chunk)
                        if progress:
                            progress(min(1.0, done / MODEL_SIZE))
        if digest.hexdigest() != MODEL_SHA256:
            partial.unlink(missing_ok=True)
            return False, "The download failed its integrity check. Please try again."
        os.replace(partial, final)
        return True, "On-device AI model ready."
    except Exception as e:
        partial.unlink(missing_ok=True)
        return False, f"Couldn't download the on-device model: {e}"


def build_prompt(task: str, text: str, speaker_context: str = "", keep_not: bool = False) -> str:
    """Qwen3 chat prompt with thinking turned off. The system turn changes only when the
    speaker context does, so consecutive calls share a cached prefix."""
    system = SYSTEM[task] + (f" {KEEP_NOT}" if keep_not else "") + (f"\n{speaker_context}" if speaker_context else "")
    return (
        f"<|im_start|>system\n{system}<|im_end|>\n"
        f"<|im_start|>user\n{text}<|im_end|>\n"
        "<|im_start|>assistant\n<think>\n\n</think>\n\n"
    )


def _spoken(phrase: str, source: str) -> bool:
    """Whether the speaker said this phrase themselves, in either script (they may well dictate
    "output only the translation", which Kriti writes as "आउटपुट ओन्ली द ट्रान्सलेसन")."""
    if phrase in source.lower():
        return True
    try:
        from ..profile.scoring import skeleton_key
    except ImportError:  # loaded on its own by the training scripts
        return False
    key = lambda s: "".join(skeleton_key(w) for w in s.split())  # noqa: E731
    sound = key(phrase)
    return len(sound) >= 3 and sound in key(source)


_LIST_CUE = re.compile(
    r"\b(?:lists?|bullets?|bullet points?|points?|items?|action items|steps?|step one|checklist|to-do|todo|"
    r"to do list|firstly|number one|point one)\b",
    re.IGNORECASE,
)
_LIST_LINE = re.compile(r"^(?:- |\d+\. )", re.MULTILINE)


def asks_for_list(text: str) -> bool:
    """Whether the dictation asks for a list, so a bulleted answer is wanted."""
    low = text.lower()
    return bool(
        _LIST_CUE.search(low)
        or re.search(r"\bfirst\b", low) and re.search(r"\bsecond\b", low)
        or any(w in text for w in ("लिस्ट", "सूची", "बुँदा", "बुदा", "बुलेट", "आइटम", "स्टेप", "चेकलिस्ट", "पोइन्ट"))
        or "पहिलो" in text and "दोस्रो" in text
    )


_LEADING_ANSWERS = {"yes", "no", "yeah", "nope", "okay", "ok", "sure"}


def keep_leading_answer(task: str, source: str, output: str) -> str:
    """The model sometimes treats a leading "Yes," as a filler ("Yes, I think I do" -> "I think I do").
    An answer word the speaker said first is put back; dropping "No" would flip the meaning."""
    if task != "cleanup" or not source.strip() or not output:
        return output
    first = source.split()[0].strip(",.!?").lower()
    if first not in _LEADING_ANSWERS or output.lower().lstrip("\"'").startswith(first):
        return output
    rest = output if output.startswith("I ") or output.startswith("I'") else output[:1].lower() + output[1:]
    return f"{first.capitalize() if first != 'ok' else 'OK'}, {rest}"


def check_output(task: str, source: str, output: str) -> Optional[str]:
    """Why an answer can't be trusted, or None if it looks like a faithful edit/translation."""
    out = output.strip()
    if not out:
        return "empty"
    lower = out.lower()
    if any(leak in lower and not _spoken(leak, source) for leak in _PROMPT_LEAKS):
        return "repeated its instructions"
    if task == "translate" and _DEVANAGARI.search(out):
        return "left Devanagari untranslated"
    if task in ("translate", "cleanup") and len(_LIST_LINE.findall(out)) >= 2 and not asks_for_list(source):
        return "made a list nobody asked for"
    if task in ("generate", "edit", "action"):
        words = [w.lower().strip(".,!?") for w in out.split()]
        for i in range(len(words) - 3):
            if words[i] and words[i] == words[i + 1] == words[i + 2] == words[i + 3] and source.lower().count(words[i]) < 4:
                return "repeated itself"
        return None
    src_words, out_words = len(source.split()), len(out.split())
    low, high = (0.4, 2.2) if task == "translate" else (0.5, 1.6)
    if src_words >= 4 and not (low <= out_words / src_words <= high):
        return "length doesn't match what was said"
    words = [w.lower().strip(".,!?") for w in out.split()]
    for i in range(len(words) - 3):
        if words[i] and words[i] == words[i + 1] == words[i + 2] == words[i + 3] and source.lower().count(words[i]) < 4:
            return "repeated itself"
    return None


class LocalModel:
    """Thread-safe wrapper; load() is cheap to call repeatedly."""

    def __init__(self, models_dir: Path, gpu: bool = True):
        self.models_dir = Path(models_dir)
        self.gpu = gpu
        self._llm = None
        self._lock = threading.Lock()

    def is_downloaded(self) -> bool:
        p = model_path(self.models_dir)
        return p.exists() and (p.name != MODEL_FILE or p.stat().st_size == MODEL_SIZE)

    def is_available(self) -> bool:
        return self.is_downloaded() and runtime_available()

    def is_loaded(self) -> bool:
        return self._llm is not None

    def load(self) -> bool:
        with self._lock:
            if self._llm is not None:
                return True
            if not self.is_available():
                return False
            try:
                from llama_cpp import Llama

                self._llm = Llama(
                    model_path=str(model_path(self.models_dir)),
                    n_gpu_layers=-1 if self.gpu else 0,
                    n_ctx=4096,
                    n_threads=max(2, min(4, (os.cpu_count() or 4) // 2)),
                    verbose=False,
                )
                print(f"[LocalAI] Model loaded: {model_path(self.models_dir).name}", file=sys.stderr)
                return True
            except Exception as e:
                print(f"[LocalAI] Couldn't load the model: {e}", file=sys.stderr)
                self._llm = None
                return False

    def unload(self) -> None:
        with self._lock:
            self._llm = None

    def run(self, task: str, text: str, speaker_context: str = "") -> Tuple[str, bool, str]:
        """task: "translate", "cleanup", "generate", or "edit". Returns (text, ok, message)."""
        if not text.strip():
            return "", True, ""
        if not self.load():
            return text, False, "On-device model isn't available."
        with self._lock:
            llm = self._llm
            if llm is None:
                return text, False, "On-device model was unloaded."
            try:
                n_in = len(llm.tokenize(text.encode("utf-8"), add_bos=False))
                max_tokens = min(512, max(128, int(1.8 * n_in) + 32)) if task in ("generate", "edit", "action") else min(512, int(1.6 * n_in) + 24)
                temp = 0.2 if task in ("generate", "edit", "action") else 0.0

                def complete(keep_not=False, temperature=temp, **seed):
                    result = llm.create_completion(
                        build_prompt(task, text, speaker_context, keep_not),
                        max_tokens=max_tokens,
                        temperature=temperature,
                        repeat_penalty=1.1,
                        stop=["<|im_end|>"],
                        **seed,
                    )
                    return result["choices"][0]["text"].strip().strip('"').strip()

                out = complete()
                if task == "translate" and flipped and flipped(text, out):
                    # Temperature 0 would give the same answer again, so the retry changes the prompt and the
                    # sampling. Still flipped means the speaker's own words are kept: a flipped "not" is worse.
                    out = complete(keep_not=True, temperature=0.3, seed=RETRY_SEED)
                    if flipped(text, out):
                        return text, False, 'On-device answer rejected (lost or added a "not").'
            except Exception as e:
                return text, False, f"On-device model error: {e}"
        problem = check_output(task, text, out)
        if problem:
            return text, False, f"On-device answer rejected ({problem})."
        return keep_leading_answer(task, text, out), True, ""
