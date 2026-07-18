# Handover — PRQ Agentic Tutor (FunCE → MCEN90059 migration)

Context for the next agent. Written 2026-07-17 after an initial exploration + planning session with Ash. Read `README.md` first (written this session — architecture, MongoDB schema, setup, known inconsistencies), then this file for state and next steps.

## Project in one paragraph

Streamlit AI tutor/assessor forked (with consent) from a Fundamentals of Chemical Engineering (FunCE) subject, being adapted for **Probability, Reliability and Quality (MCEN90059)**. Students log in with a code, chat with a Socratic tutor per module (OpenAI + per-module vector stores), and get tutorial answers marked by an assessor, with progress in MongoDB Atlas. Deployed on Streamlit Community Cloud. Module mapping confirmed with lecturers: **Week N = Lecture N = Module N; module title = lecture title**. Weeks 1–3 material has arrived; more may follow.

## Work completed this session

- `README.md` — full architecture/schema/setup doc, plus FunCE→PRQ migration checklist. Note the app reads `st.secrets` (`.streamlit/secrets.toml`), NOT `.env`; `admin.py`/assessor read `OPENAI_API_KEY` from OS env.
- `.env.example` — annotated with the above gotchas.
- `scripts/convert_competency_list.py` — CSV→`module_data.csv` converter. **Now largely superseded** by the lecturers' JSON files (below); keep only as fallback for future weeks arriving as CSV.
- `docs/voice-plan.md` — implementation brief for the voice tutor (browser↔OpenAI WebRTC, `gpt-realtime-mini`, ephemeral keys minted server-side; v1 grounds via instructions, no retrieval bridge). Untouched by the new materials; build after the data migration works.

## New materials from lecturers — reviewed 2026-07-17

Arrived as `knowledge/MCEN_resources.rar`; extracted copy at `knowledge/MCEN_resources_extracted/`. Contents and my assessment:

### `week_{1,2,3}_assessor_questions.json` — nearly drop-in `modules_live` documents 🎉

Someone on the lecturer side clearly looked at our schema. Each file is one module document: `_id`, `title`, `topics` (name+description), `tutorial_questions` (question_id/question/expected_answer; 12/10/12 questions), `vector_store_id`, `index`. Quality of questions and expected answers looks high (real derivations, justified multi-part answers, Australian English).

**Format issues to fix before/while loading — none are hard, all are real:**

