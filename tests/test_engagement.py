"""Tests for utils.engagement, using synthetic records and no database.

Timestamps are naive UTC, which is how MongoDB returns them. The cases come from the build
order in docs/engagement-report-plan.md. Run them from the repository root with

    .venv/Scripts/python.exe -m unittest discover -s tests -t .
"""
import unittest
from datetime import date, datetime, timedelta, timezone

from utils.engagement import (
    PRIZE_2_MEASURES,
    Settings,
    StudentRecords,
    adjusted_rate,
    build_report,
    is_follow_up,
    percentiles,
    read_tutor_log,
    score_prize,
    summarise_student,
    weighted_score,
)

REPORT_DATE = date(2026, 10, 17)


def utc(year, month, day, hour=0, minute=0):
    return datetime(year, month, day, hour, minute)


def conversation(pairs, module="1", topic="Topic A", started=utc(2026, 6, 1)):
    return {"module": module, "topic": topic, "conversation": pairs, "timestamp": started}


def submission(when, level=2, module="1", question="Q1"):
    return {"module": module, "question": question, "submission": "an answer", "grade": level / 2, "timestamp": when}


def records(user_id="s1", conversations=(), submissions=(), progress=None):
    return StudentRecords(user_id, list(conversations), list(submissions), progress)


def summarise(student, settings=None):
    summary = summarise_student(student, settings or Settings(), REPORT_DATE, [])
    assert summary is not None
    return summary[0]


class SessionAndDayTests(unittest.TestCase):
    def test_a_sitting_across_melbourne_midnight_is_one_session_and_two_days(self):
        # 13:50 and 14:10 UTC in June are 23:50 and 00:10 in Melbourne (UTC+10).
        student = records(submissions=[submission(utc(2026, 6, 10, 13, 50)), submission(utc(2026, 6, 10, 14, 10))])

        metrics = summarise(student)

        self.assertEqual(metrics.sessions, 1)
        self.assertEqual(metrics.active_days, 2)
        self.assertEqual((metrics.first_active, metrics.last_active), (date(2026, 6, 10), date(2026, 6, 11)))

    def test_melbourne_midnight_moves_with_daylight_saving(self):
        # In December Melbourne is UTC+11, so midnight is 13:00 UTC. At a fixed UTC+10 these
        # two times would fall on the same day.
        student = records(submissions=[submission(utc(2026, 12, 10, 12, 50)), submission(utc(2026, 12, 10, 13, 10))])

        metrics = summarise(student)

        self.assertEqual(metrics.sessions, 1)
        self.assertEqual(metrics.active_days, 2)

    def test_a_morning_in_melbourne_is_not_counted_on_the_utc_day_before(self):
        # Sunday 23:00 UTC is Monday 09:00 in Melbourne, so it belongs to the week of Monday 15 June.
        student = records(submissions=[submission(utc(2026, 6, 14, 23, 0))])

        metrics = summarise(student)

        self.assertEqual(metrics.first_active, date(2026, 6, 15))
        self.assertEqual(metrics.assessor_by_week, {date(2026, 6, 15): 1})

    def test_a_gap_longer_than_30_minutes_starts_a_new_session(self):
        for gap, expected_sessions in [(29, 1), (30, 1), (31, 2)]:
            with self.subTest(gap=gap):
                start = utc(2026, 6, 10, 1, 0)
                student = records(submissions=[submission(start), submission(start + timedelta(minutes=gap))])

                self.assertEqual(summarise(student).sessions, expected_sessions)

    def test_the_session_gap_is_a_setting(self):
        start = utc(2026, 6, 10, 1, 0)
        student = records(submissions=[submission(start), submission(start + timedelta(minutes=45))])

        self.assertEqual(summarise(student, Settings(session_gap=timedelta(minutes=60))).sessions, 1)

    def test_sessions_are_counted_for_each_mode_and_for_both_together(self):
        pairs = [
            ["first", "reply", utc(2026, 6, 10, 1, 0)],
            ["second", "reply", utc(2026, 6, 10, 1, 10)],
            ["next day", "reply", utc(2026, 6, 11, 1, 0)],
        ]
        student = records(
            conversations=[conversation(pairs)],
            submissions=[submission(utc(2026, 6, 10, 1, 20))],
        )

        metrics = summarise(student)

        self.assertEqual(metrics.tutor_sessions, 2)
        self.assertEqual(metrics.assessor_sessions, 1)
        # The tutor messages and the submission on the 10th run together into one sitting.
        self.assertEqual(metrics.sessions, 2)
        self.assertAlmostEqual(metrics.interactions_per_session, 2.0)
        self.assertAlmostEqual(metrics.tutor_interactions_per_session, 1.5)

    def test_active_days_per_week_counts_weeks_from_the_first_activity(self):
        # Wednesday 7 October to the report date, Saturday 17 October, spans two weeks.
        student = records(
            submissions=[submission(utc(2026, 10, 7, 1)), submission(utc(2026, 10, 8, 1)), submission(utc(2026, 10, 15, 1))]
        )

        self.assertAlmostEqual(summarise(student).active_days_per_week, 1.5)

    def test_a_student_who_starts_in_the_report_week_has_one_week(self):
        student = records(submissions=[submission(utc(2026, 10, 14, 1)), submission(utc(2026, 10, 15, 1))])

        self.assertAlmostEqual(summarise(student).active_days_per_week, 2.0)


