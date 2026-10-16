"""On-device AI for dictation cleanup and translation to English (llama.cpp, no cloud).

Speed comes from four things measured in the Oct 2026 bake-off on the user's own dictations:
- llama.cpp on the GPU (Metal on Macs): ~6x faster than CTranslate2's CPU path;
- a short, fixed system prompt, so llama.cpp reuses its KV cache across calls
  (re-reading the full cloud prompt each time cost 2-5 s before the first word);
- greedy decoding with an output cap tied to the input length and a light repeat penalty,
  which stops small models looping ("all all all ...") — worst case went from 3.3 s to 1.3 s;
- staying loaded while the user is active (the app's idle unloader frees it later).

The model is untuned Qwen3-1.7B for now. Anything that fails the sanity checks below is
rejected so the caller keeps the raw draft (or asks the cloud model, if the user has one).
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
import threading
from pathlib import Path
from typing import Callable, Optional, Tuple

MODEL_FILE = "Qwen3-1.7B-Q8_0.gguf"
MODEL_URL = f"https://huggingface.co/Qwen/Qwen3-1.7B-GGUF/resolve/main/{MODEL_FILE}"
MODEL_SHA256 = "061b54daade076b5d3362dac252678d17da8c68f07560be70818cace6590cb1a"
MODEL_SIZE = 1834426016
MODEL_DOWNLOAD_MB = round(MODEL_SIZE / 1e6)
# A Just Talk fine-tune placed next to it (not downloadable yet) is preferred when present.
TUNED_MODEL_FILE = "justtalk-qwen3-1.7b-v4-Q4_K_M.gguf"

_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_PROMPT_LEAKS = ("output only", "keep every detail", "this dictation", "<think", "</think", "translate this")

SYSTEM = {
    "translate": "Translate this Nepali or Nepali-English dictation into fluent English. Keep every detail. Output only the translation.",
    "cleanup": "Clean up this dictation: fix punctuation, capitalisation and grammar, drop filler words, keep the meaning and every detail. Output only the cleaned text.",
}


def model_path(models_dir: Path) -> Path:
    folder = Path(models_dir) / "local-ai"
    tuned = folder / TUNED_MODEL_FILE
    return tuned if tuned.exists() else folder / MODEL_FILE


def is_tuned(models_dir: Path) -> bool:
    return model_path(models_dir).name == TUNED_MODEL_FILE


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


def build_prompt(task: str, text: str, speaker_context: str = "") -> str:
    """Qwen3 chat prompt with thinking turned off. The system turn changes only when the
    speaker context does, so consecutive calls share a cached prefix."""
    system = SYSTEM[task] + (f"\n{speaker_context}" if speaker_context else "")
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
        return p.exists() and (p.name == TUNED_MODEL_FILE or p.stat().st_size == MODEL_SIZE)

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
        """task: "translate" (to English) or "cleanup". Returns (text, ok, message)."""
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
                result = llm.create_completion(
                    build_prompt(task, text, speaker_context),
                    max_tokens=min(512, int(1.6 * n_in) + 24),
                    temperature=0.0,
                    repeat_penalty=1.1,
                    stop=["<|im_end|>"],
                )
                out = result["choices"][0]["text"].strip().strip('"').strip()
            except Exception as e:
                return text, False, f"On-device model error: {e}"
        problem = check_output(task, text, out)
        if problem:
            return text, False, f"On-device answer rejected ({problem})."
        return out, True, ""
