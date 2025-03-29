"""Chat message models for the tutor system"""
from typing import Optional, Dict, Any

class ChatMessage:
    """Class to represent chat messages with proper typing"""
    def __init__(self, role: str, content: str, response_id: Optional[str] = None):
        self.role = role
        self.content = content
        self.response_id = response_id

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "content": self.content,
            "response_id": self.response_id
        } 