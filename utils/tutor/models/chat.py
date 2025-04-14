"""Chat message models for the tutor system"""
from typing import Optional, Dict, Any

class ChatMessage:
    """Class to represent chat messages with proper typing"""
    def __init__(self, role: str, content: str, response_id: Optional[str] = None, topic_name: Optional[str] = None):
        self.role = role
        self.content = content
        self.response_id = response_id
        self.topic_name = topic_name

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "content": self.content,
            "response_id": self.response_id,
            "topic_name": self.topic_name
        } 