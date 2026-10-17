"""Tests for utils.engagement_checks, using synthetic records and no database.

Run them from the repository root with

    .venv/Scripts/python.exe -m unittest discover -s tests -t .
"""
import unittest
from datetime import date, datetime, timedelta

from utils.engagement import Settings, StudentRecords, summarise_student
from utils.engagement_checks import (
    MAX_DETAIL_LINES,
    check_attempts,
    check_progress_clock,
    check_totals,
    question_texts,
)

QUESTIONS = {"1": {"1": "Question one", "2": "Question two"}}


def utc(month, day, hour=0, minute=0):
    return datetime(2026, month, day, hour, minute)


def submission(when, question="Question one", level=1, module="1"):
    return {"module": module, "question": question, "grade": level / 2, "timestamp": when}


def progress(attempts_by_question, last_attempt=None):
    return {
        "1": {
            "topics": {},
            "questions": {
                question_id: {"attempts": attempts, "last_attempt": last_attempt}
                for question_id, attempts in attempts_by_question.items()
            },
        }
    }


def conversation(pairs):
    return {"module": "1", "topic": "Topic A", "conversation": pairs, "timestamp": utc(8, 1)}


def metrics_for(students):
    rows = []
    for student in students:
        summary = summarise_student(student, Settings(), date(2026, 10, 17), [])
        if summary is not None:
            rows.append(summary[0])
    return rows


class QuestionTextTests(unittest.TestCase):
    def test_list_questions_are_numbered_from_one(self):
        modules = [{"index": 3, "tutorial_questions": [{"question": "A"}, {"question": "B"}]}]

        self.assertEqual(question_texts(modules), {"3": {"1": "A", "2": "B"}})

    def test_dict_questions_use_the_number_in_their_key(self):
        modules = [{"index": 3, "tutorial_questions": {"q2": {"question": "B"}, "q1": {"question": "A"}}}]

        self.assertEqual(question_texts(modules), {"3": {"2": "B", "1": "A"}})

    def test_modules_without_an_index_or_question_text_are_left_out(self):
        modules = [{"tutorial_questions": [{"question": "A"}]}, {"index": 2, "tutorial_questions": [{"label": "no text"}]}]

        self.assertEqual(question_texts(modules), {"2": {}})


class TotalsTests(unittest.TestCase):
    def test_error_turns_are_added_back_before_comparing(self):
        student = StudentRecords(
            "s1",
            [conversation([["hello", "hi"], ["again", "[error] timed out"], ["", "opening question"]])],
            [submission(utc(8, 2))],
        )

        result = check_totals([student], metrics_for([student]), {"s1": 2}, {"s1": 1})

        self.assertTrue(result.passed, result.details)

    def test_a_difference_is_listed(self):
        student = StudentRecords("s1", [conversation([["hello", "hi"]])], [submission(utc(8, 2))])

        result = check_totals([student], metrics_for([student]), {"s1": 5}, {"s1": 1})

        self.assertFalse(result.passed)
        self.assertEqual(len(result.details), 1)
        self.assertIn("s1: tutor messages, report 1, admin tab 5", result.details[0])

    def test_unusable_submissions_are_added_back(self):
        broken = {"module": "1", "question": "Question one", "grade": "n/a", "timestamp": utc(8, 3)}
        student = StudentRecords("s1", [], [submission(utc(8, 2)), broken])

        result = check_totals([student], metrics_for([student]), {}, {"s1": 2})

        self.assertTrue(result.passed, result.details)

    def test_a_student_the_report_leaves_out_is_still_compared(self):
        errors_only = StudentRecords("s1", [conversation([["hello", "[error] timed out"]])], [])

        result = check_totals([errors_only], metrics_for([errors_only]), {"s1": 1}, {})

        self.assertTrue(result.passed, result.details)

    def test_details_are_capped(self):
        students = [StudentRecords(f"s{i:03d}", [conversation([["hello", "hi"]])], []) for i in range(MAX_DETAIL_LINES + 20)]

        result = check_totals(students, metrics_for(students), {}, {})

        self.assertFalse(result.passed)
        self.assertEqual(len(result.details), MAX_DETAIL_LINES + 1)
        self.assertEqual(result.details[-1], "... and 20 more")


class AttemptsTests(unittest.TestCase):
    def test_matching_attempts_pass(self):
        student = StudentRecords(
            "s1", [], [submission(utc(8, 2)), submission(utc(8, 3)), submission(utc(8, 4), "Question two")],
            progress({"1": 2, "2": 1}),
        )

        result = check_attempts([student], QUESTIONS)

        self.assertTrue(result.passed, result.details)
        self.assertIn("2", result.summary)

    def test_fewer_attempts_in_progress_than_in_the_log_is_a_mismatch(self):
        student = StudentRecords("s1", [], [submission(utc(8, 2)), submission(utc(8, 3))], progress({"1": 1}))

        result = check_attempts([student], QUESTIONS)

        self.assertFalse(result.passed)
        self.assertEqual(result.details, ("s1: module 1 question 1, log 2, progress 1",))

    def test_unattempted_questions_are_not_compared(self):
        student = StudentRecords("s1", [], [], progress({"1": 0, "2": 0}))

        result = check_attempts([student], QUESTIONS)

        self.assertTrue(result.passed)
        self.assertIn("All 0 student-question pairs match", result.summary)

    def test_submissions_for_changed_question_text_are_listed(self):
        student = StudentRecords("s1", [], [submission(utc(8, 2), "An old wording")], progress({"1": 1}))

        result = check_attempts([student], QUESTIONS)

        self.assertFalse(result.passed)
        self.assertIn("s1: 1 logged submission matching no current question text", result.details)

    def test_a_student_without_a_progress_record_is_noted_but_does_not_fail_the_check(self):
        student = StudentRecords("s1", [], [submission(utc(8, 2)), submission(utc(8, 3))], None)

        result = check_attempts([student], QUESTIONS)

        self.assertTrue(result.passed)
        self.assertIn("1 student with no progress record not compared", result.summary)
        self.assertEqual(result.details, ("s1: no progress record, so 2 logged submissions not compared",))

    def test_the_check_cannot_run_without_question_text(self):
        result = check_attempts([StudentRecords("s1", [], [submission(utc(8, 2))], progress({"1": 1}))], {})

        self.assertIsNone(result.passed)
        self.assertEqual(result.status, "Not run")


class ClockTests(unittest.TestCase):
    def student(self, offset):
        logged = utc(8, 2, 3, 0)
        return StudentRecords("s1", [], [submission(logged)], progress({"1": 1}, logged + offset))

    def test_progress_times_within_seconds_of_the_log_pass(self):
        result = check_progress_clock([self.student(timedelta(seconds=4))], QUESTIONS)

        self.assertTrue(result.passed, result.summary)

    def test_a_constant_offset_of_hours_fails_and_names_the_setting(self):
        result = check_progress_clock([self.student(timedelta(hours=10))], QUESTIONS)

        self.assertFalse(result.passed)
        self.assertIn("10.00 hours", result.summary)
        self.assertIn("--progress-timezone", result.summary)

    def test_questions_with_different_attempt_counts_are_not_compared(self):
        logged = utc(8, 2)
        student = StudentRecords("s1", [], [submission(logged), submission(logged)], progress({"1": 1}, logged))

        result = check_progress_clock([student], QUESTIONS)

        self.assertIsNone(result.passed)


if __name__ == "__main__":
    unittest.main()
