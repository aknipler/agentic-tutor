# Voice tutor via OpenAI gpt-realtime-mini — implementation plan

Goal: add an optional voice mode to the module tutor pages. Browser connects **directly to OpenAI over WebRTC** (no media server, no Daily.co), which fits Streamlit Community Cloud's single-port constraint. The Streamlit backend's only realtime job is minting short-lived ephemeral credentials.

Model: `gpt-realtime-mini` (or current mini snapshot, e.g. `gpt-realtime-2.1-mini`). Do not use the full model — 3–4x the audio cost.

## Architecture

```
Streamlit (Python)                       Browser (JS component)             OpenAI
─────────────────                        ─────────────────────              ──────
build instructions from                                                       
module topics + PRQ prompt ──┐                                                
                             ├─ POST /v1/realtime/client_secrets ──────────► ephemeral key
render component with        │                                                
{ephemeral_key, config} ─────┘──────────► getUserMedia (mic)                  
                                          RTCPeerConnection ────SDP────────► /v1/realtime/calls?model=...
                                          data channel "oai-events"          (audio in/out via WebRTC)
                                          <audio> plays remote track          
```

## Deliverables

### 1. `utils/voice/session.py` — ephemeral key minting (Python)

- `mint_realtime_secret(instructions: str, voice: str = "marin") -> dict`
- POST `https://api.openai.com/v1/realtime/client_secrets` with `Authorization: Bearer st.secrets["OPENAI_API_KEY"]`, body containing the session config (model, instructions, voice, `input_audio_transcription` enabled, turn detection defaults, and a session `max_output_tokens` cap).
- Check the current API reference for exact body shape (it has changed since GA; verify against https://developers.openai.com/api/docs/guides/realtime-webrtc).
- Ephemeral keys expire ~60s after minting — mint only when the user clicks "Start voice session", never on page render.
- `build_voice_instructions(module_title, topics) -> str`: PRQ tutor prompt (see below) + a compact rendering of the module's topics from `modules_live` (name + description). This is the v1 grounding strategy — topic descriptions are injected into instructions instead of vector-store file search (Realtime API has no native file_search; see "Deferred" below).
- Voice-specific prompt: derive from `prompts/tutor.md` but rewrite for speech — short spoken turns, one question at a time, no markdown/LaTeX, spell out formulas verbally ("R of t equals P of T greater than t"). Keep it well under the text prompt's length. Store as `prompts/tutor_voice.md`.

### 2. Browser component — `utils/voice/component/`

**Spike first (30 min): microphone permission inside the Streamlit iframe.**
`st.components.v1.html` renders into a sandboxed iframe that historically lacks `allow="microphone"`, so `getUserMedia` may be blocked. Test on Streamlit ≥1.40 before building anything. If blocked, use `components.declare_component` with a static build dir (a plain HTML/JS file, no React/npm needed) — declared components get proper iframe permissions. This decision gates the rest.

JS responsibilities (single vanilla-JS file, no bundler):
1. Receive `{client_secret, model}` from Python (template substitution for `components.html`, or `Streamlit.args` for a declared component).
2. `navigator.mediaDevices.getUserMedia({audio: true})`.
3. `new RTCPeerConnection()`; add mic track; `pc.ontrack` → attach to hidden `<audio autoplay>`.
4. Create data channel `oai-events`; on open, optionally send `session.update`.
5. SDP offer → `POST https://api.openai.com/v1/realtime/calls?model=<model>` with `Authorization: Bearer <client_secret>`, `Content-Type: application/sdp`; set answer. (Verify the current endpoint/unified-interface flow in the docs.)
6. UI: start/stop button, connection state, mute toggle, elapsed-time display, and a running transcript `<div>` fed from data-channel transcription events (`conversation.item.input_audio_transcription.completed`, `response.output_audio_transcript.done` — verify event names).
7. Hard stop: close the peer connection after `MAX_SESSION_SECONDS` (default 600) with a spoken-warning at T-60s if easy. This is the primary cost guardrail.

### 3. Integration — `utils/tutor/interface.py`

- Add an expander/toggle "🎤 Voice tutor (beta)" inside `render_tutor_interface`, below the chat UI.
- On "Start": call `mint_realtime_secret(build_voice_instructions(...))`, render the component with the secret.
- Show a per-session note: voice sessions are limited to N minutes.
- Config in `st.secrets` (optional, with defaults): `REALTIME_MODEL`, `VOICE_MAX_SESSION_SECONDS`.

### 4. Security / cost constraints (non-negotiable)

- The real `OPENAI_API_KEY` must never reach the browser. Only the ephemeral `client_secret` is passed to the component.
- Session length cap in JS **and** `max_output_tokens` in the session config.
- Only logged-in users can mint (the tutor page already gates on `st.session_state.logged_in`).
- No secrets in the component source; the component dir is served statically.

## Deferred to v2 (do not build now)

- **Retrieval tool**: function calling from the realtime session → bridge to Responses API file_search over the module vector store. Requires a bidirectional custom component (JS → Python round trip) or a tiny external HTTPS endpoint; the instruction-injected topic content is sufficient grounding for v1.
- **Transcript persistence to Mongo** (same bidirectional-component dependency).
- **Progress updates from voice sessions** (competency status changes).

## Acceptance checklist

- [ ] Mic permission works in deployed Streamlit Cloud app (HTTPS) — not just localhost.
- [ ] Voice conversation grounded in the selected module's topics; tutor stays Socratic.
- [ ] Session auto-terminates at the cap; Stop button reliably closes the connection and releases the mic.
- [ ] Real API key absent from all browser-delivered code (verify in devtools).
- [ ] Text chat tutor unaffected when voice is not started (zero extra API calls on page load).
- [ ] Works in Chrome + Safari (Safari WebRTC quirks: autoplay policy — attach audio element after user gesture).
