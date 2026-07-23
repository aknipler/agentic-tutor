"""Convert a learning-outcomes markdown file into structured per-lecture JSON.

Expected markdown format:

    ### Lecture 1: Probability, Reliability and Quality

    1. **Definition of reliability**
       - Reliability engineering reduces ...
       - Reliability is assessed under specified conditions ...

    2. **Fundamental reliability functions**
       - Interpret cumulative probability of failure by time.

Produces a single JSON file containing a list of lectures:

    [
      {
        "lecture": 1,
        "lecture_title": "Probability, Reliability and Quality",
        "topics": {
          "Definition of reliability": {
            "learning_outcomes": [...]
          },
          ...
        }
      },
      ...
    ]

Usage:
    python scripts/md_to_learning_outcomes_json.py <input.md> <output.json>
"""

import json
import re
import sys
from pathlib import Path

LECTURE_RE = re.compile(r"^###\s*Lecture\s+(\d+)\s*:\s*(.+?)\s*$")
TOPIC_RE = re.compile(r"^\d+\.\s*\*\*(.+?)\*\*\s*$")
OUTCOME_RE = re.compile(r"^-\s+(.+?)\s*$")


def parse_markdown(text: str) -> list[dict]:
    lectures = []
    current_lecture = None
    current_topic = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        lecture_match = LECTURE_RE.match(line)
        if lecture_match:
            current_lecture = {
                "lecture": int(lecture_match.group(1)),
                "lecture_title": lecture_match.group(2),
                "topics": {},
            }
            lectures.append(current_lecture)
            current_topic = None
            continue

        topic_match = TOPIC_RE.match(line)
        if topic_match:
            if current_lecture is None:
                raise ValueError(f"Topic found before any lecture heading: {line!r}")
            current_topic = topic_match.group(1)
            current_lecture["topics"][current_topic] = {"learning_outcomes": []}
            continue

        outcome_match = OUTCOME_RE.match(line)
        if outcome_match:
            if current_lecture is None or current_topic is None:
                raise ValueError(f"Learning outcome found before a topic heading: {line!r}")
            current_lecture["topics"][current_topic]["learning_outcomes"].append(
                outcome_match.group(1)
            )
            continue

    return lectures


def main() -> None:
    if len(sys.argv) != 3:
        print(f"Usage: python {Path(__file__).name} <input.md> <output.json>")
        sys.exit(1)

    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])
    output_path.parent.mkdir(parents=True, exist_ok=True)

    text = input_path.read_text(encoding="utf-8")
    lectures = parse_markdown(text)

    if not lectures:
        print("No lectures found in input file.")
        sys.exit(1)

    output_path.write_text(json.dumps(lectures, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {len(lectures)} lecture(s) to {output_path}")


if __name__ == "__main__":
    main()
