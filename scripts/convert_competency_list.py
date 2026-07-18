"""
Convert knowledge/NewSubjectDataToReplaceCurrentData/90059_PRQ-CompetencyList.csv
into the two CSVs expected by scripts/update_module_data.py:

  - module_data.csv           (starter: topics filled from competencies, Questions blank)
  - question_data_final.csv   (empty template: headers only, author questions manually)

Usage (from the project root):
  python scripts/convert_competency_list.py            # grouped: one topic per Sub ID #1 group
  python scripts/convert_competency_list.py --per-row  # one topic per competency row

Notes:
  - The source file is TAB-separated (despite the .csv extension), Windows-1252 encoded,
    with hundreds of trailing empty columns per row.
  - In grouped mode, the row with Sub ID #2 == 0 (or blank) is treated as the topic
    overview; remaining rows in the group are appended as bullet points.
  - Module names below are placeholders - EDIT MODULE_NAMES before loading to MongoDB.
"""

import argparse
import csv
from pathlib import Path

SOURCE = Path(__file__).parent.parent / "knowledge" / "NewSubjectDataToReplaceCurrentData" / "90059_PRQ-CompetencyList.csv"

# Mapping confirmed with lecturers: Week N = Lecture N = Module N, and the
# module title IS the lecture title. Replace these placeholders with the actual
# lecture titles when the lecture slides arrive (also update pages/*.py and the
# ordering list in pages/1_Your_Progress.py to match these exactly).
MODULE_NAMES = {
    1: "Module 1 - PLACEHOLDER (use Lecture 1 title)",
    2: "Module 2 - PLACEHOLDER (use Lecture 2 title)",
    3: "Module 3 - PLACEHOLDER (use Lecture 3 title)",
}

# Topic (overview competency) names per (Module ID, Sub ID #1) group, taken from
# 90059_Week1-3-CompetencyList-CF.docx (the numbered headings, e.g.
# "1. Definition of Reliability"). Fill these in from the docx; any group not
# listed here falls back to the group's Sub-ID#2==0 overview row title, or the
# first row's title prefixed with "CHECK:" so unreviewed names are easy to spot.
OVERVIEW_NAMES = {
    (1, 1): "Definition of Reliability",
    (1, 2): "Fundamental Reliability Functions",
    (1, 3): "Rated Life and Reliability-based Decisions",
    # (1, 4): "...",  # <- paste remaining headings from the docx
}

MODULE_COLUMNS = ["Module Number", "Module Name", "Topic", "Description (Answer)", "Questions"]
QUESTION_COLUMNS = [
    "Module Number", "Question label", "Question text", "Expected answer",
    "Success criteria", "Further information required in prompt",
    "question_URL", "answer_URL",
]


def read_competencies(path: Path):
    """Yield dicts: {id, sub1, sub2, title, content}."""
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            text = path.read_text(encoding=encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise SystemExit(f"Could not decode {path}")

    rows = []
    reader = csv.reader(text.splitlines(), delimiter="\t")
    header = next(reader)
    for raw in reader:
        cells = [c.strip() for c in raw]
        if not any(cells):
            continue
        mid, sub1, sub2, title, content = (cells + [""] * 5)[:5]
        if not mid or not title:
            continue
        rows.append({
            "id": int(mid),
            "sub1": int(sub1) if sub1 else 0,
            "sub2": int(sub2) if sub2 else None,  # None = standalone/parent row
            "title": title,
            "content": content,
        })
    return rows


def topics_per_row(rows):
    """One topic per competency row."""
    for r in rows:
        yield r["id"], r["title"], r["content"]


def topics_grouped(rows):
    """One topic per (Module ID, Sub ID #1) group."""
    groups = {}
    for r in rows:
        groups.setdefault((r["id"], r["sub1"]), []).append(r)

    for (mid, sub1), items in sorted(groups.items()):
        # Overview row: Sub ID #2 == 0 or blank, if the group has one.
        overview = next((r for r in items if r["sub2"] in (None, 0)), None)

        if (mid, sub1) in OVERVIEW_NAMES:
            name = OVERVIEW_NAMES[(mid, sub1)]
        elif overview is not None:
            name = overview["title"]
        else:
            name = f"CHECK: {items[0]['title']}"  # no overview available - review manually

        details = [r for r in items if r is not overview]
        parts = [overview["content"]] if overview and overview["content"] else []
        parts += [f"- {r['title']}: {r['content']}" for r in details]
        yield mid, name, "\n".join(parts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--per-row", action="store_true",
                        help="one topic per competency row (default: grouped by Sub ID #1)")
    parser.add_argument("--outdir", default=".", help="output directory (default: cwd)")
    args = parser.parse_args()

    rows = read_competencies(SOURCE)
    topic_iter = topics_per_row(rows) if args.per_row else topics_grouped(rows)

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    module_path = outdir / "module_data.csv"
    n_topics, modules_seen = 0, set()
    with open(module_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(MODULE_COLUMNS)
        for mid, topic, description in topic_iter:
            writer.writerow([
                mid,
                MODULE_NAMES.get(mid, f"Module {mid} - PLACEHOLDER"),
                topic,
                description,
                "",  # Questions: diagnostic question per topic - author manually
            ])
            n_topics += 1
            modules_seen.add(mid)

    question_path = outdir / "question_data_final.csv"
    with open(question_path, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(QUESTION_COLUMNS)

    print(f"Read {len(rows)} competencies across modules {sorted(modules_seen)}")
    print(f"Wrote {module_path} ({n_topics} topics)")
    print(f"Wrote {question_path} (empty template - author tutorial questions here)")
    print("\nBefore running scripts/update_module_data.py:")
    print("  1. Edit MODULE_NAMES in this script (or the CSV) to the real module names.")
    print("  2. Fill in the 'Questions' column (diagnostic question per topic).")
    print("  3. Add tutorial questions to question_data_final.csv.")
    print("  4. Fix the hard-coded 'funce_db' in update_module_data.py (see README).")


if __name__ == "__main__":
    main()
