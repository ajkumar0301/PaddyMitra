"""
Local Odia speech-to-text using `Harveenchadha/odia_large_wav2vec2`
(a public, non-gated Wav2Vec2 model fine-tuned for Odia).

100% offline after the first model download (~1.2 GB cached under HF_HOME).
No API key, no HuggingFace login, no AI4Bharat license click.

Pipeline:
    audio file (any container) ─ffmpeg→ WAV 16 kHz mono ─Wav2Vec2→ Odia transcript

Routed from `queries.services.pipeline.stt_transcribe` whenever the user
picks Odia. All other languages still go to OpenAI's hosted Whisper.
"""
from __future__ import annotations

import logging
import os
import subprocess
import tempfile

log = logging.getLogger("irri")


class NotConfigured(RuntimeError):
    """Raised when transformers / torch isn't available."""


MODEL_ID = "Harveenchadha/odia_large_wav2vec2"

_pipe = None


def _get_pipe():
    global _pipe
    if _pipe is None:
        try:
            from transformers import pipeline  # lazy import
        except ImportError as exc:
            raise NotConfigured(
                "transformers is not installed. Run `pip install transformers torch`."
            ) from exc
        log.info("Loading Odia Wav2Vec2 model %s (first call only)…", MODEL_ID)
        _pipe = pipeline(
            "automatic-speech-recognition",
            model=MODEL_ID,
            device="cpu",
        )
    return _pipe


def _to_wav_16k_mono(src_path: str) -> str:
    """Convert any audio to 16 kHz mono WAV via ffmpeg. Returns a temp path."""
    out = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", src_path, "-ac", "1", "-ar", "16000",
             "-f", "wav", out],
            check=True, capture_output=True,
        )
    except FileNotFoundError:
        raise RuntimeError(
            "ffmpeg is not installed. Install it "
            "(Windows: choco install ffmpeg, Linux: apt install ffmpeg)."
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"ffmpeg failed: {exc.stderr.decode('utf-8', errors='ignore')[:300]}"
        )
    return out


def transcribe_odia(audio_path: str) -> str:
    """Transcribe an Odia audio file locally. Returns plain text in Odia script."""
    wav_path = _to_wav_16k_mono(audio_path)
    try:
        pipe = _get_pipe()
        log.info("Wav2Vec2-Odia transcribing %s", wav_path)
        result = pipe(wav_path)
    finally:
        try:
            os.remove(wav_path)
        except OSError:
            pass
    text = (result.get("text") if isinstance(result, dict) else "") or ""
    return text.strip()
