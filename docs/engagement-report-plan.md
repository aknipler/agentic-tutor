# Student engagement report plan

The PRQ lecturers are awarding two prizes. One is for the students who used the AI tutor most
often. The other is for the students who used it most effectively to support their learning.
This plan describes a repeatable report that gives the lecturers student-level data to choose
recipients fairly. "AI tutor" here means the whole app, so both the Tutor and the Assessor
count.

The report sets out the data for each prize. The lecturers decide how to weight it and who wins.

## What the lecturers asked for

| Ask | Where the report answers it |
|---|---|
| Overall usage. Total interactions, sessions and usage frequency, split by Tutor and Assessor | Students sheet, usage columns |
| Consistency. Active days and weeks, and weekly patterns across the semester | Students sheet and Weekly sheet |
| Depth. Interactions per session, follow-up questions, repeated attempts | Students sheet and Attempts sheet |
| Meaningful engagement. Responding to feedback, revisiting concepts, improving through attempts | Students sheet and Attempts sheet |

## What the data supports

A read-only count of the live logs on 17 October 2026 found:

- 39 students had made 1,896 assessor submissions. Every submission records its time, grade,
  module and question.
- 36 students had written 624 messages to the tutor. Tutor messages have no timestamps. A topic
  conversation records only the time it started.

All Assessor data can be measured exactly. For the Tutor, message counts and content are
exact but timing is not. This semester's tutor sessions, active days and weekly patterns can
only be partly rebuilt. The logging change below fixes this for all activity after it ships.

## Timestamp tutor messages

Change `log_conversation` in `mongodb/logger.py` to store each pair as
`[student_message, tutor_message, logged_at]`, with `logged_at` in UTC. Every existing reader
of these pairs already ignores a third element:

- the tutor's history replay takes `(list(pair) + ["", ""])[:2]` in `utils/tutor/interface.py`
- the admin message count reads element 0 in `mongodb/connectors/analytics.py`

Pairs written before the change keep two elements and are treated as undated. This needs no
migration and no new collection.

Ship this first, and soon. Tutor timing lost before the change can't be recovered, and the exam
revision period is close. Test it locally with the test login, then confirm new pairs in the
live log have three elements.

## Definitions

These are the rules the code implements. The report's About sheet repeats them for the
lecturers.

**Time.** Convert every timestamp to Melbourne time before working out days and weeks. The logs
store UTC, so without this a 9 am Tuesday session would count as Monday. Weeks start on Monday
and are labelled by that date. Progress records use `datetime.now()` on the server. Before
relying on them, confirm the server runs on UTC. To check, compare a submission's log timestamp
with the `last_attempt` on the same question. They should match to within a few seconds. The
code reads progress times as UTC by default. If the check fails, run the script with
`--progress-timezone` set to the server's zone. The script runs this check itself and also
warns about any activity dated after the report date. A progress record written by a developer's
machine in another zone does this.

**Interaction.**

- Tutor. A message the student wrote. Opening questions from the tutor don't count, because
  they are logged with an empty student message. A turn whose reply is an `[error]` entry
  doesn't count either, because the student's retry is counted instead.
- Assessor. One graded submission.

A tutor message can be a single word, while a submission is a worked answer, so the two units
aren't comparable. Report them side by side and never rank on their sum.

**Session.** A run of dated interactions with no gap longer than 30 minutes. Count sessions for
each mode and for the combined timeline. A student who moves from the Tutor to the Assessor in
one sitting has one combined session.

**Active day and active week.** A Melbourne date or week with at least one interaction. Tutor
activity from before the logging change gives lower-bound dates for each topic the student wrote
in. These are the date the conversation started and the date of the topic's latest competency
change. Flag any student with 10 or more undated tutor messages as "tutor timing incomplete",
since their tutor days are undercounted.

**Question.** The submission log stores question text, so identify an assessor question by its
module and text. Convert each grade back to the 0/1/2 competency scale (level = grade × 2).

**Follow-up question.** A tutor message that contains "?" or starts with a question word (why,
how, what, when, where, which, who, can, could, would, should, is, are, does, do). This is a
heuristic. Measure its accuracy before relying on it (see Validation).

