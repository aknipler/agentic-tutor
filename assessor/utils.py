from typing import Dict, List, Union

# Single definition, shared with the progress page and the tutor. Re-exported here
# because callers across the assessor already import it from this module.
from utils.status import get_status_emoji, get_status_from_progress  # noqa: F401

def convert_questions_to_dict(questions: Union[List, Dict]) -> Dict:
    """Convert questions from list to dictionary format if needed"""
    if isinstance(questions, list):
        return {f"q{i+1}": question for i, question in enumerate(questions)}
    return questions 