# This is a prioritised list of next steps for the project. Each dot point is it's own action item. Work from top to bottom. When an item is completed, append it to build_log.md (no need to read build_log.md just append it) and remove it from this document.

- Update README.md
- Assessor does not use prompt/assessor.md, nor does it inject learning outcomes / competent response requirements into assessment (these would be taken from prompts/assessor.md Competency Areas) 
- questions are not added to modules_data. There is the draft-topic-questions.md file, but the questions are not added to the modules_data. The tutor will generate a question if there is no question in the modules_data, but it is preferred that the lecturers review and approve the questions in draft-topic-questions.md and add them to modules_data.
- Assessor is very harsh on giving level 2. Level 1 is easily obtained, even if the wrong words are used, and already classifies as a green tick. 
- When submitting the answer for the question, it always shows "Error saving assessment results” message. (Note: I am not sure if this was for the login codes that did not have a user_progress created in the database.) (Mac OS)

- Pre 22/07/2026 implementation initialised user_module_progress modules -> questions with a list of questions. PRQ001 had 12 questions (correct) in the format index: object (i.e. 12: Object) but also had question_id: Object. Don't know why. To simplify and use abstracted functions that already exist, I replaced the hardcoded creation of user progress in get_user_progress with the function create_user_progress which already existed. This is a noticed discrepancy. 
- The tutor conversation output shows the entire conversation history for that module. Currently feature, would it be preferable just to show the output for that particular competency? 
