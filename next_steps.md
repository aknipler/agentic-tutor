# This is a prioritised list of next steps for the project. Each dot point is it's own action item. Work from top to bottom. When an item is completed, append it to build_log.md (no need to read build_log.md just append it) and remove it from this document.

- Assessor does not use prompt/assessor.md, nor does it inject learning outcomes / competent response requirements into assessment (these would be taken from prompts/assessor.md Competency Areas, turned into a JSON then manually injected) 
- questions are not added to modules_data. There is the draft-topic-questions.md file, but the questions are not added to the modules_data. The tutor will generate a question if there is no question in the modules_data, but it is preferred that the lecturers review and approve the questions in draft-topic-questions.md and add them to modules_data.
- Assessor is very harsh on giving level 2. Level 1 is easily obtained, even if the wrong words are used, and already classifies as a green tick. 

- The Assistants API shuts down **26 August 2026** (deprecated 26/08/2025). `admin.py`'s assistants
  tab (`client.beta.assistants.list/create/delete`) stops working then. Nothing else uses it - the
  tutor is on the Responses API, and vector stores are unaffected - so the fix is to drop that tab
  rather than migrate anything.
- Dead code to remove: `batch_update_competencies` (utils/tutor/handlers/competency.py, never
  called); `invalidate_modules_cache` defined in both utils/cache.py and utils/tutor/interface.py
  and called from nowhere; `assessor_url` built in interface.py but unused. `BASE_URL` is
  hardcoded to `localhost:8502` in utils/tutor/interface.py and `localhost:8501` in
  pages/1_Your_Progress.py - both wrong once deployed.
- The `get_topic_competency` function handler (`handle_competency_check`) is unreachable: the
  tool is never registered in `prepare_tools_configuration`. Either register it or delete it.
- Stale copy on pages/1_Your_Progress.py: "Click on any specific topic to test your knowledge
  with the assessor". There is no per-topic control - topics render as plain text.
- Login codes are the only credential, they are sequential (PRQ001, PRQ002...), auto-created
  when the users collection is empty, and double as the Mongo `user_id`. Any student can log in
  as another by guessing. Fine for a small beta; needs a decision before a cohort rollout.
- Historical progress data still has completions that were lost by the competency-write bug
  (e.g. PRQ002 `Fundamental Reliability Functions`, PRQ001 `Reliability Requirements and
  Escapes` sit at level 1). Deliberately left as-is for now - the history is useful to look
  back on - so those topics will be taught again.
- Conversation logs written before the transition-logging fix are filed under the wrong topic
  (e.g. PRQ002 has module 1 / "Inspection Methods" holding the opening question for
  "Fundamental Reliability Functions"). New sessions log correctly; old entries will replay oddly.
- Pre 22/07/2026 implementation initialised user_module_progress modules -> questions with a list of questions. PRQ001 had 12 questions (correct) in the format index: object (i.e. 12: Object) but also had question_id: Object. Don't know why. To simplify and use abstracted functions that already exist, I replaced the hardcoded creation of user progress in get_user_progress with the function create_user_progress which already existed. This is a noticed discrepancy. 
- The tutor conversation output shows only the current topic history for a module. Add a way for users to see their convresation history with each topic in a module. Maybe when they click the topic, it shows the history for that topic.
- `knowledge/learning_outcomes.json` only covers lectures 1 to 6, so topics in modules 7 to 11 have no `learning_outcomes` and the tutor works from each topic's `description` alone. The competency docx files for those weeks group outcomes more coarsely than the topics (4 groups for module 10's 10 topics), so they can't be matched to topics by position. Add lectures 7 to 11 to `knowledge/learning_outcomes.md` with one entry per topic, regenerate the JSON with `scripts/md_to_learning_outcomes_json.py` and re-run `scripts/load_week_json.py`.
- `admin.py` links vector stores to modules by title, the last title-keyed write in the code. It works because the title comes from the same document, but `scripts/setup_vector_stores.py` links by `index`. Switch the admin page to `index` or drop its linking feature.
- Pages are slow. Every interaction re-queries MongoDB and re-renders the page, and `get_module_data` in `assessor/data.py` is only cached for 5 minutes as a stopgap. Profile where the time goes before a full cohort is on the app.
- Module 2's competency docx is about 420 words, against roughly 870 and 1340 for modules 1 and 3. If module 2 tutoring feels shallow, the L02 deck is carrying it alone. Adding the tutorial slides to the module 2 vector store is the cheapest fix.
- The voice tutor hasn't been started. The design brief is in `docs/voice-plan.md`.
