# Voice features — implementation plan

Two separate features, revised 2026-07-19. **They are not the same technology and should not
share an implementation:**

| | A. Voice tutor | B. Assessor voice answer |
|---|---|---|
| Interaction | Two-way spoken conversation | One-way dictation |
| Needs | OpenAI Realtime over WebRTC | Speech-to-text only |
| Component | Custom JS component | `st.audio_input` — built in |
| Transcript | Shown **after** the session ends | Shown **after** submission |
| Effort | Days | Hours |

Build **B first**. It is far simpler, delivers value on its own, and needs none of A's
infrastructure.

---

## B. Assessor voice answer

> Requirement: a button activates voice input so a student can dictate their answer. On Stop,
> the answer is submitted and the transcription is shown afterwards.

No custom component, no WebRTC, no ephemeral keys. Streamlit 1.40 ships `st.audio_input`, which
records in the browser (handling the mic permission itself) and hands the audio to Python.

### Flow

```
"🎤 Answer by voice"  ->  st.audio_input records  ->  student clicks Stop
                                                          |
                          audio bytes arrive in Python on the next rerun
                                                          |
                    client.audio.transcriptions.create(...)  ->  text
                                                          |
                    existing assess_answer(...) path, unchanged
                                                          |
                    render: transcription, then competency + feedback
```

### Deliverables

1. **`assessor/voice.py`**
   - `transcribe(audio_bytes: bytes, filename: str = "answer.webm") -> str`
   - Calls `client.audio.transcriptions.create(model=..., file=...)`. Use `gpt-4o-transcribe`
     (better on technical vocabulary than `whisper-1`); make it configurable via
     `st.secrets["TRANSCRIBE_MODEL"]`.
   - Pass a `prompt` biasing toward subject vocabulary — "Cpk", "gauge R&R", "ANOVA",
     "takt time" — otherwise these come back mangled. Build it from the module's topic names,
     which are already to hand.
   - Return `""` on failure and let the caller show the error; never submit an empty answer.

2. **`assessor/ui.py` — inside the existing question expander**
   - A toggle (`st.toggle("🎤 Answer by voice")`) that reveals `st.audio_input`, so the widget
     doesn't clutter the default text flow.
   - Track the processed recording's identity in `st.session_state` so a rerun doesn't
     re-transcribe and re-submit the same audio. This is the one real trap: `st.audio_input`
     returns the same value on every rerun until it is cleared.
   - On new audio: transcribe → submit through the **existing** `assess_answer` path → clear
     the cache → `st.rerun()`, exactly as the typed path now does.
   - Render the transcription above the assessment results, clearly labelled as what was heard.

3. **Persist the transcript** as the answer text. `save_assessment_results` already stores
   `response_text`; the transcription should go in as the student's answer so the record
   matches what was graded.

### Decision needed before building

Auto-submitting on Stop means **a mis-transcription is graded and consumes an attempt**, with no
chance to correct it. Technical terms are exactly what ASR gets wrong. Three options:

- **(a) As specified** — submit immediately on Stop. Fewest clicks; wrong transcripts get graded.
- **(b) Transcribe, show, confirm** — one extra click, student sees what was heard before it
  counts. Safest.
- **(c) As specified, but editable after** — submit on Stop, show the transcript in an editable
  box with "Resubmit corrected answer".

I'd recommend **(b)**; it costs one click and removes the failure mode entirely. Flagging it
because the requirement as written is (a).

---

## A. Voice tutor

Browser connects **directly to OpenAI over WebRTC** (no media server), which fits Streamlit
Community Cloud's single-port constraint. The backend's only realtime job is minting
short-lived ephemeral credentials.

Model: `gpt-realtime-mini` (or current mini snapshot). Not the full model — several times the
audio cost.

```
Streamlit (Python)                    Browser (JS component)          OpenAI
──────────────────                    ──────────────────────          ──────
build instructions from
module topics + PRQ prompt ──┐
                             ├─ POST /v1/realtime/client_secrets ──► ephemeral key
render component with        │
{ephemeral_key, config} ─────┘──────► getUserMedia (mic)
                                      RTCPeerConnection ──SDP──────► /v1/realtime/calls
                                      data channel "oai-events"      (audio both ways)
                                      <audio> plays remote track
```

### Change from the previous plan: transcript timing

The transcript is **not** displayed while speaking. Accumulate transcript events silently
during the session and render the full conversation only once it ends (Stop, or the duration
cap). Rationale: a live transcript invites reading instead of listening, which defeats the
point of a spoken tutorial.

This makes the component's job easier — buffer an array of `{role, text}`, render on close.

### Deliverables

