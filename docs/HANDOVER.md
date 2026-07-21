# Handover — PRQ Agentic Tutor

State of the project as of 2026-07-19. Read `README.md` first — it covers architecture, setup,
the data model, and how to adapt the app to another subject. This file only records **current
state and what is left to do**.

## Status

The FunCE → PRQ migration is **complete**. The app runs end-to-end for weeks 1–3 and has been
manually tested: login → tutor chat → assessor submission → progress display.

Verified working:

- **Module data.** `modules_live` holds 3 modules, indices 1/2/3, loaded from the lecturers'
  week JSONs via `scripts/load_week_json.py`.
- **Vector stores.** Real OpenAI stores (`vs_6a5b…`) built and linked per module. Tutor chat
  responds on-topic and grounded in the lecture material.
- **Assessor.** Grades 0/1/2 with written feedback, records attempts, and persists results.
- **Logins.** `users` holds `PRQ001`–`PRQ003`. The old FunCE codes and their progress have been
  removed.

Modules are keyed by their `index` field throughout — never by title. This is the invariant most
worth protecting; breaking it is what caused the assessor's split-record bug.

## Deployment plan

Weeks 1–3 go live first. The lecturers will gauge student engagement and then decide whether to
extend to 6 weeks and beyond. Adding a week requires no code change beyond one page file — see
the README's adaptation section.

## Outstanding

### 1. `admin.py` access check is broken

`check_admin_access()` calls Python's built-in `input()`:

```python
if st.secrets["ADMIN_PASSWORD"] == input("Enter admin password: "):
```

`input()` reads from the server's stdin, not the browser. Under `streamlit run` this either
blocks the script thread waiting on the terminal or raises, which the surrounding `except`
swallows into "You don't have permission." Either way the admin dashboard is unusable.

Fix: prompt in the UI instead, e.g. a `st.text_input(..., type="password")` gated behind a
form, storing the result in `st.session_state`. Note the comparison is also plaintext and not
constant-time — acceptable for a prototype guard against accidental clicks, but it is not a
security control and should not be described as one.

### 2. Waiting on the lecturers

- **Class list** (student emails) — needed before semester start to generate real login codes
  with `scripts/create_users.py`. Until then only the three `PRQ00x` defaults exist.
- **Tutorial slides** — promised but never delivered. Would be useful supplementary
  vector-store content, particularly for module 2 (see below).
- **Weeks 4+** — competencies, questions and slides, if the subject is extended.

### 3. Draft topic questions need review

`docs/draft-topic-questions.md` holds an authored opening question for each of the 30 topics.
None are in the database yet. Topics without a `question` field work fine — the tutor generates
an opener from the topic description — so this is an improvement, not a blocker. Have the
lecturers skim them, then add the approved ones as a `question` field per topic and reload.

### 4. Known rough edges

- **Navigating mid-assessment loses the answer.** Changing page while grading is in flight
  abandons the request and clears the text box. The assessor page now warns about this; making
  it genuinely safe needs the submission to survive a rerun.
- **Pages are slow.** Every interaction re-queries MongoDB and re-renders. `get_module_data` is
  cached for 5 minutes as a band-aid and cleared explicitly after a submission. The underlying
  cost has not been profiled — worth doing before a full cohort is on it.
- **Module 2 is thinner than 1 and 3.** Its competency docx is ~420 words against ~870 and
  ~1340. If module 2 tutoring feels shallow, the L02 deck is carrying it alone; the promised
  tutorial slides are the cheapest fix.
- **`scripts/create_users.py` has no re-run guard.** Running it twice mints a second set of
  codes for the same students. Run it once, after the module data is loaded.
- **`admin.py` links vector stores by title**, the last title-keyed write in the codebase.
  `scripts/setup_vector_stores.py` links by `index` and is the safer path.

### 5. Not started

- **Deployment.** Target is Streamlit Community Cloud; secrets go in the app's Secrets settings
  as TOML. Not yet deployed.
- **Voice tutor.** Design brief in `docs/voice-plan.md`, untouched. Build after the text app
  has been through real student use.

## Conventions worth keeping

- Scripts in `scripts/` are **dry-run by default** and require `--commit` to write. Every one of
  them is destructive, billable, or both.
- The `week_*_assessor_questions.json` files contain `expected_answer` for every tutorial
  question. They must never be uploaded to a vector store; `setup_vector_stores.py` excludes
  `.json` deliberately.
- Competency is 0/1/2 (not started / partial / full) in the tutor, the assessor, both prompts,
  and the database.
- Secrets come from `st.secrets` (`.streamlit/secrets.toml`), never `.env` — the project has no
  `python-dotenv`, so a `.env` file is silently ignored.
