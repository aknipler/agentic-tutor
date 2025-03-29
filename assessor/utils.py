from typing import Dict, List, Union

def convert_questions_to_dict(questions: Union[List, Dict]) -> Dict:
    """Convert questions from list to dictionary format if needed"""
    if isinstance(questions, list):
        return {f"q{i+1}": question for i, question in enumerate(questions)}
    return questions

def get_status_emoji(status: str) -> str:
    """Get the emoji representation for a question status"""
    status_emoji = {
        "completed": "✅",
        "in_progress": "🟠",
        "not_started": "🔴"
    }
    return status_emoji.get(status, "🔴") 