1. **`utils/voice/session.py`** — ephemeral key minting
   - `mint_realtime_secret(instructions, voice="marin") -> dict`: POST
     `https://api.openai.com/v1/realtime/client_secrets` with the real key from `st.secrets`,
     body carrying model, instructions, voice, `input_audio_transcription` enabled, turn
     detection, and a `max_output_tokens` cap.
   - **Verify the request shape against current docs** — it has changed since GA.
   - Keys expire in about a minute: mint on "Start", never on page render.
   - `build_voice_instructions(module_title, topics) -> str`: voice prompt plus a compact
     rendering of the module's topics. Topic descriptions are the v1 grounding strategy; the
     Realtime API has no native `file_search`.
   - `prompts/tutor_voice.md`: derived from `prompts/tutor.md` but rewritten for speech — short
     turns, one question at a time, no markdown or LaTeX, formulas spoken aloud ("R of t equals
     one minus F of t"). Much shorter than the text prompt.

2. **`utils/voice/component/`** — browser component

   **Spike first (~30 min): does `getUserMedia` work inside the Streamlit iframe?**
   `st.components.v1.html` renders into a sandbox that historically lacks
   `allow="microphone"`. Test before building anything; if blocked, use
   `components.declare_component` with a static build dir (plain HTML/JS, no npm), which gets
   proper iframe permissions. **This decision gates the rest.**

   Note: if the spike pushes us to `declare_component`, `Streamlit.setComponentValue()` becomes
   available, so returning the finished transcript to Python is nearly free — which also
   unblocks persistence (previously deferred).

   Responsibilities:
   1. Receive `{client_secret, model}` from Python.
   2. `getUserMedia({audio: true})`.
   3. `RTCPeerConnection`; add mic track; `ontrack` → hidden `<audio autoplay>`.
   4. Data channel `oai-events`; `session.update` on open if needed.
   5. SDP offer → `POST https://api.openai.com/v1/realtime/calls?model=<model>` with the
     ephemeral key and `Content-Type: application/sdp`; set the answer.
   6. UI: start/stop, connection state, mute, elapsed time. **No live transcript** — buffer
     transcription events (`conversation.item.input_audio_transcription.completed`,
     `response.output_audio_transcript.done`; verify names) and render on close.
   7. Hard stop after `MAX_SESSION_SECONDS` (default 600). This is the main cost guardrail.

3. **Integration — `utils/tutor/interface.py`**
   - "🎤 Voice tutor (beta)" expander below the chat UI.
   - On Start: `mint_realtime_secret(build_voice_instructions(...))`, render the component.
   - Show the session length limit up front.
   - Optional secrets: `REALTIME_MODEL`, `VOICE_MAX_SESSION_SECONDS`.

### Deferred to v2

- **Retrieval tool** — realtime function call bridged to Responses API `file_search` over the
  module vector store. Instruction-injected topics are sufficient grounding for v1.
- **Progress updates from voice sessions** — competency changes from spoken answers.
- **Transcript persistence** — in reach if the component ends up declared (see above), but not
  required for v1.

---

## Shared constraints (non-negotiable)

- The real `OPENAI_API_KEY` must never reach the browser. Only ephemeral secrets go to the
  component; feature B never sends a key to the browser at all.
- Only logged-in users can mint or transcribe — both pages already gate on
  `st.session_state.logged_in`.
- Session length cap in JS **and** `max_output_tokens` server-side.
- Audio is billed per minute. Both features need a visible cap or a short recording limit.

## Build order

1. **B** — assessor voice answer. Self-contained, no component work, immediately useful.
2. **A's mic spike** — decides `components.html` vs `declare_component`; blocks everything else.
3. **A** — ephemeral minting, then the component, then integration.

## Acceptance checklist

**B — assessor voice**
- [ ] Recording, transcription and submission work on deployed Streamlit Cloud (HTTPS), not just localhost.
- [ ] A rerun does not re-transcribe or double-submit the same recording.
- [ ] Subject vocabulary (Cpk, gauge R&R, ANOVA) transcribes correctly with the biasing prompt.
- [ ] A failed transcription surfaces an error and does not consume an attempt.
- [ ] The stored answer text matches what was graded.

**A — voice tutor**
- [ ] Mic permission works in the deployed app, not just localhost.
- [ ] Conversation is grounded in the module's topics and stays Socratic.
- [ ] **No transcript is visible during the conversation; the full transcript appears on end.**
- [ ] Session auto-terminates at the cap; Stop reliably closes the connection and releases the mic.
- [ ] Real API key absent from all browser-delivered code (check devtools).
- [ ] Text chat unaffected when voice is unused — zero extra API calls on page load.
- [ ] Chrome and Safari (Safari autoplay: attach audio only after a user gesture).