## Metrics

The report has one row for each student with at least one interaction.

### Overall usage

| Measure | Tutor | Assessor | Combined |
|---|---|---|---|
| Interactions | yes | yes | no |
| Sessions | after the logging change | yes | yes |
| Active days | lower bound before the logging change | yes | yes |
| Active days per week | no | no | yes |

Active days per week is combined active days divided by the number of weeks from the student's
first activity to the report date. Students who started late aren't penalised for the weeks
before they began. Weeks are whole Monday-to-Sunday weeks, counted from the week of the first
activity to the week of the report date, with both included. A student who first appears in the
report week has one week.

### Consistency

- Active weeks, combined.
- The Weekly sheet has one row per student and one column per week. Each cell holds that week's
  interactions, in separate Tutor and Assessor blocks shaded as a heat map. Undated tutor
  messages go in an Undated column rather than being spread across weeks.

### Depth

- Mean interactions per session, for each mode and combined. Tutor figures start after the
  logging change.
- Mean student messages per topic conversation. Timestamps aren't needed, so this is exact for
  the whole semester.
- Follow-up questions asked.
- Assessor questions attempted more than once, and mean attempts per question.

### Meaningful learning engagement

- **Responded to feedback.** Questions where the first attempt scored below 2 and the student
  tried again. Report the count, and the share of all questions first scored below 2.
- **Improved through attempts.** Questions from the previous measure where a later attempt
  scored higher than the first. Report the count and the share.
- **Revisited.** Questions and tutor topics the student worked on across two or more days.
  Report the count and the share. A return to a question already at level 2 counts, because
  that is spaced practice. Tutor topics use the lower-bound dates before the logging change.
- **Follow-up question share.** Follow-up questions divided by tutor messages.

The report also counts topics and questions at level 2. They start with a weight of 0 on the
Prize 2 sheet, because a high level can reflect what a student knew before using the app.

### Attempts sheet

The Attempts sheet has one row for each student and question. Its columns are:

- module
- the first 80 characters of the question
- number of attempts
- the level sequence (for example 0 → 1 → 2)
- first and best level
- the days it was attempted on

Every meaningful-engagement figure can be traced to these rows, so lecturers can check any
student near the top of a prize sheet directly.

## Prize sheets

Each prize has its own sheet listing every measure that bears on it. The lecturers decide how
much each measure counts. The workbook comes with starting weights so it ranks students as soon
as it opens, but those weights are a suggestion and the lecturers set the final ones.

### How a prize sheet works

- A weights row above the table has one cell per measure. Changing a weight updates every
  score and rank straight away, without rerunning the script. A weight of 0 leaves the measure
  out.
- Each measure has a raw value column and a percentile column. The percentile is the student's
  position in the cohort from 0 to 100, with tied students sharing the average rank. It is
  (average rank − 1) ÷ (students with data − 1) × 100, so the lowest value gets 0 and the
  highest gets 100. A student alone in the cohort, or a cohort where every value ties, gets 50.
  Scores use percentiles so that measures on different scales count equally and one extreme
  account can't distort everyone else's position.
- The score is the weighted mean of the student's percentiles. A blank percentile means the
  student has no data for that measure, and the mean leaves it out rather than counting it as
  zero. A student who never used the Tutor isn't penalised on tutor measures.
- The rank column orders students by score. Students with the same score share the higher
  rank, which is the better of the places they cover. Scores of 90, 80, 80 and 70 rank 1, 2, 2
  and 4, as the RANK function gives. The sheet is an Excel table with filters, so
  lecturers can sort by rank or by any single measure.
- A student who never used a mode has a blank value for its count measures, not a 0. This
  applies to Tutor messages, Assessor submissions and Sessions on the Prize 1 sheet. Their
  percentile is blank too, so the score leaves the measure out.
- A flag column marks students whose tutor timing is incomplete.

The script works out raw values and percentiles. Score and rank are spreadsheet formulas, so
they recalculate when a weight changes. The score formula is:

```
IFERROR(SUMPRODUCT(weights, percentiles) / SUMPRODUCT(weights, --ISNUMBER(percentiles)), "")
```

It works in Excel and LibreOffice. The file is written without calculated results, so scores
appear only once it is opened in a spreadsheet program.

### Prize 1. Most frequent engagement

Every student with an interaction appears on this sheet.

| Measure | Starting weight |
|---|---|
| Active days, combined | 1 |
| Active weeks, combined | 1 |
| Active days per week | 0 |
| Sessions, combined | 0 |
| Tutor messages | 0 |
| Assessor submissions | 0 |

The starting weights rank on time rather than counts, which matches "most frequently". Active
days measures how often a student came back. Active weeks measures how evenly that was spread
across the semester. Interaction counts reward one long sitting, and a tutor message isn't the
same amount of work as a submission. The count measures are there for lecturers who want to
give volume some weight anyway. Combined sessions undercount students whose tutor timing is
incomplete.

### Prize 2. Most effective use

Only eligible students get a rank. A student needs 3 or more active weeks and 10 or more
interactions (tutor messages plus assessor submissions) to be eligible. Both thresholds sit in
cells beside the weights and can be changed. Ineligible students stay on the sheet with a blank
rank.

| Measure | Calculation | Starting weight |
|---|---|---|
| Improvement after feedback | Questions improved ÷ questions first scored below 2 | 1 |
| Revisiting | Questions and topics revisited ÷ questions and topics worked on | 1 |
| Follow-up questions | Follow-up questions ÷ tutor messages | 1 |
| Responded to feedback | Questions retried ÷ questions first scored below 2 | 0 |
| Messages per topic conversation | Mean | 0 |
| Interactions per session | Mean, combined | 0 |
| Attempts per question | Mean | 0 |
| Topics and questions at level 2 | Count | 0 |

The first three best separate purposeful use from frequent use, so they start at 1. A question
can only improve if it was retried, which means improvement already covers most of what
"responded to feedback" measures. The depth measures rise with volume as much as with purpose.
Level 2 counts can reflect what a student knew before using the app, so weight them with care.

Percentiles for each measure are worked out across every student with data for it, not just
eligible students. Changing a threshold therefore never needs a rerun.

The first four measures are rates, so a single attempt could produce 100%. The script shrinks
each rate toward the cohort rate before working out percentiles. The cohort rate is total
successes divided by total opportunities across all students with data.

```
adjusted rate = (successes + k × cohort rate) / (opportunities + k)        k = 5
```

Take a cohort improvement rate of 40%. A student who improved 1 of 1 questions gets
(1 + 2) / 6 = 50%. A student who improved 9 of 10 gets (9 + 2) / 15 = 73%. A rate needs enough
attempts behind it before it stands out. The sheet shows the counts and raw rate next to the
adjusted rate.

### Choosing winners

Before deciding, read the Attempts rows and a sample of tutor conversations for the students at
the top of each sheet. Staff and test accounts appear in the output, and the lecturers will
recognise their own.

## Build order

All six steps are written and tested locally. The logger timestamps new tutor pairs,
`utils/engagement.py` and `utils/engagement_workbook.py` do the work, and
`scripts/engagement_report.py` runs it. The logging change still needs to ship to the live app,
and step 1's last check (new pairs in the live log have three elements) waits on that. Until it
ships, every tutor message is undated. Tutor sessions all read 0, tutor active days are lower
bounds, and most students carry the "tutor timing incomplete" flag. Run the report again once
the change has been live for a while.

1. Make the logging change.
2. Write `utils/engagement.py`. Use pure functions that take plain records (tutor pairs with or
   without a time, submissions, progress topics) and return per-student metrics and scores.
   Don't import Streamlit or pymongo, so it can be tested without a database.
3. Write `tests/test_engagement.py` with synthetic data covering these cases:
   - a sitting that crosses Melbourne midnight is one session but two active days
   - a 31-minute gap starts a new session
   - opening questions and error turns are left out of counts
   - two-element pairs are undated and three-element pairs are dated
   - a question that goes 0 → 1 → 2, one retried after reaching 2, and one attempted once
   - shrinkage ranks 1 of 1 below 9 of 10
   - a student with no data for a measure gets a blank percentile, not 0
   - tied values share the average percentile
