# Draft per-topic diagnostic questions — for lecturer review

**Purpose.** The tutor opens each topic with a single focused Socratic question. The lecturer
`week_*_assessor_questions.json` files supply each topic's `name` + `description` but **no**
`question` field. The tutor now degrades gracefully — if a topic has no `question`, it generates
an opener on the fly from the description (`build_initial_topic_prompt` in
`utils/tutor/interface.py`). These drafts are the **preferred** alternative: authored openers the
lecturers can vet, so the tutor asks a consistent, intended question rather than an ad-hoc one.

**How to use.** Skim each question below. Edit freely. For any topic you approve, add a
`"question"` field to that topic in the matching
`knowledge/MCEN_resources_extracted/week_N_assessor_questions.json`, then re-run
`scripts/load_week_json.py --commit`. Topics left without a `question` still work (generated opener).

These are *opening* diagnostic questions to start discussion — not the graded tutorial questions
(which live in `tutorial_questions`). 30 topics total: 11 + 7 + 12.

---

## Week 1 — Probability, Reliability and Quality

| # | Topic | Draft diagnostic question |
|---|-------|---------------------------|
| 1 | Definition of Reliability | In your own words, what does it mean to say a component "has a reliability of 95%"? Make sure your answer pins down *what function*, over *what time period*, and under *what conditions*. |
| 2 | Fundamental Reliability Functions | If the cumulative probability of failure F(t) rises as time goes on, what must happen to the reliability R(t) — and why must R(t) and F(t) always add up to 1? |
| 3 | Rated Life and Reliability Decisions | A bearing is rated for 20,000 hours at a minimum reliability of 95%. How would you use *both* of those numbers to decide when to inspect, service, or replace it? |
| 4 | Reliability Requirements and Escapes | What three pieces of information does a well-formed reliability requirement have to contain — and how would a part that fails prematurely relate to the idea of an "escape"? |
| 5 | Failure Types Across the Life Cycle | A part can fail early in life, during normal life, or at end of life. What physical cause would you associate with each, and how do they differ? |
| 6 | Definition and Dimensions of Quality | Beyond "it works well," what does *quality* actually mean for an engineered product? Can you name some of the distinct dimensions it might be judged on? |
| 7 | Turnbacks and Non-Conformance | What is the difference between a turnback, rework, scrap, and a customer escape — and where does each one occur in the production flow? |
| 8 | Tolerances, Scrap Rate and Yield | Given a lot's size and how many units fell outside the specification limits, how would you work out the scrap rate and yield? What does "parts per million non-conforming" add to that picture? |
| 9 | Manufacturing Outcome Distributions | If you fitted a distribution to a process's output, how would its mean and spread *relative to the specification limits* let you estimate the fraction of conforming parts? |
| 10 | Process Potential and Capability | What's the difference between Cp and Cpk — and what does it tell you when Cpk comes out much smaller than Cp? |
| 11 | Short-Term and Long-Term Performance | Why might a process that looks highly capable over a single week (say Cpk = 1.67) still deliver poor quality over a full production run? |

## Week 2 — Inspections and Processes

| # | Topic | Draft diagnostic question |
|---|-------|---------------------------|
| 1 | Inspection Methods | How would you weigh up visual inspection, go/no-go gauging, and continuous metrology for a production line? On what dimensions do they actually differ? |
| 2 | Production Control as Feedback | How is controlling a production process like a feedback loop — and why can continuous measurement catch a problem *before* any scrap is produced? |
| 3 | Manufacturing Data and Correlation | If two process variables turn out to be strongly correlated in your data, what can — and can't — you conclude from that, and what would you do next? |
| 4 | Production Rate, Cycle Time and Takt Time | What is takt time, and how would you use it together with your net acceptable output to judge whether you can meet customer demand? |
| 5 | Sources of Manufacturing Defects | Think of a manufacturing line you know. What are the main *categories* of cause that could produce a defective unit? |
| 6 | Inspection-Centred and Process-Centred Quality | What's the fundamental difference between catching defects after production and preventing them at the source — and which would you prioritise, and why? |
| 7 | Process Maps and FMEA | In an FMEA, what do failure mode, effect, cause, severity, occurrence, and detection each capture — and how do they combine to tell you where to act first? |

## Week 3 — ANOVA and Gauge Repeatability & Reproducibility

| # | Topic | Draft diagnostic question |
|---|-------|---------------------------|
| 1 | ANOVA Purpose and Selection | What question is ANOVA actually answering for you — and how would you decide between a one-way and a two-way model for a given experiment? |
| 2 | One-Way ANOVA Hypotheses | For a one-way ANOVA, how would you state the null and alternative hypotheses? In your example, what is the response and what is the factor? |
| 3 | ANOVA Table Interpretation | Walk me through an ANOVA table: what do the sums of squares, mean squares, and F-statistic each tell you, and how does that lead to a p-value? |
| 4 | Statistical Conclusions and Post-Hoc Analysis | If your ANOVA comes back significant, can you already say *which* groups differ? If not, what would you need to do next? |
| 5 | Residual Analysis and Model Adequacy | Before you trust an ANOVA conclusion, what would you check about the residuals — and why does each check matter? |
| 6 | Two-Way ANOVA and Interactions | What does it mean for two factors to "interact," and how does an interaction change the way you interpret their main effects? |
| 7 | Measurement Error Decomposition | When you measure a part and see some spread in the readings, what two broad sources is that variation coming from? |
| 8 | Accuracy, Bias, Resolution and Precision | How would you distinguish accuracy, bias, resolution, and precision? Can a gauge be precise but not accurate? |
| 9 | Repeatability, Reproducibility, Stability and Linearity | What's the difference between repeatability and reproducibility — and where do stability and linearity fit in? |
| 10 | Gauge R&R Study Design | How would you design a crossed Gauge R&R study — what would you deliberately vary, and why does randomising the measurement order matter? |
| 11 | Gauge R&R Metrics | A Gauge R&R report hands you %Contribution, %Study Variation, %Tolerance, and the number of distinct categories. What is each one telling you about the measurement system? |
| 12 | Gauge R&R Decision-Making | Given a Gauge R&R result, how would you decide whether the measurement system is good enough — and does the bar differ for inspection versus process control? |