class TutorLogTests(unittest.TestCase):
    def test_opening_questions_and_error_turns_are_not_counted(self):
        pairs = [
            ["", "An opening question from the tutor"],
            ["what is MTBF", "[error] the model call failed"],
            ["what is MTBF", "It is the mean time between failures"],
        ]

        log = read_tutor_log([conversation(pairs)])

        self.assertEqual([m.text for m in log.messages], ["what is MTBF"])
        self.assertEqual(log.error_turns, 1)

    def test_counted_messages_and_error_turns_add_up_to_the_admin_count(self):
        pairs = [["", "opening"], ["a", "[error] x"], ["b", "reply"], ["c", "reply"], ["d", "[error] y"]]
        admin_count = sum(1 for pair in pairs if pair[0] != "")

        log = read_tutor_log([conversation(pairs)])

        self.assertEqual(len(log.messages) + log.error_turns, admin_count)

    def test_two_element_pairs_are_undated_and_three_element_pairs_are_dated(self):
        pairs = [["old", "reply"], ["new", "reply", utc(2026, 6, 10, 1, 0)]]

        log = read_tutor_log([conversation(pairs)])

        self.assertIsNone(log.messages[0].at)
        self.assertEqual(log.messages[1].at, datetime(2026, 6, 10, 1, 0, tzinfo=timezone.utc))

    def test_undated_messages_count_as_interactions_but_not_as_sessions(self):
        pairs = [["old", "reply"], ["new", "reply", utc(2026, 6, 10, 1, 0)]]

        metrics = summarise(records(conversations=[conversation(pairs)]))

        self.assertEqual(metrics.tutor_messages, 2)
        self.assertEqual(metrics.tutor_undated_messages, 1)
        self.assertEqual(metrics.tutor_sessions, 1)
        self.assertEqual(metrics.tutor_by_week, {date(2026, 6, 8): 1})

    def test_a_student_with_only_opening_questions_has_no_interactions(self):
        student = records(conversations=[conversation([["", "opening"]])])

        self.assertIsNone(summarise_student(student, Settings(), REPORT_DATE, []))

    def test_undated_messages_give_the_conversation_start_and_the_last_competency_change_as_days(self):
        pairs = [["old", "reply"]]
        progress = {"1": {"topics": {"Topic A": {"progress": 2, "last_updated": utc(2026, 5, 6, 5)}}}}
        student = records(conversations=[conversation(pairs, started=utc(2026, 5, 4, 3))], progress=progress)

        metrics = summarise(student)

        self.assertEqual(metrics.tutor_active_days, 2)
        self.assertEqual(metrics.active_weeks, 1)
        self.assertEqual(metrics.topics_revisited, 1)

    def test_dated_messages_do_not_use_the_lower_bound_days(self):
        pairs = [["new", "reply", utc(2026, 5, 10, 1)]]
        progress = {"1": {"topics": {"Topic A": {"progress": 2, "last_updated": utc(2026, 5, 12, 5)}}}}
        student = records(conversations=[conversation(pairs, started=utc(2026, 5, 1))], progress=progress)

        metrics = summarise(student)

        self.assertEqual(metrics.tutor_active_days, 1)
        self.assertEqual(metrics.topics_revisited, 0)

    def test_progress_times_are_read_in_the_progress_timezone(self):
        pairs = [["old", "reply"]]
        progress = {"1": {"topics": {"Topic A": {"progress": 1, "last_updated": utc(2026, 5, 6, 15)}}}}
        student = records(conversations=[conversation(pairs, started=utc(2026, 5, 6, 3))], progress=progress)

        # 15:00 on the 6th is the 6th in Melbourne, or 01:00 on the 7th when it is read as UTC.
        in_melbourne = summarise(student, Settings(progress_timezone="Australia/Melbourne"))
        in_utc = summarise(student, Settings(progress_timezone="UTC"))

        self.assertEqual(in_melbourne.tutor_active_days, 1)
        self.assertEqual(in_utc.tutor_active_days, 2)

    def test_ten_undated_messages_flag_incomplete_tutor_timing(self):
        for count, flagged in [(9, False), (10, True)]:
            with self.subTest(count=count):
                pairs = [[f"message {n}", "reply"] for n in range(count)]

                self.assertEqual(summarise(records(conversations=[conversation(pairs)])).tutor_timing_incomplete, flagged)

    def test_messages_per_topic_conversation(self):
        conversations = [
            conversation([["a", "r"], ["b", "r"], ["c", "r"]], topic="One"),
            conversation([["d", "r"]], topic="Two"),
            conversation([["", "opening only"]], topic="Three"),
        ]

        metrics = summarise(records(conversations=conversations))

        self.assertEqual(metrics.topics_worked, 2)
        self.assertAlmostEqual(metrics.messages_per_topic, 2.0)


