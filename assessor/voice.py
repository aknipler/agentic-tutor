"""Speech-to-text for spoken tutorial answers.

Dictation only - no realtime session and no custom component. `st.audio_input`
records in the browser and hands the bytes to Python; this module turns them into
text, which then goes through the ordinary assessment path.
"""
import os
from typing import Optional

import streamlit as st
from openai import OpenAI

DEFAULT_MODEL = "gpt-4o-transcribe"

# Terms a general-purpose speech model reliably mangles. Supplied as a biasing
# prompt so answers come back with the subject's vocabulary intact.
SUBJECT_VOCABULARY = (
    "Cp, Cpk, gauge R&R, repeatability, reproducibility, ANOVA, P/TV, "
    "parts per million, PPM, takt time, cycle time, specification limits, LSL, USL, "
    "reliability, cumulative probability of failure, FMEA, turnback, escape, scrap, "
    "standard deviation, sigma, p-value, null hypothesis, residuals, interaction effect"
)


def _get_client() -> OpenAI:
    """OpenAI client, preferring the OS env var and falling back to secrets."""
    api_key = os.getenv("OPENAI_API_KEY") or st.secrets.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("No OPENAI_API_KEY in the environment or .streamlit/secrets.toml.")
    return OpenAI(api_key=api_key)


def build_vocabulary_hint(question_text: str = "") -> str:
    """Biasing prompt for the transcriber.

    Includes the question so related terms are primed, plus the subject glossary.

    NOTE: never include the expected answer here. The prompt steers what the model
    thinks it is hearing, so seeding it with the model answer risks that text
    appearing in the transcript and being graded as the student's own words.
    """
    question_text = (question_text or "").strip()
    if question_text:
        return f"Engineering tutorial answer responding to: {question_text}\nTerms: {SUBJECT_VOCABULARY}"
    return f"Engineering tutorial answer. Terms: {SUBJECT_VOCABULARY}"


def transcribe(audio_bytes: bytes, filename: str = "answer.wav",
               question_text: str = "") -> Optional[str]:
    """Transcribe recorded audio to text.

    Returns the transcript, or None if transcription failed or produced nothing.
    Callers must treat None as "do not submit" so a failure never costs an attempt.
    """
    if not audio_bytes:
        return None

    model = st.secrets.get("TRANSCRIBE_MODEL", DEFAULT_MODEL)

    try:
        client = _get_client()
        result = client.audio.transcriptions.create(
            model=model,
            file=(filename, audio_bytes),
            prompt=build_vocabulary_hint(question_text),
        )
    except Exception as e:
        print(f"[Error] Transcription failed: {e}")
        st.error(f"Could not transcribe the recording: {e}")
        return None

    transcript = (getattr(result, "text", "") or "").strip()
    if not transcript:
        st.warning("Nothing was transcribed from that recording. Please try again.")
        return None

    return transcript
