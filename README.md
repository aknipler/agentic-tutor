# PRQ Agentic Tutor

Streamlit-based AI tutor/assessor for **Probability, Reliability and Quality (MCEN90059)**. Students log in with a code, chat with a Socratic tutor per module (OpenAI + per-module vector stores for file search), and get assessed on tutorial questions with progress tracked in MongoDB.

Module mapping (confirmed with lecturers): **Week N = Lecture N = Module N**, and the module title is the lecture title. The initial rollout covers **weeks 1–3**; lecturers will decide about extending to 6+ after gauging student engagement.

## Project layout

| Path | Purpose |
|---|---|
| `Home.py` | Streamlit entry point (login page) |
| `pages/` | `1_Your_Progress.py`, module pages `2_Module_1.py`–`4_Module_3.py`, `8_Assessor.py` |
| `utils/tutor/` | Tutor chat interface (loads `prompts/tutor.md` as system prompt) |
| `utils/modules.py` | Module lookup helpers — **modules are keyed by `index`, never by title** |
| `assessor/` | Answer assessment (OpenAI, `prompts/assessor.md`) |
| `mongodb/connectors/` | All DB access (`base.py` = client, `modules.py`, `user_management.py`, `user_progress.py`) |
| `scripts/` | Data-loading and setup utilities |
| `admin.py` | Separate Streamlit admin app: vector stores, module links, users |
| `prompts/` | Tutor and assessor system prompts (PRQ versions) |
| `knowledge/MCEN_resources_extracted/` | **Canonical PRQ source material** from lecturers (see below) |

### How modules are identified

Every module document carries an `index` (1-based). That is the only key used to
find a module — page files, progress ordering, and progress records all resolve
through it. **Titles are data, not keys**: they come from the lecturers' files and
can change without any code change. Helpers live in `utils/modules.py`
(`find_module_by_index`, `sort_modules_by_index`).

Adding a week later means: drop its files in, run the two scripts below, and copy
one module page with `MODULE_ID = "4"`. No title edits anywhere.

## Setup

```bash
uv sync                          # preferred (pyproject.toml + uv.lock)
# or: python -m venv .venv && .venv\Scripts\activate && pip install -r requirements.txt
```

### Secrets — important

The app reads credentials via `st.secrets`, **not** from `.env`. There is no `python-dotenv` in this project, so a `.env` file is silently ignored by the Streamlit app. Instead create `.streamlit/secrets.toml`:

```toml
OPENAI_API_KEY = "sk-..."
MONGODB_USERNAME = "your_atlas_user"
MONGODB_PASSWORD = "your_atlas_password"
MONGODB_CONNECTION_STRING = "mongodb+srv://your_atlas_user:<db_password>@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority"
MONGODB_DATABASE_NAME = "MCEN900592026Sem2"
```

Notes:
- `MONGODB_CONNECTION_STRING` must contain the literal placeholder `<db_password>` — `mongodb/connectors/base.py` does `connection_string.replace("<db_password>", password)`.
- `MONGODB_USERNAME` is read but never actually used to build the connection (the username is baked into the connection string). Kept for compatibility.
- `admin.py` and `assessor/openai_assessor.py` read `OPENAI_API_KEY` from **environment variables** (`os.getenv`), not `st.secrets`. Set it in your shell too (`$env:OPENAI_API_KEY="sk-..."` in PowerShell). `scripts/setup_vector_stores.py` accepts either.
- Scripts run outside a Streamlit session still read `.streamlit/secrets.toml`, but only if you run them **from the project root**. Streamlit will log `No runtime found` / `missing ScriptRunContext` warnings — these are harmless.
- On Streamlit Community Cloud, paste the same TOML into the app's Secrets settings.
- Keep `.env` / `secrets.toml` out of git.

## Course material and vector stores

**The app never reads `knowledge/` at runtime.** (The one exception is
`assessor/ui.py`, which reads question/answer images from `knowledge/images/`.)
Course content reaches the tutor *only* through OpenAI vector stores: files are
uploaded to OpenAI, which chunks, embeds and indexes them; MongoDB stores just
the resulting `vector_store_id`, which the tutor passes to its `file_search`
tool. `knowledge/` is therefore a **staging area**, not a runtime dependency.

Canonical PRQ material lives in `knowledge/MCEN_resources_extracted/`:

| File | What it is | Used for |
|---|---|---|
| `L01a`, `L02`, `L03 … v10.pdf` | The actual lecture slide decks (349 slides total) | Primary vector-store content |
| `Module {1,2,3} - <title>.docx` | Short competency summaries (~870/420/1340 words) | Supplementary vector-store content |
| `week_{1,2,3}_assessor_questions.json` | Module definitions: topics + tutorial questions | Loaded into `modules_live` — **never** uploaded to a vector store |

> ⚠️ The `week_*.json` files contain `expected_answer` for every tutorial
> question. Indexing them would let the tutor hand students the model answers.
> `scripts/setup_vector_stores.py` excludes `.json` for exactly this reason.

> ⚠️ `knowledge/Module {1,2,3}.docx` / `.pdf` at the **top level** are leftover
> **FunCE chemical-engineering** content, not PRQ. Do not upload them. Only use
> files from `MCEN_resources_extracted/`.

