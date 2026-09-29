# Architecture

How the app works internally. Setup and adapting the app to another subject are covered in the
[README](../README.md).

## Modules are keyed by `index`

Every module document has an `index` (1, 2, 3, …), and it is the only identifier the code uses.
Module pages look their module up by it, progress is stored under `str(index)` and the assessor
records attempts against it. Titles come from the source files and can change without touching
code. Use `find_module_by_index` and `sort_modules_by_index` in `utils/modules.py`.

The loader takes `index` from the source filename, so `week_4_...json` becomes module 4. The
lecturers' files also carry their own `index` field numbered from 0, which the loader only uses
as a cross-check.

## The topic loop

A module page teaches one topic at a time. The app decides which topic is current and tells the
model. The model never picks one itself.

When the tutor judges the student competent it calls `update_topic_competency(level, reason)`
with level 2. The page congratulates the student and moves on only once that write is
confirmed. The next topic is the one after the current one, wrapping back to fill any gaps
earlier in the module. When every topic is at level 2 the module is finished and its chat input
is disabled. A competency write can never lower a level that is already recorded.

Students don't have to go in order. Asking to move ("can we jump to ANOVA?") makes the tutor
call `switch_topic(topic_name, reason)`. The app matches the name against the module's own
topics, so a paraphrase or abbreviation still works. If the name is unknown or matches more
than one topic, the topic list goes back to the tutor so it can ask the student. After a
switch, everything else in the turn follows the new topic, including the competency write.

The topic a student ends up on is saved as `last_topic`, and their next session resumes there
rather than at the first unfinished topic.

Every way of arriving at a topic goes through `open_topic`. A topic with a logged conversation
resumes from it, and only a topic with no history gets a new opening question. Nobody is asked
to prove themselves twice on work they've already done. Chat history is replayed from the
conversation log on login, so a student picks up mid-topic.

## Database

The app uses two MongoDB databases. `MONGODB_DATABASE_NAME` holds the modules, logins and
progress, and `MONGODB_LOGS_DATABASE_NAME` holds the conversation logs.

### `modules_live`

One document per module, in the shape of the source JSON described in the README. The loader
adds `index`, `vector_store_id` and each topic's `learning_outcomes` (merged from
`knowledge/learning_outcomes.json`). `tutorial_questions` can be a list or a dict, and both are
normalised on read.

### `users`

```json
{ "login_code": "PRQ001", "created_at": "..." }
```

### `user_module_progress`

One document per student, created on first login.

```json
{
  "user_id": "PRQ001",
  "modules": {
    "1": {
      "progress": 0, "status": "not_started",
      "last_topic": "Definition of Reliability",
      "topics":    { "Definition of Reliability": { "progress": 0, "status": "not_started" } },
      "questions": { "1": { "status": "not_started", "attempts": 0, "competency_level": 0 } }
    }
  }
}
```

- Modules are keyed by `str(index)`.
- Topics are keyed by name. Renaming a topic in the source data orphans every student's
  progress on it, so treat topic names as fixed once a cohort has started.
- Questions are keyed by position, and `"1"` is the first question in the module. Reordering
  questions moves students' results onto different questions.
- `last_topic` records where a student chose to be. Competency levels only show what is
  finished, so a student who jumped ahead would otherwise be sent back to the first unfinished
  topic. It is updated on every topic change and ignored if that topic no longer exists.
- `progress` and `competency_level` use the 0/1/2 scale.

### Conversation logs

`user_conversations` holds every tutor turn, keyed by user, module `index` and topic name.
`user_submissions` holds assessor submissions. The tutor reads `user_conversations` back on
login to restore chat history, so the app depends on this database at runtime.

## Course material

The app doesn't read `knowledge/` at runtime. The one exception is `assessor/ui.py`, which
loads question and answer images from `knowledge/images/`.

Lecture material reaches the tutor through OpenAI only. `setup_vector_stores.py` uploads each
module's files to a vector store and MongoDB keeps the `vector_store_id`, which the tutor
passes to its `file_search` tool. You can reorganise `knowledge/` freely as long as the setup
scripts can still find the files.

## Caching

Never give a page its own `@st.cache_data` copy of a shared lookup. Streamlit keys a cached
function by its module, qualified name and source text, and every page script runs as
`__main__`. Two pages with the same zero-argument helper therefore share one cache entry. This
is how each module page once showed another module's title and vector store. Cache once in an
importable module and key it by an argument, as `get_cached_module` in `utils/cache.py` does.

`get_modules_data` keeps the module list in session state for the whole session. A student who
is already logged in won't see newly loaded modules until they log in again.

`get_module_data` in `assessor/data.py` is cached for 5 minutes and cleared after each
submission, so results show up straight away.