4. Write `scripts/engagement_report.py`. Have it read both databases, call `utils/engagement.py`
   and write the workbook. It never writes to the database, so it needs no `--commit` flag.
   Give it these options:
   - `--out`, defaulting to `data/reports/engagement_<date>.xlsx`. `data/` is gitignored, which
     matters because the workbook lists login codes.
   - `--session-gap` and `--shrink-k`, with defaults of 30 minutes and 5.
   - `--min-weeks` and `--min-interactions`, which set the starting values of the Prize 2
     threshold cells, with defaults of 3 and 10.
   - `--progress-timezone`, for the clock check below, with a default of UTC.
   - `--report-date`, so a rerun can report as of an earlier Melbourne date.
   - `--validation-notes`, a text file of the hand-check results to copy to the About sheet.
5. Have the workbook include About, Students, Weekly, Attempts, Prize 1 and Prize 2 sheets.
   Write each prize sheet's score, rank and eligibility cells as formulas that read its weights
   row and threshold cells. On About, explain how to change weights and thresholds, and record
   the run time, data range, settings, git commit and validation results so two runs can be
   compared.
6. Run the validation checks below.

The report is deterministic. It makes no model calls and uses no sampling, so the same data and
settings always give the same output. Run the script again at any point in the semester, or in
a later semester, to get an updated report.

## Validation

Complete these checks before the first report goes out, and record the results on the About
sheet. The script runs the first two checks and the clock check itself and writes their results
to the About sheet. The others need a person. Put their results in a text file, one per line,
and pass it with `--validation-notes`.

- Per-student tutor message and assessor submission totals match the admin Data Analysis tab.
  The admin count includes error turns, so add those back before comparing.
- Attempts per question match the `attempts` field in the progress records. List any
  mismatches.
- Read 50 randomly chosen tutor messages, mark which ones ask a question and compare with the
  heuristic. If fewer than about 80% of the messages it flags are real questions, fix the word
  list or drop the component.
- Trace two students by hand from the raw records to their final row. Make one of them a
  student who only used the Tutor.
- Open the workbook in Excel and in LibreOffice. For the two traced students, check score and
  rank against a hand calculation under the starting weights. Repeat after changing a weight,
  after setting a weight to 0 and after changing a threshold.

### First run, 17 October 2026

- Totals matched the admin tab for all 124 users with a record.
- Attempts differed on 8 of about 1,400 student-question pairs. In each one the log had one more
  attempt than the progress record. PRQ001 to PRQ003 have no progress record, so their
  submissions weren't compared. The cause of the 8 isn't known. The report uses the log.
- The progress clock matched the log on every question but one. That one is a record on the
  test account written by a Melbourne machine, and it also set off the future-date warning.
- The first 50 messages gave 8 real questions among 11 flagged. Two more samples, of 50 and
  200, brought it to 64 of 77 (83%), so the word list stays. A tighter rule did no better on the
  200.
- Two traced students matched by hand. In Excel, every score, rank and eligibility result
  matched an independent calculation across nine weight and threshold settings. LibreOffice
  wasn't installed, so that half of the last check is still open.

## Left out on purpose

- Time between attempts as a sign of a considered resubmission. A quick resubmit is often a
  typo fix rather than a guess.
- Detecting identical resubmissions. There is no sign of gaming, and students don't know what
  is measured.
- Whether a student used the Tutor before the Assessor. A student may have learned a topic
  elsewhere and gone straight to practice.
- A daily cap on counted interactions. The starting Prize 1 weights rank on active days, which
  already stops one long sitting from dominating.

## Known limits

- Tutor days and revisits from before the logging change are lower bounds. Look at flagged
  students by hand.
- Follow-up questions are detected with a word list.
- Changing a question's text after students have attempted it splits its attempts across two
  rows.
- Under the starting weights, Prize 2 ranks a student who only used the Tutor on weaker
  measures (a word list and lower-bound dates). Treat their rank with more caution.
