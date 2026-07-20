# PRQ Agentic Tutor

A Streamlit AI tutor and assessor for **Probability, Reliability and Quality (MCEN90059)**.

Students log in with a code, work through one module per lecture week, chat with a Socratic
tutor grounded in that week's lecture material, and submit answers to tutorial questions for
automated assessment. Progress is tracked per student in MongoDB.

Nothing about the subject is hard-coded — see [Adapting to another subject](#adapting-to-another-subject).

---

## How it works

```
Home.py            login with a code, verified against the `users` collection
  |
  +-- pages/N_Module_X.py   one page per module
  |     |
  |     +-- Socratic tutor chat (OpenAI + that module's vector store)
  |     |     ...marks each topic 0/1/2 via an update_topic_competency tool call
  |     |
  |     +-- list of tutorial questions -> "Try Question" -> Assessor
  |
  +-- pages/8_Assessor.py   submit an answer (text and/or images), get graded 0/1/2 + feedback
  |
  +-- pages/1_Your_Progress.py   per-module topic and question status
```

Two OpenAI system prompts drive the behaviour: `prompts/tutor.md` (Socratic questioning,
never hand over answers) and `prompts/assessor.md` (grade against the expected answer).
Both are plain Markdown — edit them directly to change tone or grading strictness.

### Modules are keyed by `index`

Every module document carries an `index` (1, 2, 3, …). **That is the only identifier used
anywhere**: page files look up their module by it, progress records are stored under it, and
the assessor records attempts against it.

Titles are *data*, never keys. They come from your source files and can change freely without
touching code. Helpers are in `utils/modules.py` (`find_module_by_index`, `sort_modules_by_index`).

If you take one thing from this README: **never look a module up by title.**

---

## Setup

### 1. Install

```bash
uv sync                       # preferred
# or: python -m venv .venv && .venv\Scripts\activate && pip install -r requirements.txt
```

### 2. Secrets

The app reads `st.secrets`, **not** `.env` — there is no `python-dotenv` here, so a `.env`
file is silently ignored. Create `.streamlit/secrets.toml`:

```toml
OPENAI_API_KEY = "sk-..."
MONGODB_CONNECTION_STRING = "mongodb+srv://your_atlas_user:<db_password>@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority"
MONGODB_DATABASE_NAME = "your_database_name"
ADMIN_PASSWORD = "your_admin_password"
```

- Replace `<db_password>` placeholder etc.
- `admin.py` and `assessor/openai_assessor.py` read `OPENAI_API_KEY` from the **environment**,
  not from secrets. Export it too: `$env:OPENAI_API_KEY="sk-..."` (PowerShell).
- On Streamlit Community Cloud, paste the same TOML into the app's Secrets settings.
- Keep `secrets.toml` out of git.

### 3. Load module data

```bash
.venv/Scripts/python.exe scripts/load_week_json.py            # preview
.venv/Scripts/python.exe scripts/load_week_json.py --commit   # write
```

Reads `knowledge/MCEN_resources_extracted/week_*_assessor_questions.json` and replaces the
`modules_live` collection.

### 4. Build the vector stores

```bash
.venv/Scripts/python.exe scripts/setup_vector_stores.py            # preview
.venv/Scripts/python.exe scripts/setup_vector_stores.py --commit   # create + upload
```

Creates one OpenAI vector store per module, uploads that module's source files, and writes the
real store id back to the module.

> Until this runs, a module's `vector_store_id` is a placeholder that OpenAI will reject, and
> **tutor chat fails on every message** for that module. The assessor is unaffected — it does
> not use retrieval.

### 5. Create logins, then run

`PRQ001`–`PRQ003` are seeded automatically **only if the `users` collection is empty**. For a
real cohort, put a `data/classlist.csv` with an `Email` column in place and run
`scripts/create_users.py` — it generates a random code per student plus 15 spares, writes
`data/user_codes.csv`, and creates each student's progress record.

Run it *after* step 3: progress records are initialised against whatever modules exist at that
moment. It has no re-run guard, so running it twice mints a second set of codes.

```bash
streamlit run Home.py     # student app
streamlit run admin.py    # vector stores, module links, users (needs OPENAI_API_KEY in env)
streamlit run debug.py    # environment sanity checks
```

Every script above is **dry-run by default** and needs `--commit` to write.

---

## Data model

Three MongoDB collections, in the database named by `MONGODB_DATABASE_NAME`.

### `modules_live` — one document per module

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

- `index` is 1-based. Source files are 0-based; the loader renumbers them.
- `topics[].question` is **optional**. Supply one to control a topic's opening question;
  omit it and the tutor generates an opener from `description`.
- Optional extras the assessor tolerates: `success_criteria`, `agent_context`,
  `question_image_url`, `answer_image_url`.
- `tutorial_questions` may be a list or a dict; both are normalised on read.

### `users` — login codes

```json
{ "login_code": "PRQ001", "created_at": "..." }
```

### `user_module_progress` — one document per student

Created on first login, keyed by `str(index)`:

```json
{
  "user_id": "PRQ001",
  "modules": {
    "1": {
      "progress": 0, "status": "not_started",
      "topics":    { "Definition of Reliability": { "progress": 0, "status": "not_started" } },
      "questions": { "1": { "status": "not_started", "attempts": 0, "competency_level": 0 } }
    }
  }
}
```

Competency is `0` = not started, `1` = in progress/partial, `2` = completed/full, used
consistently by the tutor, the assessor, and both prompts.

---

## Course material

**The app never reads `knowledge/` at runtime** (the one exception is `assessor/ui.py`, which
loads question and answer images from `knowledge/images/`).

Content reaches the tutor only through OpenAI: files are uploaded to a vector store, OpenAI
chunks and indexes them, and MongoDB stores just the resulting `vector_store_id`, which the
tutor hands to its `file_search` tool. `knowledge/` is a **staging area**, not a runtime
dependency — you can reorganise it freely as long as the setup script can find the files.

`knowledge/MCEN_resources_extracted/` holds:

| File | Role |
|---|---|
| `L01a`, `L02`, `L03 … .pdf` | Lecture slide decks — primary vector-store content |
| `Module {1,2,3} - <title>.docx` | Competency summaries — supplementary content |
| `week_{1,2,3}_assessor_questions.json` | Module definitions — loaded into `modules_live`, **never** uploaded |

> The `week_*.json` files contain `expected_answer` for every tutorial question. Indexing them
> would let the tutor hand students the model answers, so `setup_vector_stores.py` excludes
> `.json` by design.

`setup_vector_stores.py` maps files to modules **by filename**: `L02 ...pdf`, `Module 2 ...docx`
and `week_2_....json` all resolve to module 2. Adding a new week means dropping its files in —
no code change.

---

## Adapting to another subject

The app has no subject-specific logic. To repoint it:

1. **Module data.** Produce one JSON per module in the shape above and load it with
   `scripts/load_week_json.py`. The only required fields are `title`, `index`, `topics`, and
   `tutorial_questions`. Titles can follow any convention — nothing matches on them.
2. **Course material.** Put each module's PDFs/DOCX in the source directory, named so the
   module number is at the start (`L04 ...`, `Module 4 - ...`), then run
   `scripts/setup_vector_stores.py`.
3. **Prompts.** Edit `prompts/tutor.md` and `prompts/assessor.md`. Keep the
   `update_topic_competency(topic_name, level, reason)` tool contract and the 0/1/2 scale —
   the code depends on both.
4. **Pages.** Add or remove `pages/N_Module_X.py`. Each is a ~45-line shim whose only
   subject-specific line is `MODULE_ID = "4"`; copy one and change that number. The file's
   numeric prefix controls sidebar order.
5. **Branding.** The title in `Home.py` and the "About the AI Tutor" text in
   `utils/tutor/interface.py`.

A module page whose data hasn't been loaded shows "not available yet" rather than an error, so
you can add pages ahead of content.

---

## Notes and limitations

- **Don't navigate mid-assessment.** Changing page while an answer is being graded abandons the
  request and loses the answer. The assessor page warns about this; it is not yet handled
  gracefully.
- **Page loads are slow.** Each interaction re-queries MongoDB and re-renders. `get_module_data`
  is cached for 5 minutes to compensate, and is explicitly cleared after a submission so results
  aren't stale.
- **`admin.py` requires an admin password in `.streamlit/secrets.toml`**. It is not a security measure, just a guard against
  accidental clicks.
- **`admin.py` links vector stores to modules by title**, the one remaining title-keyed write.
  It works because the title comes from the same document, but `setup_vector_stores.py` links
  by `index` and is the safer path.
- **Orphaned progress**: if you remove a module, students keep a progress record for it. Clear
  those with `scripts/cleanup_orphan_progress.py`.

## Repository layout

| Path | Purpose |
|---|---|
| `Home.py` | Entry point — login |
| `pages/` | Progress page, module pages, assessor |
| `utils/tutor/` | Tutor chat: prompt assembly, streaming, competency tool calls |
| `utils/modules.py` | Module lookup by `index` |
| `assessor/` | Answer submission, OpenAI grading, results UI |
| `mongodb/connectors/` | All database access |
| `prompts/` | Tutor and assessor system prompts |
| `scripts/` | Setup and maintenance utilities |
| `knowledge/` | Source course material (staging for vector stores) |
| `docs/` | Design notes — voice tutor plan, draft topic questions |
