# PRQ Agentic Tutor

Streamlit-based AI tutor/assessor for **Probability, Reliability and Quality (MCEN90059)**. Students log in with a code, chat with a Socratic tutor per module (OpenAI + per-module vector stores for file search), and get assessed on tutorial questions with progress tracked in MongoDB.

## Project layout

| Path | Purpose |
|---|---|
| `Home.py` | Streamlit entry point (login page) |
| `pages/` | Module pages (`2_Module_1.py` … `7_Module_6.py`), progress page, assessor |
| `utils/tutor/` | Tutor chat interface (loads `prompts/tutor.md` as system prompt) |
| `assessor/` | Answer assessment (OpenAI, `prompts/assessor.md`) |
| `mongodb/connectors/` | All DB access (`base.py` = client, `modules.py`, `users`, `user_progress`) |
| `scripts/` | Data-loading utilities (run once to seed the DB) |
| `admin.py` | Separate Streamlit admin app: create/delete OpenAI vector stores, upload files, link a vector store to a module |
| `prompts/` | Tutor and assessor system prompts (currently FunCE — replace with PRQ versions) |
| `knowledge/NewSubjectDataToReplaceCurrentData/` | New PRQ source material: tutor prompt, assessor prompt, competency list CSV |

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt  # or: uv sync
```

### Secrets — important

The app reads credentials via `st.secrets`, **not** from `.env`. There is no `python-dotenv` in this project, so a `.env` file is silently ignored by the Streamlit app. Instead create `.streamlit/secrets.toml`:

```toml
OPENAI_API_KEY = "sk-..."
MONGODB_USERNAME = "your_atlas_user"
MONGODB_PASSWORD = "your_atlas_password"
MONGODB_CONNECTION_STRING = "mongodb+srv://your_atlas_user:<db_password>@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority"
MONGODB_DATABASE_NAME = "prq_bot"
```

Notes:
- `MONGODB_CONNECTION_STRING` must contain the literal placeholder `<db_password>` — `mongodb/connectors/base.py` does `connection_string.replace("<db_password>", password)`.
- `MONGODB_USERNAME` is read but never actually used to build the connection (the username is baked into the connection string). Kept for compatibility.
- `admin.py` and `assessor/openai_assessor.py` read `OPENAI_API_KEY` from **environment variables** (`os.getenv`), not `st.secrets`. Set it in your shell too (`$env:OPENAI_API_KEY="sk-..."` in PowerShell) or run those with the env var exported.
- On Streamlit Community Cloud, paste the same TOML into the app's Secrets settings.
- Keep `.env` / `secrets.toml` out of git.

## MongoDB structure and initialisation

Database: whatever `MONGODB_DATABASE_NAME` is set to (e.g. `prq_bot`). The app uses these collections:

### `modules_live` — one document per module

This is what the module pages and progress page read. Expected shape (as produced by `scripts/update_module_data.py`):

```json
{
  "title": "Module name",
  "index": 1,
  "vector_store_id": "vs_...",
  "topics": [
    { "name": "Topic name", "description": "Answer/description", "question": "Diagnostic question" }
  ],
  "tutorial_questions": [
    {
      "label": "Q1.1",
      "question": "Question text",
      "expected_answer": "...",
      "success_criteria": "...",
      "agent_context": "Extra info injected into the prompt",
      "question_image_url": "",
      "answer_image_url": ""
    }
  ]
}
```

`vector_store_id` is set afterwards via `admin.py` (link module → OpenAI vector store).

Note there is no separate "module_map" collection: the `module_map` you may see in `pages/1_Your_Progress.py` is just an in-memory dict `{title: module}` built from `modules_live`. Progress-page ordering, however, is driven by a hard-coded title list in that file — it must be updated to the PRQ module titles.

### `users` — login codes

```json
{ "login_code": "ABC123", "name": "optional", "created_at": "..." }
```

Auto-seeded on first run of `Home.py` with defaults `FUNCE001`–`FUNCE003` if empty (rename these for PRQ in `mongodb/connectors/user_management.py`).

### `user_module_progress` — one document per student

Created automatically on a user's first login, keyed by `modules[].index` from `modules_live`:

```json
{
  "user_id": "ABC123",
  "modules": {
    "1": {
      "progress": 0, "status": "not_started",
      "topics": { "Topic name": { "progress": 0, "status": "not_started" } },
      "questions": { "Q1.1": { "status": "not_started", "attempts": 0, "last_attempt": null } }
    }
  }
}
```

### Initialisation order

1. Create a MongoDB Atlas cluster + DB user; put credentials in `.streamlit/secrets.toml`.
2. Prepare two CSVs (see below) and run `python scripts/update_module_data.py` from a directory containing `module_data.csv` and `question_data_final.csv`. This wipes and repopulates `modules_live`.
3. Run `streamlit run admin.py` to create vector stores from your course PDFs and link each module to its vector store (writes `vector_store_id` into `modules_live`).
4. Create student logins: `python scripts/create_users.py` (expects `data/classlist.csv` with an `Email` column; writes `data/user_codes.csv` + spare codes), or just rely on the default codes.
5. `streamlit run Home.py`.

CSV columns expected by `update_module_data.py`:
- `module_data.csv`: `Module Number`, `Module Name`, `Topic`, `Description (Answer)`, `Questions`
- `question_data_final.csv`: `Module Number`, `Question label`, `Question text`, `Expected answer`, `Success criteria`, `Further information required in prompt`, `question_URL`, `answer_URL`

⚠️ **Known inconsistencies to fix (inherited from FunCE):**
- `scripts/update_module_data.py` and `scripts/load_data.py` hard-code the DB name `funce_db` instead of using `MONGODB_DATABASE_NAME`. If you run them as-is your data lands in the wrong database. Change `client[st.secrets["MONGODB_DATABASE_NAME"]]` to `client[<your db name>]` (or read it from secrets).
- `scripts/load_data.py` is a **legacy** loader (older JSON schema, writes to a `modules` collection the app no longer reads). Prefer `update_module_data.py`.
- `mongodb/connectors/modules.py` contains legacy functions (`get_question_details`, `get_module_topics`, `get_all_modules`) hard-coded to a `FunCE` database with `modules`/`questions` collections. The current UI doesn't use them; remove or update.

## Running

```bash
streamlit run Home.py    # student app
streamlit run admin.py   # vector-store admin (needs OPENAI_API_KEY env var)
streamlit run debug.py   # environment/file sanity checks
```

## FunCE → PRQ migration checklist

- [ ] Replace `prompts/tutor.md` with `knowledge/NewSubjectDataToReplaceCurrentData/PRQ_AI_Tutor_Prompt.txt` (loaded verbatim as the tutor system prompt).
- [ ] Replace `prompts/assessor.md` with `PRQ_AI_Assessor_Prompt.txt`.
- [ ] Build `module_data.csv` / `question_data_final.csv` from `90059_PRQ-CompetencyList.csv` via `scripts/convert_competency_list.py` and reload `modules_live`. Module mapping (confirmed with lecturers): Week N = Lecture N = Module N, module title = lecture title. Overview topic names come from `90059_Week1-3-CompetencyList-CF.docx` (paste into `OVERVIEW_NAMES` in the converter). Lecturers will supply further competency lists (JSON/docx), lecture slides, and tutorial slides — the CSV converter is an interim path.
- [ ] If the subject has more than 6 modules (one per lecture week), add `pages/N_Module_X.py` files — currently hard-coded at 6.
- [ ] Update hard-coded module titles in each `pages/N_Module_X.py` (`target_title = "Introduction to Chemical Engineering"` etc.) and the ordering list in `pages/1_Your_Progress.py`.
- [ ] Update sample/fallback data in `mongodb/connectors/modules.py` (FunCE sample modules) and default login codes `FUNCE00x`.
- [ ] Replace `knowledge/micro-competencies.md` with the PRQ competency breakdown.
- [ ] Upload PRQ course material to new vector stores via `admin.py` and relink modules.
- [ ] Fix the hard-coded `funce_db` in scripts (see above).
