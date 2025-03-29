"""Tutor package for the FunCE2.0 application"""

from .interface import render_tutor_interface
from .models.chat import ChatMessage
from .config.settings import TutorConfig, COMPETENCY_LEVELS, MODULE_TITLES

__all__ = [
    'render_tutor_interface',
    'ChatMessage',
    'TutorConfig',
    'COMPETENCY_LEVELS',
    'MODULE_TITLES'
] 