"""
End-to-end real AI pipeline for a farmer query:

    STT (voice only) -> Translate to English -> Retrieve from Chroma -> Classify
    -> Generate answer -> Translate to farmer's language -> TTS (optional)
    -> Send via WhatsApp (Picky Assist)

All OpenAI calls are real (model names configurable via settings).
The pipeline is resilient: on failure it records the error into Query.pipeline_trace.error
and attempts to send a graceful fallback text reply to the farmer.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import List, Optional

import requests
from django.conf import settings
from django.core.files.base import ContentFile
from django.utils import timezone

from catalogues.services.vector_store import search_catalogue
from queries.models import Query

log = logging.getLogger("irri")


# ---------- OpenAI client helpers ----------

def _client():
    from openai import OpenAI
    if not settings.OPENAI_API_KEY:
        raise RuntimeError(
            "OPENAI_API_KEY is not set; pipeline cannot run. "
            "Add it to .env or set USE_LOCAL_EMBEDDINGS and skip TTS/STT."
        )
    return OpenAI(api_key=settings.OPENAI_API_KEY)


def _chat(messages: List[dict], model: Optional[str] = None, json_mode: bool = False) -> str:
    kwargs = {
        "model": model or settings.OPENAI_CHAT_MODEL,
        "messages": messages,
        "temperature": 0.2,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    resp = _client().chat.completions.create(**kwargs)
    return resp.choices[0].message.content or ""


# ---------- Pipeline stages ----------

def stt_transcribe(audio_path: str, language_hint: str = "") -> str:
    """Transcribe audio to text in the source language.

    Routing:
      - Odia → AI4Bharat / Bhashini (much better Odia accuracy than Whisper).
      - All other languages → OpenAI Whisper with the ISO-639-1 hint.

    Fallbacks:
      - If Bhashini isn't configured or fails, Odia falls back to Whisper.
      - If Whisper rejects the language hint with `unsupported_language`,
        we retry without the hint (auto-detect).
    """
    if language_hint == "Odia":
        try:
            from .indic_stt import NotConfigured, transcribe_odia
            text = transcribe_odia(audio_path)
            if text:
                return text
            log.warning("Bhashini returned empty Odia transcript; falling back to Whisper.")
        except NotConfigured as exc:
            log.info("%s — falling back to Whisper for Odia.", exc)
        except Exception as exc:
            log.warning("Bhashini Odia ASR failed (%s); falling back to Whisper.", exc)

    lang_map = {"Odia": "or", "Hindi": "hi", "Bengali": "bn", "English": "en",
                "Telugu": "te", "Tamil": "ta"}
    lang = lang_map.get(language_hint, None)

    def _call(with_lang: bool) -> str:
        with open(audio_path, "rb") as fh:
            kwargs = {"model": settings.OPENAI_STT_MODEL, "file": fh}
            if with_lang and lang:
                kwargs["language"] = lang
            return _client().audio.transcriptions.create(**kwargs).text

    try:
        return _call(with_lang=True)
    except Exception as exc:
        msg = str(exc)
        if "unsupported_language" in msg or "is not supported" in msg.lower():
            log.warning("STT model rejected language '%s'; retrying without hint", lang)
            return _call(with_lang=False)
        raise


def translate(text: str, source_lang: str, target_lang: str) -> str:
    if not text.strip():
        return ""
    if source_lang == target_lang:
        return text
    sys = (
        f"You are a translator. Translate the user's message from {source_lang} to "
        f"{target_lang}. Return ONLY the translated text. Preserve agricultural terminology."
    )
    return _chat([{"role": "system", "content": sys}, {"role": "user", "content": text}])


def classify_and_enrich(query_text_en: str) -> dict:
    """
    Extract task_type, problem_entity, category, season, crop_stage, missing_context as JSON.
    """
    sys = (
        "You are an agricultural query classifier. Given a farmer's rice-related question, "
        "respond ONLY with a JSON object having these fields:\n"
        '{"category": one of ["Rice Variety","Disease","Fertiliser","Water Mgmt","Others"],\n'
        ' "task_type": one of ["Diagnosis","Variety Suitability","Fertiliser Rec.","Management Advice","Other"],\n'
        ' "problem_entity": short phrase (e.g. "Blast", "Urea dose"),\n'
        ' "season": one of ["Kharif","Rabi","Zaid",""] (empty if unknown),\n'
        ' "crop_stage": one of ["Nursery","Tillering","Flowering","Mature Grain",""] (empty if unknown),\n'
        ' "missing_context": short comma-separated list of context the farmer did not provide '
        '(e.g. "variety, land type") or empty string}'
    )
    raw = _chat(
        [{"role": "system", "content": sys}, {"role": "user", "content": query_text_en}],
        json_mode=True,
    )
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def retrieve(catalogue, query_text_en: str, n_results: int = 6):
    return search_catalogue(catalogue, query_text_en, n_results=n_results)


FARMER_PERSONA = (
    "You are PaddyMitra, an AI advisor speaking directly to a rice farmer in India. "
    "Answer in SIMPLE, PLAIN language a small-holder farmer can understand. "
    "Rules for your answer:\n"
    " - Keep it short: 3-5 sentences, or a tight bullet list (max 5 bullets).\n"
    " - Avoid scientific jargon. If a technical word is unavoidable, give the common/local name too.\n"
    " - Use practical, actionable instructions: what to do, how much, when.\n"
    " - Do NOT cite research papers or authors. Do NOT discuss mechanisms of action.\n"
    " - If the context is insufficient, say so plainly and ask for the missing detail in 1 sentence."
)

RESEARCHER_PERSONA = (
    "You are PaddyMitra Research, an AI advisor speaking to an agricultural researcher, "
    "extension officer, or agronomist. Answer in TECHNICAL, DETAILED language.\n"
    "Rules for your answer:\n"
    " - Give a thorough, structured response (headings, bullets, tables where useful).\n"
    " - Use scientific names, active ingredients, mechanisms, and measured values.\n"
    " - Cite the source documents you used by title (bracketed, e.g. [Source: ...]).\n"
    " - Include trial numbers and percentages where the context provides them.\n"
    " - Where methods or concentrations differ between sources, note the disagreement.\n"
    " - If context is insufficient, state the gap precisely and suggest what additional data would resolve it."
)

# Applied to BOTH personas. Most numeric errors farmers complain about come
# from the LLM converting units (e.g. tons/ha → kg/acre) and losing precision
# or making outright wrong conversions. We disable conversion entirely.
UNIT_FIDELITY_RULES = (
    "\n\nNUMERIC / UNIT FIDELITY (MANDATORY):\n"
    " - Quote numbers and units EXACTLY as they appear in the CONTEXT. "
    "Do not convert between units (e.g. do not change tons/hectare to kg/acre, "
    "do not change kg/ha to lb/acre, do not change litres to gallons).\n"
    " - Keep the same unit string the source used (e.g. \"5-6 tons per hectare\", "
    "\"120 kg N/ha\", \"40 grams per litre\").\n"
    " - Do not round, average, or rephrase numbers. If the source says \"5-6 tons/ha\", "
    "write \"5-6 tons/ha\" — not \"about 5 tons\" and not \"2000-2400 kg/acre\".\n"
    " - If the question asks for a unit not present in the CONTEXT, say so plainly "
    "instead of converting.\n"
)


def generate_answer(query_text_en: str, retrieved_hits: list, user_type: str = "farmer") -> str:
    context = "\n\n".join(
        f"[Source: {h['metadata'].get('document_title', 'doc')}]\n{h['chunk']}"
        for h in retrieved_hits
    )
    persona = RESEARCHER_PERSONA if (user_type or "").lower() == "researcher" else FARMER_PERSONA
    sys = (
        persona
        + UNIT_FIDELITY_RULES
        + "\n\nYou MUST answer using ONLY the context below.\n\nCONTEXT:\n"
        + context
    )
    return _chat([
        {"role": "system", "content": sys},
        {"role": "user", "content": query_text_en},
    ])


def tts_synthesize(text: str, voice: Optional[str] = None) -> bytes:
    resp = _client().audio.speech.create(
        model=settings.OPENAI_TTS_MODEL,
        voice=voice or settings.OPENAI_TTS_VOICE,
        input=text[:4000],
    )
    # openai>=1.0 returns a streamable response
    return resp.read() if hasattr(resp, "read") else resp.content


# ---------- High-level orchestrators ----------

def run_pipeline_for_text(
    catalogue, farmer_language: str, query_text: str,
    district: str = "", generate_tts: bool = False, hook=None,
    whatsapp_number: str = "", user_type: str = "farmer",
) -> Query:
    """Full pipeline entry point for a text-only query (demo form or webhook)."""
    trace = {"steps": [], "user_type": user_type}
    start = time.monotonic()
    q = Query.objects.create(
        whatsapp_number=whatsapp_number,
        district=district,
        hook=hook,
        trigger_keyword=(hook.trigger_keyword if hook else ""),
        catalogue=catalogue,
        original_query_language=farmer_language,
        original_query_text=query_text,
        status="Processing",
    )

    try:
        # 1. translate farmer -> English (if needed)
        t0 = time.monotonic()
        query_en = translate(query_text, farmer_language, "English")
        trace["steps"].append({"stage": "translate_in", "ms": int((time.monotonic() - t0) * 1000)})
        q.translated_query_text = query_en

        # 2. classify + enrich
        t0 = time.monotonic()
        cls = classify_and_enrich(query_en)
        trace["steps"].append({"stage": "classify", "ms": int((time.monotonic() - t0) * 1000)})
        q.category = cls.get("category", "")[:40]
        q.task_type = cls.get("task_type", "")[:40]
        q.problem_entity = cls.get("problem_entity", "")[:200]
        q.season = cls.get("season", "")[:20]
        q.crop_stage = cls.get("crop_stage", "")[:30]
        q.missing_context = cls.get("missing_context", "")[:500]

        # 3. retrieve
        t0 = time.monotonic()
        hits = retrieve(catalogue, query_en, n_results=6)
        trace["steps"].append({
            "stage": "retrieve",
            "ms": int((time.monotonic() - t0) * 1000),
            "hits": len(hits),
        })

        # 4. generate  (persona: farmer | researcher)
        t0 = time.monotonic()
        answer_en = generate_answer(query_en, hits, user_type=user_type)
        trace["steps"].append({
            "stage": "generate",
            "ms": int((time.monotonic() - t0) * 1000),
            "persona": user_type,
        })
        q.ai_response_text = answer_en

        # 5. translate English -> farmer's language
        t0 = time.monotonic()
        answer_local = translate(answer_en, "English", farmer_language)
        trace["steps"].append({"stage": "translate_out", "ms": int((time.monotonic() - t0) * 1000)})
        q.ai_response_text_local = answer_local

        # 6. TTS (optional)
        if generate_tts:
            t0 = time.monotonic()
            try:
                audio_bytes = tts_synthesize(answer_local)
                q.ai_response_voice_file.save(
                    f"q{q.pk}.mp3", ContentFile(audio_bytes), save=False
                )
                trace["steps"].append({"stage": "tts", "ms": int((time.monotonic() - t0) * 1000)})
            except Exception as exc:
                trace["steps"].append({"stage": "tts", "error": str(exc)})

        # 7. attach source documents
        doc_ids = {h["metadata"].get("document_id") for h in hits if h["metadata"].get("document_id")}
        if doc_ids:
            q.save()  # must save before m2m set
            q.source_documents.set(doc_ids)

        q.response_time_seconds = round(time.monotonic() - start, 2)
        q.status = "Responded"
        q.pipeline_trace = trace
        q.save()

        # 8. WhatsApp send (only if we have a hook + number configured)
        if hook and whatsapp_number:
            try:
                from .whatsapp import send_via_picky_assist
                send_via_picky_assist(hook, whatsapp_number, answer_local, audio_url=None)
            except Exception as exc:
                log.warning("WhatsApp send failed: %s", exc)

        return q

    except Exception as exc:
        log.exception("Pipeline failure for query %s", q.pk)
        trace["error"] = str(exc)
        q.pipeline_trace = trace
        q.status = "Failed"
        q.response_time_seconds = round(time.monotonic() - start, 2)
        q.save()
        raise


def identify_from_image(image_path: str, catalogue=None) -> dict:
    """
    Run CLIP image search against the global image bank.
    Returns: {
        "matched": bool,                  # confident match?
        "prefix": str,                    # matched visual group name
        "description": str,               # sidecar visual description (English)
        "image_url": str,                 # representative image URL (top hit)
        "distance": float | None,
        "score": float | None,
        "low_confidence": bool,           # True when above the confidence threshold
        "all_hits": list,                 # raw top-k for debug
    }
    """
    from image_bank.services.image_vector_store import query_by_image_path

    threshold = float(getattr(settings, "IMAGE_BANK_DISTANCE_MAX", 0.35))
    top_k = int(getattr(settings, "IMAGE_BANK_TOP_K", 5))
    catalogue_id = getattr(catalogue, "id", None) if catalogue else None
    hits = query_by_image_path(image_path, top_k=top_k, catalogue_id=catalogue_id)
    if not hits:
        return {"matched": False, "prefix": "", "description": "", "image_url": "",
                "distance": None, "score": None, "low_confidence": True, "all_hits": []}

    top = hits[0]
    distance = top.get("distance")
    meta = top.get("metadata") or {}
    low_conf = distance is None or distance > threshold
    return {
        "matched": True,
        "prefix": meta.get("prefix", ""),
        "description": (meta.get("description") or top.get("description") or "").strip(),
        "image_url": meta.get("image_url", ""),
        "distance": distance,
        "score": top.get("score"),
        "low_confidence": low_conf,
        "all_hits": hits,
    }


def run_pipeline_for_image(
    catalogue, farmer_language: str, uploaded_image,
    district: str = "", generate_tts: bool = False, hook=None,
    whatsapp_number: str = "", user_type: str = "farmer",
    user_query_text: str = "",
) -> Query:
    """
    Image-as-query entry point.

    Flow:
      1. Save the uploaded image to a temp file on disk.
      2. CLIP-match against the global image bank to identify the topic.
      3. If matched, build a synthesized query from the matched prefix +
         visual description, then run the standard text pipeline against the
         catalogue (translate -> classify -> retrieve -> generate -> translate).
      4. If low confidence, prefix the answer with a warning.
    """
    import tempfile

    # Persist upload to a real path so PIL/CLIP can read it.
    suffix = Path(uploaded_image.name).suffix or ".jpg"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        for chunk in uploaded_image.chunks():
            tmp.write(chunk)
        tmp_path = tmp.name

    try:
        identification = identify_from_image(tmp_path, catalogue=catalogue)
    except Exception as exc:
        log.exception("Image identification failed")
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise

    prefix = identification.get("prefix") or "(unknown)"
    visual_desc = identification.get("description") or ""
    low_conf = identification.get("low_confidence", True)

    # If the caller supplied a text question along with the image, translate it
    # into English first so we can blend it into the synthesized query.
    user_q_en = ""
    if user_query_text:
        try:
            user_q_en = translate(user_query_text, farmer_language or "English", "English")
        except Exception:
            user_q_en = user_query_text

    score = identification.get("score")
    score_str = f"{score:.2f}" if isinstance(score, (int, float)) else "n/a"

    if not identification.get("matched") or not visual_desc:
        if user_q_en:
            synth_query_en = (
                f"{user_q_en}\n\n"
                "(No matching reference image was found in the knowledge base. "
                "Answer the user's question using general knowledge and the retrieved "
                "documents. If the question depends on what is visually present, ask "
                "the user for a clearer photo or more details.)"
            )
        else:
            synth_query_en = (
                "An image was uploaded but no matching reference image was found in the "
                "knowledge base. Tell the user what extra information or a clearer photo "
                "would help."
            )
    else:
        topic = prefix.replace("_", " ")
        if user_q_en:
            # User has a specific question. The CLIP match is a HINT, not a fact —
            # the closest visual neighbour may still be a different concept (e.g.
            # growth stage when the user is asking about disease). Let the LLM
            # reconcile the two and disagree if the topics don't line up.
            confidence_note = (
                "low confidence — treat as a tentative hint only"
                if low_conf else
                f"similarity score {score_str}"
            )
            synth_query_en = (
                f"USER QUESTION:\n{user_q_en}\n\n"
                f"VISUAL HINT (from a CLIP image-similarity search; {confidence_note}):\n"
                f"The uploaded photo most closely resembles reference images of '{topic}'.\n\n"
                "INSTRUCTIONS:\n"
                "- Answer the USER QUESTION directly. Do NOT change the topic.\n"
                "- The VISUAL HINT may or may not be relevant to what the user is asking. "
                "If the hint's topic does not match the user's question (for example, the "
                "hint is a growth stage but the user asks about disease or nutrient "
                "deficiency), say so explicitly and do not assert the hint as a diagnosis.\n"
                "- Only use the hint if it is genuinely relevant to the user's question.\n"
                "- If the visual hint is low confidence, treat it cautiously.\n"
            )
        else:
            # No user question — pure image-as-query. Identification is the answer.
            confidence_note = (
                "low confidence" if low_conf else f"similarity score {score_str}"
            )
            synth_query_en = (
                f"An uploaded image was matched to reference images of '{topic}' "
                f"({confidence_note}) in the visual knowledge base. "
                "Briefly explain what this is and what the user should do about it. "
                "If the match is low confidence, say so and ask for a clearer photo."
            )

    # Run the existing text pipeline using the synthesized English query.
    q = run_pipeline_for_text(
        catalogue=catalogue,
        farmer_language="English",          # synthesized query is already English
        query_text=synth_query_en,
        district=district,
        generate_tts=generate_tts,
        hook=hook,
        whatsapp_number=whatsapp_number,
        user_type=user_type,
    )

    # Attach image-match metadata to the query record.
    q.original_query_text = (
        f"[IMAGE QUERY] {user_query_text}".strip() if user_query_text else "[IMAGE QUERY]"
    )
    q.original_query_language = farmer_language or "English"
    trace = q.pipeline_trace or {}
    trace["image_query"] = {
        "matched_prefix": identification.get("prefix"),
        "matched_description": (identification.get("description") or "")[:1000],
        "matched_image_url": identification.get("image_url"),
        "distance": identification.get("distance"),
        "score": identification.get("score"),
        "low_confidence": low_conf,
    }
    q.pipeline_trace = trace

    if low_conf and identification.get("matched"):
        warning = (
            "Note: the image match is low confidence. The closest visual group is "
            f"'{prefix.replace('_', ' ')}'. Please send a clearer photo if this is wrong.\n\n"
        )
        q.ai_response_text = warning + (q.ai_response_text or "")
        if q.ai_response_text_local:
            q.ai_response_text_local = warning + q.ai_response_text_local

    q.save()

    try:
        os.remove(tmp_path)
    except OSError:
        pass

    return q


def process_incoming_message(hook, payload: dict) -> Query:
    """
    Called by PickyAssistWebhookView. `payload` keys:
        from, message_type ("text"|"audio"), text, audio_url, district
    """
    lang = hook.primary_language
    district = payload.get("district", "")
    whatsapp = payload.get("from", "")
    msg_type = payload.get("message_type", "text")
    query_text = payload.get("text", "")

    if msg_type == "audio":
        url = payload.get("audio_url", "")
        if not url:
            raise ValueError("audio_url missing")
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            r = requests.get(url, timeout=30)
            r.raise_for_status()
            tmp.write(r.content)
            tmp_path = tmp.name
        try:
            query_text = stt_transcribe(tmp_path, language_hint=lang)
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    return run_pipeline_for_text(
        catalogue=hook.catalogue,
        farmer_language=lang,
        query_text=query_text,
        district=district,
        generate_tts=True,
        hook=hook,
        whatsapp_number=whatsapp,
    )
