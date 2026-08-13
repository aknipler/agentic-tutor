"""Cohort-level counts for the admin dashboard's Data Analysis tab.

Everything here aggregates across the whole class at once, so nothing takes a
`user_id`. Two databases are involved: progress lives in `MONGODB_DATABASE_NAME`,
while the tutor transcripts and assessor submissions that show whether a student
ever actually turned up live in `MONGODB_LOGS_DATABASE_NAME` (mongodb/logger.py).

Counting is done server-side, in aggregation pipelines, rather than by pulling
documents back and tallying them in Python. Both sources carry the bulky part of
the app's data - full tutor transcripts on one side, students' submitted answer
images (`questions.*.input_image_data`) on the other - and moving all of that
across the wire just to count level 2s would cost megabytes on every cache miss.

Results are cached for five minutes. The dashboard re-runs its whole script on
every widget interaction, and these are the most expensive reads in it.
"""
from typing import Any, Dict, List

import streamlit as st

from .base import get_mongo_client

CACHE_TTL_SECONDS = 300


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def get_tutor_message_counts() -> Dict[str, int]:
    """Count each student's own messages to the tutor, keyed by user_id.

    A logged conversation is a list of `[student_message, tutor_message]` pairs,
    and a tutor-generated opening question is written with an empty student
    message (mongodb/logger.py). Counting only non-empty first elements
    therefore counts the times a student actually said something, not the times
    the tutor spoke to them.

    Returns:
        dict: {user_id: number of messages}. Users who never wrote anything are
        absent, so the keys are exactly the students who have used the tutor.
    """
    pipeline = [
        {"$unwind": "$conversations"},
        {"$unwind": "$conversations.conversation"},
        {
            "$project": {
                "user_id": 1,
                # A malformed entry would make $arrayElemAt fail the whole
                # pipeline; treat anything that isn't a pair as no message.
                "student_message": {
                    "$cond": [
                        {"$isArray": "$conversations.conversation"},
                        {"$arrayElemAt": ["$conversations.conversation", 0]},
                        "",
                    ]
                },
            }
        },
        {"$match": {"student_message": {"$type": "string", "$ne": ""}}},
        {"$group": {"_id": "$user_id", "messages": {"$sum": 1}}},
    ]

    try:
        db = get_mongo_client()[st.secrets["MONGODB_LOGS_DATABASE_NAME"]]
        results = db["user_conversations"].aggregate(pipeline)
        return {doc["_id"]: doc["messages"] for doc in results if doc.get("_id")}
    except Exception as e:
        print(f"[Error] Exception in get_tutor_message_counts: {str(e)}")
        st.error(f"Error counting tutor messages: {str(e)}")
        return {}


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def get_assessor_submission_counts() -> Dict[str, int]:
    """Count each student's assessor submissions, keyed by user_id.

    Every graded answer is appended to that student's `submissions` array, so
    this counts attempts, not distinct questions - a question answered three
    times counts three times.

    Returns:
        dict: {user_id: number of submissions}. Students with no submissions
        are absent.
    """
    pipeline = [
        {
            "$project": {
                "user_id": 1,
                "submissions": {
                    "$cond": [{"$isArray": "$submissions"}, {"$size": "$submissions"}, 0]
                },
            }
        },
        {"$match": {"submissions": {"$gt": 0}}},
    ]

    try:
        db = get_mongo_client()[st.secrets["MONGODB_LOGS_DATABASE_NAME"]]
        results = db["user_submissions"].aggregate(pipeline)
        return {doc["user_id"]: doc["submissions"] for doc in results if doc.get("user_id")}
    except Exception as e:
        print(f"[Error] Exception in get_assessor_submission_counts: {str(e)}")
        st.error(f"Error counting assessor submissions: {str(e)}")
        return {}


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def get_module_completion_counts(module_id: str) -> List[Dict[str, Any]]:
    """Per-student completion counts for one module.

    Both counts are of level 2 only - the 0/1/2 scale's "full competency" - so a
    topic still in progress contributes nothing. Topics record their level under
    `progress`, questions under `competency_level`; that split is how the two
    halves of the app already write them.

    Args:
        module_id: The module's 1-based `index`, as a string. Progress documents
            key modules by exactly that (never by title).

    Returns:
        list: one dict per student with a progress record - `user_id`,
        `topics_completed`, `questions_completed`. A student who has never
        opened this module has a record with both counts at 0.
    """
    module_key = str(module_id)
    pipeline = [
        {
            "$project": {
                "user_id": 1,
                # $objectToArray turns the name-keyed topic/question maps into
                # arrays that $filter can count. Missing module -> empty.
                "topics": {
                    "$objectToArray": {"$ifNull": [f"$modules.{module_key}.topics", {}]}
                },
                "questions": {
                    "$objectToArray": {"$ifNull": [f"$modules.{module_key}.questions", {}]}
                },
            }
        },
        {
            "$project": {
                "user_id": 1,
                "topics_completed": {
                    "$size": {
                        "$filter": {
                            "input": "$topics",
                            "as": "topic",
                            "cond": {"$eq": ["$$topic.v.progress", 2]},
                        }
                    }
                },
                "questions_completed": {
                    "$size": {
                        "$filter": {
                            "input": "$questions",
                            "as": "question",
                            "cond": {"$eq": ["$$question.v.competency_level", 2]},
                        }
                    }
                },
            }
        },
    ]

    try:
        db = get_mongo_client()[st.secrets["MONGODB_DATABASE_NAME"]]
        results = db["user_module_progress"].aggregate(pipeline)
        return [
            {
                "user_id": doc["user_id"],
                "topics_completed": doc.get("topics_completed", 0),
                "questions_completed": doc.get("questions_completed", 0),
            }
            for doc in results
            if doc.get("user_id")
        ]
    except Exception as e:
        print(f"[Error] Exception in get_module_completion_counts: {str(e)}")
        st.error(f"Error loading module completion data: {str(e)}")
        return []


def clear_analytics_caches() -> None:
    """Drop every cached count, so the next read hits the database."""
    get_tutor_message_counts.clear()
    get_assessor_submission_counts.clear()
    get_module_completion_counts.clear()
