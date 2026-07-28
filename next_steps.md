# This is a prioritised list of next steps for the project. Each dot point is it's own action item. Work from top to bottom. When an item is completed, append it to build_log.md (no need to read build_log.md just append it) and remove it from this document.

- Assessor does not use prompt/assessor.md, nor does it inject learning outcomes / competent response requirements into assessment (these would be taken from prompts/assessor.md Competency Areas, turned into a JSON then manually injected) 
- questions are not added to modules_data. There is the draft-topic-questions.md file, but the questions are not added to the modules_data. The tutor will generate a question if there is no question in the modules_data, but it is preferred that the lecturers review and approve the questions in draft-topic-questions.md and add them to modules_data.
- Assessor is very harsh on giving level 2. Level 1 is easily obtained, even if the wrong words are used, and already classifies as a green tick. 

- Five-second dead zone after a topic transition swallows a message. `handle_topic_transition`
  (utils/tutor/interface.py) returns "Processing topic transition, please wait..." if the student
  replies within 5s of moving to a new topic. Their message is already in the chat history and
  `current_prompt` is cleared, so the question is silently dropped and they have to retype it;
  that branch also doesn't clear `in_topic_transition`. The filler text stays in the transcript
  permanently. Decide whether the 5s guard is still needed at all now that the transition only
  fires on a confirmed level-2 write - if it is, queue the message instead of discarding it.
- `current_topic` is a single session-wide key shared by every module page
  (utils/tutor/state.py), while chat history is keyed per module. Visiting a second module and
  returning leaves the first tracking the other module's topic. `ensure_current_topic_for_module`
  resyncs it on every turn so no data is corrupted, but the key should be scoped per module
  (`current_topic_{module_id}`) like `messages_module_{id}` and `topic_cutoff_index_{id}` -
  roughly a dozen mechanical call sites.
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
- The tutor conversation output shows the entire conversation history for that module. Currently feature, would it be preferable just to show the output for that particular competency? 