You do **not** need to author your own per-module documents. The lecture PDFs
extract cleanly as text (~300 chars/slide, almost no image-only pages), and the
lecturers' `Module N - <title>.docx` summaries already play the role that
FunCE's hand-written `Module N.docx` files did.

## MongoDB structure and initialisation

Database: whatever `MONGODB_DATABASE_NAME` is set to. The app uses these collections:

### `modules_live` — one document per module

This is what the module pages and progress page read. Actual shape as delivered by the lecturers and loaded by `scripts/load_week_json.py`:

```json
{
  "title": "Week 1 - Probability, Reliability and Quality",
  "index": 1,
  "vector_store_id": "vs_...",
  "topics": [
    { "name": "Definition of Reliability", "description": "Explain reliability as ..." }
  ],
  "tutorial_questions": [
    { "question_id": "1.1", "question": "Define product reliability ...", "expected_answer": "..." }
  ]
}
```

Notes on this shape:
- `index` is **1-based**. The source files are 0-based; the loader renumbers them.
- Topics have **no `question` field**. That is expected — the tutor generates an opening question from `description` (`build_initial_topic_prompt` in `utils/tutor/interface.py`). Draft per-topic questions for lecturer review are in `docs/draft-topic-questions.md`; approved ones can be added as a `question` field.
- Optional fields the assessor tolerates but the PRQ data omits: `success_criteria`, `agent_context`, `question_image_url`, `answer_image_url`.
- `tutorial_questions` may be a list or a dict; `assessor/utils.py::convert_questions_to_dict` normalises it.

### `users` — login codes

```json
{ "login_code": "PRQ001", "name": "optional", "created_at": "..." }
```

Auto-seeded on first run of `Home.py` with defaults `PRQ001`–`PRQ003` if the collection is empty.

### `user_module_progress` — one document per student

Created automatically on a user's first login, keyed by `str(modules[].index)` from `modules_live`:

```json
{
  "user_id": "PRQ001",
  "modules": {
    "1": {
      "progress": 0, "status": "not_started",
      "topics": { "Definition of Reliability": { "progress": 0, "status": "not_started" } },
      "questions": { "1": { "status": "not_started", "attempts": 0, "last_attempt": null } }
    }
  }
}
```

### Initialisation order

1. Create a MongoDB Atlas cluster + DB user; put credentials in `.streamlit/secrets.toml`.
2. **Load module data** — wipes and repopulates `modules_live` from the week JSONs:
   ```bash
   .venv/Scripts/python.exe scripts/load_week_json.py            # preview
   .venv/Scripts/python.exe scripts/load_week_json.py --commit   # write
   ```
3. **Create vector stores** — creates one store per module, uploads that module's
   PDF + docx, and writes the real `vector_store_id` back:
   ```bash
   .venv/Scripts/python.exe scripts/setup_vector_stores.py            # preview
   .venv/Scripts/python.exe scripts/setup_vector_stores.py --commit   # create + upload
   ```
   (Or do it by hand in `admin.py`. Until this step runs, `vector_store_id` holds
   the lecturers' placeholder and **tutor chat will fail** — the placeholder is not
   a real OpenAI id.)
4. Create student logins via `admin.py`, or rely on the default `PRQ00x` codes.
5. `streamlit run Home.py`.

Both scripts are **dry-run by default** and require `--commit` to write, since each is destructive or billable. Both refuse to run against a database named `funce_db`.

## Running

```bash
streamlit run Home.py    # student app
streamlit run admin.py   # vector-store / user admin (needs OPENAI_API_KEY env var)
streamlit run debug.py   # environment/file sanity checks
```

## Known issues (inherited from FunCE)

- `scripts/update_module_data.py` references `st.secrets` but **never imports streamlit** — it raises `NameError` if run. It is the old CSV-based loader, superseded by `load_week_json.py`.
- `scripts/load_data.py` is a **legacy** loader (older JSON schema, writes to a `modules` collection the app no longer reads).
- `mongodb/connectors/modules.py` contains legacy functions (`get_module_by_id`, `get_question_details`, `get_module_topics`, `get_all_modules`) that read `modules`/`questions` collections the current UI doesn't use. `get_all_modules` has no callers at all.
- `admin.py` links a vector store to a module **by title** (`update_module_vector_store`), the last title-keyed write in the codebase. It works because the title comes from the same document, but `scripts/setup_vector_stores.py` links by `index` instead.

## FunCE → PRQ migration status

- [x] Tutor and assessor prompts swapped to PRQ (`AI-PRQ Tutor` / `AI-PRQ Assessor`).
- [x] Module data loaded from `week_*_assessor_questions.json` via `scripts/load_week_json.py`.
- [x] Hard-coded module titles removed — modules keyed by `index` (`utils/modules.py`).
- [x] FunCE sample-data fallback replaced with actionable diagnostics.
- [x] Default login codes are `PRQ00x`.
- [x] Tutor no longer crashes on topics with no diagnostic `question`.
- [ ] Vector stores created from the PRQ lecture PDFs and linked (`scripts/setup_vector_stores.py`).
- [ ] End-to-end test: login → tutor chat → assessor → progress.
- [ ] Replace `knowledge/micro-competencies.md` and remove leftover FunCE files from `knowledge/`.
- [ ] Weeks 4+ if lecturers extend (add source files + one page file per module).
- [ ] Voice tutor — see `docs/voice-plan.md`.
