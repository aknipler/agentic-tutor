# PRQ Agentic Tutor

A Streamlit AI tutor and assessor for **Probability, Reliability and Quality (MCEN90059)**.

Students log in with a code and work through one module per lecture week. Each module has a
Socratic tutor grounded in that week's lecture material, plus tutorial questions that an AI
assessor grades. Each student's progress is stored in MongoDB.

Nothing about the subject is hard-coded. See [Adapting to another subject](#adapting-to-another-subject).
For the internals, including the topic loop and the database layout, read
[docs/architecture.md](docs/architecture.md).

## How it works

```
Home.py                       login with a code, checked against the `users` collection
  |
  +-- pages/N_Module_X.py     one page per module
  |     |
  |     +-- Socratic tutor chat (OpenAI + that module's vector store)
  |     |     marks each topic 0/1/2 with an update_topic_competency tool call
  |     |
  |     +-- tutorial questions -> "Try Question" -> Assessor
  |
  +-- pages/13_Assessor.py    submit an answer (text or images), graded 0/1/2 with feedback
  |
  +-- pages/1_Your_Progress.py   topic and question status for each module
```

Two system prompts drive the behaviour, `prompts/tutor.md` and `prompts/assessor.md`. Both are
plain Markdown, so edit them directly to change the tone or how strictly answers are graded.

Modules are identified by their `index` field (1, 2, 3, …) everywhere in the code. Titles are
data. Never look a module up by title. Use the helpers in `utils/modules.py` instead.

Competency is 0 (not started), 1 (partial) or 2 (full) everywhere in the app, including both
prompts and the database.

## Setup

### 1. Install

```bash
uv sync
```

Without uv, create a venv and run `pip install -r requirements.txt`.

### 2. Secrets

The app reads `st.secrets`, not `.env`. There is no `python-dotenv`, so a `.env` file is
ignored. Create `.streamlit/secrets.toml` with these values.

```toml
OPENAI_API_KEY = "sk-..."
MONGODB_CONNECTION_STRING = "mongodb+srv://your_atlas_user:<db_password>@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority"
MONGODB_DATABASE_NAME = "your_database_name"
MONGODB_LOGS_DATABASE_NAME = "agentic_tutor_logs"
ADMIN_PASSWORD = "your_admin_password"
```

- `MONGODB_LOGS_DATABASE_NAME` holds the conversation logs. It can be the same database as
  `MONGODB_DATABASE_NAME`.
- `admin.py` and `assessor/openai_assessor.py` read `OPENAI_API_KEY` from the environment, so
  export it as well. In PowerShell that is `$env:OPENAI_API_KEY="sk-..."`.
- On Streamlit Community Cloud, paste the same TOML into the app's Secrets settings.
- Keep `secrets.toml` out of git.

### 3. Load module data

```bash
.venv/Scripts/python.exe scripts/load_week_json.py            # preview
.venv/Scripts/python.exe scripts/load_week_json.py --commit   # write
```

This reads `knowledge/MCEN_resources_extracted/week_*_assessor_questions.json` and replaces the
`modules_live` collection. The preview checks every file and warns about any change that would
detach students' existing progress.

### 4. Build the vector stores

```bash
.venv/Scripts/python.exe scripts/setup_vector_stores.py            # preview
.venv/Scripts/python.exe scripts/setup_vector_stores.py --commit   # create and upload
```

This creates an OpenAI vector store for each module that doesn't have one yet, uploads that
module's lecture files and links the store to the module. Pass `--name-prefix PRQ` to set how
the stores are named in the OpenAI dashboard.

> Tutor chat fails on every message for a module until its store is built. The assessor
> doesn't use retrieval, so it works either way.

### 5. Create logins, then run

For a cohort, put a `data/classlist.csv` with an `Email` column in place and run
`scripts/create_users.py`. It generates a code for each student plus 15 spares, writes them to
`data/user_codes.csv` and creates each student's progress record. To make a batch of codes
without a class list, use `scripts/generate_and_load_codes.py`. If the `users` collection is
empty, `PRQ001` to `PRQ003` are seeded automatically.

Run this after step 3, because progress records are set up for whichever modules exist at the
time. `create_users.py` has no re-run guard, and running it twice issues a second set of codes.

```bash
streamlit run Home.py     # student app
streamlit run admin.py    # vector stores, module links and users (needs OPENAI_API_KEY in env)
streamlit run debug.py    # environment checks
```

Every script in `scripts/` is a dry run by default and only writes with `--commit`.

## Adapting to another subject

Use a new `MONGODB_DATABASE_NAME` for each subject. The loader keeps whichever vector store is
already linked to a module number, so reusing a database would leave the old subject's lecture
material attached.

1. **Module data.** Write one JSON file per module with the module number at the start of the
   filename, e.g. `week_4_questions.json`. Load them with `scripts/load_week_json.py`, adding
   `--data-dir` and `--glob` if they live somewhere else or are named differently.

   ```json
   {
     "title": "Week 1 - Probability, Reliability and Quality",
     "topics": [
       { "name": "Definition of Reliability", "description": "Explain reliability as ..." }
     ],
     "tutorial_questions": [
       { "question_id": "1.1", "question": "Define product reliability ...", "expected_answer": "..." }
     ]
   }
   ```

   Every topic needs a `name`, and every question needs `question` and `expected_answer`. The
   tutor writes each topic's opening question from its `description`, or uses the topic's
   `question` field if you supply one. The assessor also accepts `question_image_url` and
   `answer_image_url` on a question. Titles can follow any convention.

   Progress is stored against topic names and question positions. Once students have started,
   don't rename topics or reorder questions. The preview warns you if a load would do either.

2. **Course material.** Put each module's lecture files in the source folder with the module
   number at the start of the name (`L04 ...`, `Module 4 - ...`), or in a folder per week such
   as `week_04/`. The accepted prefixes and file types are listed in `utils/course_files.py`.
   Then run `scripts/setup_vector_stores.py`. Keep worked solutions out of the folder, because
   the tutor can quote anything in its vector store. The module JSON files are never uploaded
   since they contain the expected answers.

3. **Prompts.** Edit `prompts/tutor.md` and `prompts/assessor.md`. Keep the
   `update_topic_competency(level, reason)` tool and the 0/1/2 scale, because the code depends
   on both. The tool has no topic argument on purpose, since the app supplies the current
   topic. Don't let the prompt announce that a topic is finished either. The app moves on only
   after the competency write succeeds.

4. **Pages.** Each module page in `pages/` is one call to `render_module_page`.

   ```python
   render_module_page(module_id="4", release_date=datetime(2026, 8, 15, 23, 59))
   ```

   Copy a page and change the module number and unlock date, or leave out `release_date` for
   no lock. The number at the start of the filename sets the sidebar order, so renumber
   `N_Assessor.py` to keep it last. A page whose module isn't loaded yet says so, which means
   you can add pages ahead of the content.

5. **Branding.** Change the title in `Home.py` and the "About the AI Tutor" text in
   `utils/tutor/interface.py`.

## Notes

- Changing page while an answer is being graded abandons the request and loses the answer. The
  assessor page warns students about this.
- Removing a module leaves each student's progress record for it behind. Clear those with
  `scripts/cleanup_orphan_progress.py`.
- Login codes are the only credential, and each one is also the student's `user_id`. Anyone
  with another student's code can see and change that student's progress.
- `ADMIN_PASSWORD` stops accidental clicks in `admin.py`. It isn't a security measure.

## Known issues

`next_steps.md` is the working backlog. Read it before starting work, because several entries
record deliberate decisions rather than bugs. When an item is done, add it to `build_log.md` and
remove it from `next_steps.md`.

## Repository layout

| Path | Purpose |
|---|---|
| `Home.py` | Entry point and login |
| `pages/` | Progress page, module pages, assessor |
| `utils/tutor/` | Tutor chat, prompt assembly, competency tool calls, topic changes |
| `utils/modules.py` | Module lookup by `index` |
| `utils/pages.py` | Shared body of every module page, and the assessor page lookup |
| `utils/course_files.py` | Rules for matching source files to module numbers |
| `utils/status.py` | How the 0/1/2 scale is shown on screen, shared by every page |
| `assessor/` | Answer submission, grading, results UI |
| `mongodb/connectors/` | All database access |
| `mongodb/logger.py` | Conversation and submission logs (separate database) |
| `prompts/` | Tutor and assessor system prompts |
| `scripts/` | Setup and maintenance scripts |
| `knowledge/` | Source course material, staged for the vector stores |
| `docs/` | Architecture notes, voice tutor plan, draft topic questions |