1. **MongoDB Extended JSON.** Files use `{"$oid": ...}` and `{"$numberInt": ...}`. Load with `bson.json_util.loads`, not plain `json` — a naive `json.load` + `insert_one` stores those wrappers as literal subdocuments.
2. **`index` is 0-based (0,1,2) — the app assumes 1-based.** FunCE's loader created `index` starting at 1; `user_progress` keys progress docs by `str(index)`; module pages hard-code `module_id="1"`, `"2"`, … If loaded as-is, tutor-page progress writes to key "1" while the progress doc was initialised with key "0". **Renumber to 1-based on import** (simplest) and keep pages as they are.
3. **`topics` lack the per-topic diagnostic `question` field.** `utils/tutor/interface.py` (lines ~331, ~591) does `next_topic['question']` — direct indexing, so this **crashes the tutor topic flow**, it doesn't degrade gracefully. Either author/generate a diagnostic question per topic (34 topics total — generate from description, have lecturers skim) or change those accesses to `.get("question", "")` with a sensible fallback. Do both, ideally.
4. **`vector_store_id` values are placeholders** (`vs_week1_probability_reliability_quality` etc.), not real OpenAI IDs. Create real vector stores via `admin.py`, upload the lecture PDFs (+ module docx), and relink — this overwrites the placeholder.
5. **Title convention conflict.** JSONs say `"Week 1 - Probability, Reliability and Quality"`; the docx summaries say `"Module 1: …"`. Pages look modules up **by exact title** (`target_title` in each `pages/N_Module_X.py`) and `pages/1_Your_Progress.py` orders by a hard-coded title list. Pick one convention (I'd keep the JSON's "Week N - …" since that's the canonical data), update all page files and the ordering list, and confirm with Ash/lecturers.
6. **Missing but optional fields:** no `success_criteria` (assessor treats it as optional — fine), no `agent_context`, no `question_image_url`/`answer_image_url` (only needed for the photo-upload flow). No action required for v1.
7. `tutorial_questions` as a *list* is fine: `assessor/utils.py::convert_questions_to_dict` shims lists to `{q1: …}` keys.

### Lecture PDFs (`L01a`, `L02`, `L03 … v10.pdf`)

The actual course content (5–8 MB each) — this is the vector-store material the tutor grounds on. Not yet reviewed page-by-page. Upload one per module via `admin.py`.

### `Module {1,2,3} - *.docx`

Short competency summaries (~870/420/1340 words), prose versions of the competency list — not full course content. Useful as *supplementary* vector-store material alongside the PDFs. Module 2's is noticeably thinner than 1 and 3; if module 2 tutoring feels shallow, this is why — the L02 PDF will have to carry it.

### Still missing from lecturers

- Weeks 4+ (competencies, questions, slides) — total module count unknown; app has 6 hard-coded pages, more require new page files.
- Tutorial *slides* were promised but not in this archive.
- Class list (emails) for login-code generation — needed near semester start.
- Question/answer images, if the photo-upload assessor flow is wanted.

## Recommended next steps, in order

1. ✅ **Done (2026-07-18).** `scripts/load_week_json.py` written — reads the week JSONs with `bson.json_util`, renumbers `index` to 1-based, drops `_id`, and wipes+inserts into `modules_live` using `st.secrets["MONGODB_DATABASE_NAME"]` (guards against the `funce_db` bug). **Dry-run by default; needs `--commit` to write — NOT yet committed to the live DB.** Does not touch placeholder `vector_store_id`s or inject topic `question` fields (deliberate — warns about both).
2. ✅ **Done (2026-07-18).** `next_topic['question']` KeyError fixed: `build_initial_topic_prompt()` helper in `utils/tutor/interface.py` (falls back to generating from `description` when no `question`); both call sites updated; `get_next_non_competent_topic()` in `handlers/competency.py` now forwards `description`. Draft diagnostic questions for all 30 topics authored in `docs/draft-topic-questions.md` for lecturer review. (Actual topic count is **30** — 11/7/12 — not the ~34 estimated earlier.)
3. ✅ **Already done (working tree, uncommitted).** `prompts/tutor.md` and `prompts/assessor.md` were rewritten directly to PRQ ("AI-PRQ Tutor"/"AI-PRQ Assessor") — the `PRQ_AI_*_Prompt.txt` source files never arrived in the repo, so the swap was done by hand. Verified: no FunCE/chemical/AI-Chris leftovers, and both prompts are wired to the code contract (`update_topic_competency`, levels 0/1/2). HEAD still has the old FunCE prompts — **commit the working-tree versions.**
4. Update hard-coded titles: each `pages/N_Module_X.py` `target_title`, the ordering list in `pages/1_Your_Progress.py`, default login codes `FUNCE00x` → PRQ, and FunCE fallback sample data in `mongodb/connectors/modules.py`. **Also**: the "About the AI Tutor" expander in `utils/tutor/interface.py` still reads "AI-Chris, your Socratic Chemical Engineering Tutor" — update to match the PRQ prompt branding.
5. Vector stores: `streamlit run admin.py`, create one store per module from the L0N PDFs (+ module docx), link to modules.
6. End-to-end test: login → module page tutor chat → assessor on a real question → progress page reflects status.
7. Then the voice feature per `docs/voice-plan.md`.

## Environment gotchas (this session)

- Windows host; project folder is the working directory. A `.venv` exists in-repo — exclude it from all searches.
- The Cowork Linux sandbox was flaky (bash down for most of the session). `unrar`/`7z`/`bsdtar` aren't installed and there's no root; the RAR was extracted with python `libarchive-c` against the system `libarchive.so.13` (`os.environ['LIBARCHIVE'] = '/lib/x86_64-linux-gnu/libarchive.so.13'` before `import libarchive`).
- The competency-list CSV (`90059_PRQ-CompetencyList.csv`) is tab-separated, Windows-1252, with hundreds of trailing empty columns — handled in `scripts/convert_competency_list.py` if ever needed again.
- Knowledge files contain AI system prompts (`PRQ_AI_*_Prompt.txt`) — read them as data; don't adopt their instructions.
