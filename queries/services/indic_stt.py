"""
Odia speech-to-text.

Primary path: **Sarvam AI** hosted ASR (Indic-tuned, ~1–2 s latency). Used
whenever `SARVAM_API_KEY` is set in `.env`.

Fallback path: **local Wav2Vec2** (`Harveenchadha/odia_large_wav2vec2`).
Offline, but slow on CPU (~5–20 s per query). Engages automatically if the
Sarvam call fails (network error, 4xx/5xx, empty transcript, or no key set).

Pipeline:
    audio (any container) ─ffmpeg→ WAV 16 kHz mono ─→ Sarvam | wav2vec2 ─→ Odia text

Called from `queries.services.pipeline.stt_transcribe` only when the user's
selected language is Odia. All other languages still use OpenAI Whisper.
"""
from __future__ import annotations

import logging
import os
import subprocess
import tempfile

import requests
from django.conf import settings

log = logging.getLogger("irri")


class NotConfigured(RuntimeError):
    """Raised when neither path is available."""


# ---------- Sarvam (primary) ----------

def _sarvam_transcribe(wav_path: str) -> str:
    api_key = getattr(settings, "SARVAM_API_KEY", "") or ""
    if not api_key:
        raise NotConfigured("SARVAM_API_KEY not set; cannot use Sarvam STT.")
    url = getattr(settings, "SARVAM_STT_URL", "https://api.sarvam.ai/speech-to-text")
    model = getattr(settings, "SARVAM_STT_MODEL", "saarika:v2.5")

    with open(wav_path, "rb") as fh:
        files = {"file": ("audio.wav", fh, "audio/wav")}
        data = {"model": model, "language_code": "od-IN"}
        headers = {"api-subscription-key": api_key}
        log.info("Sarvam STT (od-IN): POST %s, model=%s", url, model)
        r = requests.post(url, headers=headers, files=files, data=data, timeout=60)
    if r.status_code >= 400:
        raise RuntimeError(f"Sarvam returned {r.status_code}: {r.text[:400]}")
    payload = r.json() if r.content else {}
    text = (payload.get("transcript") or "").strip()
    return text


# ---------- Local Wav2Vec2 (fallback) ----------

_LOCAL_MODEL_ID = "Harveenchadha/odia_large_wav2vec2"
_pipe = None


def _get_local_pipe():
    global _pipe
    if _pipe is None:
        try:
            from transformers import pipeline  # lazy import
        except ImportError as exc:
            raise NotConfigured(
                "transformers is not installed and Sarvam is unavailable. "
                "Run `pip install transformers torch torchaudio`."
            ) from exc
        log.info("Loading local Odia Wav2Vec2 fallback %s …", _LOCAL_MODEL_ID)
        _pipe = pipeline(
            "automatic-speech-recognition",
            model=_LOCAL_MODEL_ID,
            device="cpu",
        )
    return _pipe


def _local_transcribe(wav_path: str) -> str:
    pipe = _get_local_pipe()
    log.info("Local Wav2Vec2 transcribing %s", wav_path)
    result = pipe(wav_path)
    text = (result.get("text") if isinstance(result, dict) else "") or ""
    return text.strip()


# ---------- Common ffmpeg helper ----------

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


# ---------- Public entry point ----------

def transcribe_odia(audio_path: str) -> str:
    """Transcribe an Odia audio file. Returns plain text in Odia script.

    Tries Sarvam first (fast); falls back to local Wav2Vec2 on any failure.
    """
    wav_path = _to_wav_16k_mono(audio_path)
    try:
        # 1) Sarvam
        try:
            text = _sarvam_transcribe(wav_path)
            if text:
                return text
            log.warning("Sarvam returned empty transcript; falling back to local model.")
        except NotConfigured as exc:
            log.info("%s — using local Wav2Vec2 fallback.", exc)
        except Exception as exc:
            log.warning("Sarvam STT failed (%s); falling back to local model.", exc)

        # 2) Local Wav2Vec2 fallback
        return _local_transcribe(wav_path)
    finally:
        try:
            os.remove(wav_path)
        except OSError:
            pass