class FollowUpTests(unittest.TestCase):
    def test_follow_up_detection(self):
        cases = [
            ("How does this work", True),
            ("what's the difference", True),
            ("  Why not", True),
            ("Could you show me", True),
            ("do you mean the mean", True),
            ("I think it is 5?", True),
            ("yes", False),
            ("ok thanks", False),
            ("Dominic is here", False),
            ("don't know", False),
            ("island", False),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(is_follow_up(text), expected)

    def test_follow_up_share_is_over_all_tutor_messages(self):
        pairs = [["why is that", "r"], ["ok", "r"], ["got it?", "r"], ["next", "r"]]

        metrics = summarise(records(conversations=[conversation(pairs)]))

        self.assertEqual(metrics.follow_ups, 2)
        self.assertAlmostEqual(metrics.follow_up_share, 0.5)


class QuestionTests(unittest.TestCase):
    def attempts(self, question, levels, first_day, module="1", same_day=False):
        """Submissions for one question, one a day unless same_day is set."""
        step = timedelta(minutes=10) if same_day else timedelta(days=1)
        return [submission(first_day + step * n, level, module, question) for n, level in enumerate(levels)]

    def test_improving_retrying_after_full_marks_and_attempting_once(self):
        day = utc(2026, 6, 1, 1)
        submissions = (
            self.attempts("A", [0, 1, 2], day)
            + self.attempts("B", [2, 2], day)
            + self.attempts("C", [1], day)
        )

        summary = summarise_student(records(submissions=submissions), Settings(), REPORT_DATE, [])
        metrics, rows = summary
        by_question = {row.question: row for row in rows}

        a = by_question["A"]
        self.assertEqual((a.attempts, a.first_level, a.best_level), (3, 0, 2))
        self.assertEqual(a.level_sequence, "0 → 1 → 2")
        self.assertEqual(a.days, (date(2026, 6, 1), date(2026, 6, 2), date(2026, 6, 3)))
        self.assertEqual((by_question["B"].attempts, by_question["B"].best_level), (2, 2))
        self.assertEqual((by_question["C"].attempts, by_question["C"].best_level), (1, 1))

        self.assertEqual(metrics.questions_attempted, 3)
        self.assertEqual(metrics.questions_retried, 2)
        self.assertAlmostEqual(metrics.attempts_per_question, 2.0)
        # A and C first scored below 2. Only A was tried again, and it improved.
        self.assertEqual(metrics.questions_first_below_2, 2)
        self.assertEqual(metrics.questions_responded, 1)
        self.assertEqual(metrics.questions_improved, 1)
        self.assertAlmostEqual(metrics.responded_share, 0.5)
        self.assertAlmostEqual(metrics.improved_share, 0.5)
        # A and B were worked on across several days. Going back to B at level 2 still counts.
        self.assertEqual(metrics.questions_revisited, 2)

    def test_a_retry_that_scores_no_higher_has_not_improved(self):
        day = utc(2026, 6, 1, 1)
        submissions = self.attempts("flat", [0, 0], day) + self.attempts("down", [1, 0], day)

        metrics = summarise(records(submissions=submissions))

        self.assertEqual(metrics.questions_responded, 2)
        self.assertEqual(metrics.questions_improved, 0)

    def test_retrying_on_the_same_day_is_not_a_revisit(self):
        submissions = self.attempts("A", [0, 2], utc(2026, 6, 1, 1), same_day=True)

        metrics = summarise(records(submissions=submissions))

        self.assertEqual(metrics.questions_revisited, 0)

    def test_grades_convert_back_to_levels(self):
        entries = [
            {**submission(utc(2026, 6, 1, 1, n)), "grade": grade} for n, grade in enumerate([0, 0.5, 1])
        ]

        _, rows = summarise_student(records(submissions=entries), Settings(), REPORT_DATE, [])

        self.assertEqual(rows[0].levels, (0, 1, 2))

    def test_a_question_is_identified_by_module_and_text(self):
        day = utc(2026, 6, 1, 1)
        submissions = (
            self.attempts("Same text", [1], day, module="10")
            + self.attempts("Same text", [1], day, module="2")
            + self.attempts("Other text", [1], day, module="2")
        )

        _, rows = summarise_student(records(submissions=submissions), Settings(), REPORT_DATE, [])

        self.assertEqual([(row.module, row.question) for row in rows], [("2", "Same text"), ("2", "Other text"), ("10", "Same text")])

    def test_the_attempts_sheet_shows_the_first_80_characters(self):
        _, rows = summarise_student(
            records(submissions=[submission(utc(2026, 6, 1, 1), question="x" * 200)]), Settings(), REPORT_DATE, []
        )

        self.assertEqual(rows[0].question_start, "x" * 80)

    def test_unreadable_submissions_are_skipped_with_a_warning(self):
        good = submission(utc(2026, 6, 1, 1))
        bad = [
            {**good, "grade": None},
            {**good, "grade": 3},
            {**good, "timestamp": None},
        ]
        warnings = []

        metrics, _ = summarise_student(records(submissions=[good, *bad]), Settings(), REPORT_DATE, warnings)

        self.assertEqual(metrics.assessor_submissions, 1)
        self.assertEqual(len(warnings), 3)

    def test_levels_at_two_come_from_the_progress_record(self):
        progress = {
            "1": {
                "topics": {"A": {"progress": 2}, "B": {"progress": 1}, "C": {"progress": 2}},
                "questions": {"1": {"competency_level": 2}, "2": {"competency_level": 1}},
            },
            "2": {"topics": {"D": {"progress": 2}}, "questions": {}},
        }
        student = records(submissions=[submission(utc(2026, 6, 1, 1))], progress=progress)

        metrics = summarise(student)

        self.assertEqual((metrics.topics_at_level_2, metrics.questions_at_level_2), (3, 1))
        self.assertEqual(metrics.items_at_level_2, 4)

    def test_levels_at_two_are_unknown_without_a_progress_record(self):
        metrics = summarise(records(submissions=[submission(utc(2026, 6, 1, 1))]))

        self.assertIsNone(metrics.items_at_level_2)


class PercentileTests(unittest.TestCase):
    def test_tied_values_share_the_average_percentile(self):
        result = percentiles({"a": 1, "b": 2, "c": 2, "d": 3})

        self.assertEqual(result, {"a": 0.0, "b": 50.0, "c": 50.0, "d": 100.0})

    def test_a_missing_value_is_blank_and_is_not_counted_in_the_cohort(self):
        result = percentiles({"a": 1, "b": None, "c": 3})

        self.assertEqual(result, {"a": 0.0, "b": None, "c": 100.0})

    def test_one_value_or_all_tied_sit_in_the_middle(self):
        self.assertEqual(percentiles({"a": 7}), {"a": 50.0})
        self.assertEqual(percentiles({"a": 4, "b": 4, "c": 4}), {"a": 50.0, "b": 50.0, "c": 50.0})

    def test_nobody_has_data(self):
        self.assertEqual(percentiles({"a": None}), {"a": None})


class ScoreTests(unittest.TestCase):
    def test_the_score_is_a_weighted_mean_that_leaves_out_blank_percentiles(self):
        cells = {"x": 100.0, "y": None, "z": 0.0}

        self.assertAlmostEqual(weighted_score(cells, {"x": 1, "y": 1, "z": 1}), 50.0)
        self.assertAlmostEqual(weighted_score(cells, {"x": 3, "y": 1, "z": 1}), 75.0)

    def test_a_weight_of_zero_leaves_the_measure_out(self):
        self.assertAlmostEqual(weighted_score({"x": 100.0, "z": 0.0}, {"x": 1, "z": 0}), 100.0)

    def test_the_score_is_blank_when_no_weighted_measure_has_data(self):
        self.assertIsNone(weighted_score({"x": None, "z": 40.0}, {"x": 1, "z": 0}))


class ShrinkageTests(unittest.TestCase):
    def test_a_rate_is_pulled_toward_the_cohort_rate(self):
        self.assertAlmostEqual(adjusted_rate(1, 1, 0.4, 5), 0.5)
        self.assertAlmostEqual(adjusted_rate(9, 10, 0.4, 5), 11 / 15)

    def test_one_of_one_ranks_below_nine_of_ten(self):
        # The cohort improved 12 of 30 questions, a rate of 0.4.
        def first_scored_zero(question, later_level, user_id):
            levels = [0] if later_level is None else [0, later_level]
            return [
                submission(utc(2026, 6, 1, 1) + timedelta(days=n), level, "1", f"{user_id} {question}")
                for n, level in enumerate(levels)
            ]

        def student(user_id, improved, not_improved):
            submissions = []
            for question in range(improved):
                submissions += first_scored_zero(question, 1, user_id)
            for question in range(improved, improved + not_improved):
                submissions += first_scored_zero(question, None, user_id)
            return records(user_id, submissions=submissions)

        report = build_report(
            [student("one_of_one", 1, 0), student("nine_of_ten", 9, 1), student("two_of_nineteen", 2, 17)],
            REPORT_DATE,
        )
        cells = {row.user_id: row.cells["improvement"] for row in report.prize_2.rows}

        self.assertAlmostEqual(report.prize_2.cohort_rates["improvement"], 0.4)
        self.assertAlmostEqual(cells["one_of_one"].raw, 1.0)
        self.assertAlmostEqual(cells["nine_of_ten"].raw, 0.9)
        self.assertAlmostEqual(cells["one_of_one"].adjusted, 0.5)
        self.assertAlmostEqual(cells["nine_of_ten"].adjusted, 11 / 15)
        self.assertLess(cells["one_of_one"].percentile, cells["nine_of_ten"].percentile)
        self.assertEqual((cells["one_of_one"].successes, cells["one_of_one"].opportunities), (1, 1))


class ReportTests(unittest.TestCase):
    def three_weeks(self, user_id, revisit, attempts_each=1, same_day=False, questions=12):
        """A student with one question a day over three weeks.

        The first `revisit` questions are attempted again on the next day, or on the same day if
        same_day is set. Every attempt scores level 2.
        """
        submissions = []
        for index in range(questions):
            first = utc(2026, 6, 1, 1) + timedelta(days=7 * (index % 3) + index // 3)
            submissions.append(submission(first, 2, "1", f"Q{index}"))
            if index < revisit:
                again = first + (timedelta(minutes=20) if same_day else timedelta(days=1))
                submissions.append(submission(again, 2, "1", f"Q{index}"))
        return records(user_id, submissions=submissions)

    def test_the_starting_weights(self):
        report = build_report([self.three_weeks("a", 0)], REPORT_DATE)

        self.assertEqual(
            {key: weight for key, weight in report.prize_1.weights.items() if weight},
            {"active_days": 1, "active_weeks": 1},
        )
        self.assertEqual(
            {key: weight for key, weight in report.prize_2.weights.items() if weight},
            {"improvement": 1, "revisiting": 1, "follow_ups": 1},
        )

    def test_students_are_ranked_on_the_weighted_percentiles(self):
        students = [
            self.three_weeks("revisits_all", 12),
            self.three_weeks("revisits_half", 6),
            self.three_weeks("revisits_none", 0),
            self.three_weeks("retries_same_day", 12, same_day=True),
        ]
        report = build_report(students, REPORT_DATE)

        ranks = {row.user_id: row.rank for row in report.prize_2.rows}

        # Revisiting is the only starting-weight measure with data. Two students tie for last.
        self.assertEqual(ranks, {"revisits_all": 1, "revisits_half": 2, "revisits_none": 3, "retries_same_day": 3})

    def test_students_with_the_same_score_share_the_higher_rank(self):
        students = [
            self.three_weeks("twin_a", 12),
            self.three_weeks("twin_b", 12),
            self.three_weeks("below", 0),
        ]

        ranks = {row.user_id: row.rank for row in build_report(students, REPORT_DATE).prize_2.rows}

        # The twins tie for first, so both rank 1 and the next student is third.
        self.assertEqual(ranks, {"twin_a": 1, "twin_b": 1, "below": 3})

    def test_changing_a_weight_changes_the_ranks(self):
        students = [
            self.three_weeks("revisits_all", 12),
            self.three_weeks("revisits_half", 6),
            self.three_weeks("revisits_none", 0),
            self.three_weeks("retries_same_day", 12, same_day=True),
        ]
        metrics = build_report(students, REPORT_DATE).students

        table = score_prize(metrics, PRIZE_2_MEASURES, 5, weights={"revisiting": 0, "attempts_per_question": 1})

        ranks = {row.user_id: row.rank for row in table.rows}
        # Both retried every question, so they tie for first on attempts per question.
        self.assertEqual(ranks, {"revisits_all": 1, "retries_same_day": 1, "revisits_half": 3, "revisits_none": 4})

    def test_all_weights_at_zero_leave_every_score_blank(self):
        metrics = build_report([self.three_weeks("a", 3), self.three_weeks("b", 0)], REPORT_DATE).students

        table = score_prize(metrics, PRIZE_2_MEASURES, 5, weights={"improvement": 0, "revisiting": 0, "follow_ups": 0})

        self.assertEqual([row.score for row in table.rows], [None, None])
        self.assertEqual([row.rank for row in table.rows], [None, None])

    def test_students_below_the_prize_2_thresholds_are_scored_but_not_ranked(self):
        two_weeks = records("two_weeks", submissions=[
            submission(utc(2026, 6, 1, 1) + timedelta(days=7 * (n % 2) + n // 2), 2, "1", f"Q{n}") for n in range(12)
        ])
        nine = records("nine", submissions=[
            submission(utc(2026, 6, 1, 1) + timedelta(days=7 * (n % 3) + n // 3), 2, "1", f"Q{n}") for n in range(9)
        ])
        students = [self.three_weeks("enough", 0), two_weeks, nine]

        default = build_report(students, REPORT_DATE)
        relaxed = build_report(students, REPORT_DATE, Settings(min_weeks=2, min_interactions=9))

        by_user = {row.user_id: row for row in default.prize_2.rows}
        self.assertEqual([by_user[u].eligible for u in ("enough", "two_weeks", "nine")], [True, False, False])
        self.assertEqual(by_user["enough"].rank, 1)
        for user_id in ("two_weeks", "nine"):
            self.assertIsNotNone(by_user[user_id].score)
            self.assertIsNone(by_user[user_id].rank)
        self.assertTrue(all(row.eligible and row.rank is not None for row in relaxed.prize_2.rows))

    def test_every_student_with_an_interaction_is_on_prize_1(self):
        report = build_report([self.three_weeks("a", 0), self.three_weeks("b", 0)], REPORT_DATE)

        self.assertEqual([row.user_id for row in report.prize_1.rows], ["a", "b"])
        self.assertTrue(all(row.eligible for row in report.prize_1.rows))

    def test_a_student_who_only_used_the_tutor_is_blank_on_assessor_measures_not_zero(self):
        tutor_only = records("tutor_only", conversations=[conversation([["why", "r", utc(2026, 6, 1, 1)]])])
        assessor_only = records("assessor_only", submissions=[submission(utc(2026, 6, 1, 1))])
        mixed = records(
            "mixed",
            conversations=[conversation([["why", "r", utc(2026, 6, 2, 1)]])],
            submissions=[submission(utc(2026, 6, 2, 1, 5), 0)],
        )

        report = build_report([tutor_only, assessor_only, mixed], REPORT_DATE)
        prize_1 = {row.user_id: row.cells for row in report.prize_1.rows}
        prize_2 = {row.user_id: row.cells for row in report.prize_2.rows}

        self.assertIsNone(prize_1["tutor_only"]["assessor_submissions"].raw)
        self.assertIsNone(prize_1["tutor_only"]["assessor_submissions"].percentile)
        self.assertIsNone(prize_1["assessor_only"]["tutor_messages"].percentile)
        self.assertIsNone(prize_2["assessor_only"]["follow_ups"].percentile)
        # Only two students have follow-up data, so the cohort for that measure is two. Both
        # asked a question in their only message, so they tie.
        follow_up_percentiles = sorted(
            cells["follow_ups"].percentile for cells in prize_2.values() if cells["follow_ups"].percentile is not None
        )
        self.assertEqual(follow_up_percentiles, [50.0, 50.0])

    def test_the_weekly_axis_runs_from_the_first_week_to_the_report_week(self):
        report = build_report([records(submissions=[submission(utc(2026, 9, 30, 1))])], REPORT_DATE)

        self.assertEqual(report.weeks, [date(2026, 9, 28), date(2026, 10, 5), date(2026, 10, 12)])
        self.assertEqual(report.data_range, (date(2026, 9, 30), date(2026, 9, 30)))

    def test_an_empty_cohort_gives_an_empty_report(self):
        report = build_report([], REPORT_DATE)

        self.assertEqual((report.students, report.weeks, report.data_range), ([], [], None))

    def test_the_report_is_the_same_each_time(self):
        students = [self.three_weeks("a", 6), self.three_weeks("b", 0)]

        self.assertEqual(build_report(students, REPORT_DATE), build_report(students, REPORT_DATE))


if __name__ == "__main__":
    unittest.main()
