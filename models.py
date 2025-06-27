from enum import Enum
from pydantic import BaseModel
from typing import Dict, Any, Optional, Tuple
from datetime import datetime
from abc import ABC, abstractmethod

class BookingRequest(BaseModel):
    book_title: str
    name: str
    phone: str
    duration: int

class BookQuery(BaseModel):
    book_title: str

class ChatMessage(BaseModel):
    message: str
    user_id: str = "default"

class ConversationState(Enum):
    INITIAL = 1
    AWAITING_BOOK_TITLE = 2
    AWAITING_USER_DETAILS = 3
    CONFIRMATION = 4

# Add the AIProvider base class here
class AIProvider(ABC):
    @abstractmethod
    def initialize(self, api_key: str):
        pass
    
    @abstractmethod
    def generate_response(self, system_prompt: str, user_message: str) -> str:
        pass