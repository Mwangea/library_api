from fastapi import FastAPI, HTTPException, Body
from pydantic import BaseModel
from datetime import datetime
import pandas as pd
import os
import json
from enum import Enum
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Tuple

# === CONFIG ===
load_dotenv()
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

EXCEL_PATH = os.path.abspath("library_db.xlsx")
print(f"Excel file path: {EXCEL_PATH}")

# === MODELS ===
class BookingRequest(BaseModel):
    book_title: str
    name: str
    phone: str
    duration: int

class BookQuery(BaseModel):
    book_title: str

class ChatMessage(BaseModel):
    message: str
    user_id: str = "default"  # Optional user ID for conversation tracking

# === AI PROVIDER INTERFACE ===
class AIProvider(ABC):
    @abstractmethod
    def initialize(self, api_key: str):
        pass
    
    @abstractmethod
    def generate_response(self, system_prompt: str, user_message: str) -> str:
        pass

# === CONCRETE AI PROVIDERS ===
class OpenAIGPTProvider(AIProvider):
    def __init__(self):
        from openai import OpenAI
        self.client = None
        self.OpenAI = OpenAI
    
    def initialize(self, api_key: str):
        self.client = self.OpenAI(api_key=api_key)
    
    def generate_response(self, system_prompt: str, user_message: str) -> str:
        models_to_try = ["gpt-4", "gpt-4-turbo", "gpt-3.5-turbo"]
        last_error = None
        
        for model in models_to_try:
            try:
                response = self.client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message}
                    ],
                    max_tokens=400,
                    temperature=0.3
                )
                return response.choices[0].message.content
            except Exception as e:
                last_error = e
                continue
        
        raise last_error or Exception("No models available")

class GeminiProvider(AIProvider):
    def __init__(self):
        import google.generativeai as genai
        self.genai = genai
        self.model = None
    
    def initialize(self, api_key: str):
        self.genai.configure(api_key=api_key)
        # Use the free model - try 1.5 Flash first, fall back to 1.5 Pro
        try:
            self.model = self.genai.GenerativeModel('gemini-1.5-flash')
        except:
            self.model = self.genai.GenerativeModel('gemini-1.5-pro')
    
    def generate_response(self, system_prompt: str, user_message: str) -> str:
        full_prompt = f"{system_prompt}\n\nUser Message: {user_message}"
        try:
            response = self.model.generate_content(
                full_prompt,
                generation_config={
                    "temperature": 0.3,
                    "max_output_tokens": 400
                }
            )
            return response.text
        except Exception as e:
            print(f"Gemini API Error: {str(e)}")
            return "Sorry, I'm having trouble generating a response. Please try again."

# === AI PROVIDER FACTORY ===
class AIProviderFactory:
    @staticmethod
    def create_provider(provider_name: str) -> AIProvider:
        providers = {
            "openai": OpenAIGPTProvider,
            "gemini": GeminiProvider
        }
        
        if provider_name.lower() not in providers:
            raise ValueError(f"Unsupported provider: {provider_name}")
        
        return providers[provider_name.lower()]()

# === CONVERSATION MANAGEMENT ===
class ConversationState(Enum):
    INITIAL = 1
    AWAITING_BOOK_TITLE = 2
    AWAITING_USER_DETAILS = 3
    CONFIRMATION = 4

class ConversationManager:
    def __init__(self):
        self.conversation_state: Dict[str, ConversationState] = {}
        self.user_data: Dict[str, Dict[str, Any]] = {}
    
    def initialize_user(self, user_id: str):
        if user_id not in self.conversation_state:
            self.conversation_state[user_id] = ConversationState.INITIAL
            self.user_data[user_id] = {}
    
    def get_state(self, user_id: str) -> ConversationState:
        return self.conversation_state.get(user_id, ConversationState.INITIAL)
    
    def set_state(self, user_id: str, state: ConversationState):
        self.conversation_state[user_id] = state
    
    def get_user_data(self, user_id: str) -> Dict[str, Any]:
        return self.user_data.get(user_id, {})
    
    def update_user_data(self, user_id: str, data: Dict[str, Any]):
        if user_id not in self.user_data:
            self.user_data[user_id] = {}
        self.user_data[user_id].update(data)
    
    def reset_user(self, user_id: str):
        self.conversation_state.pop(user_id, None)
        self.user_data.pop(user_id, None)

# === BOOK MANAGEMENT ===
class BookManager:
    def __init__(self, excel_path: str):
        self.excel_path = excel_path
    
    def load_sheet(self, sheet_name: str) -> pd.DataFrame:
        return pd.read_excel(self.excel_path, sheet_name=sheet_name)
    
    def save_sheet(self, sheet_name: str, df: pd.DataFrame):
        # Read existing workbook to preserve other sheets
        try:
            with pd.ExcelFile(self.excel_path) as xls:
                sheet_dict = {}
                for sheet in xls.sheet_names:
                    if sheet != sheet_name:  # Don't reload the sheet we're updating
                        sheet_dict[sheet] = pd.read_excel(xls, sheet_name=sheet)
                
                # Add the updated sheet
                sheet_dict[sheet_name] = df
                
                # Write all sheets back
                with pd.ExcelWriter(self.excel_path, engine='openpyxl') as writer:
                    for name, data in sheet_dict.items():
                        data.to_excel(writer, sheet_name=name, index=False)
                        
        except Exception as e:
            print(f"Error saving sheet {sheet_name}: {str(e)}")
            # Fallback: try to save just this sheet
            with pd.ExcelWriter(self.excel_path, engine='openpyxl', mode='a', if_sheet_exists='replace') as writer:
                df.to_excel(writer, sheet_name=sheet_name, index=False)
    
    def get_available_books(self) -> pd.DataFrame:
        return self.load_sheet('Books')
    
    def get_bookings(self) -> pd.DataFrame:
        try:
            return self.load_sheet('Bookings')
        except:
            # Create empty bookings sheet if it doesn't exist
            empty_bookings = pd.DataFrame(columns=[
                'Booking ID', 'Name', 'Book Title', 'Phone Number', 
                'Duration (Days)', 'Date Booked'
            ])
            self.save_sheet('Bookings', empty_bookings)
            return empty_bookings
    
    def get_available_books_list(self) -> list:
        """Get a formatted list of available books for AI context"""
        df = self.get_available_books()
        available_books = []
        for idx, row in df.iterrows():
            if row['Available Copies'] > 0:
                available_books.append({
                    'title': row['Title'],
                    'author': row.get('Author', 'Unknown'),
                    'available_copies': row['Available Copies']
                })
        return available_books
    
    def check_book_availability(self, title: str) -> Tuple[bool, Optional[int], Optional[Dict[str, Any]]]:
        df = self.get_available_books()
        print(f"Looking for book: '{title}'")
        print(f"Available books in database:")
        for idx, row in df.iterrows():
            print(f"  - '{row['Title']}' (Available: {row['Available Copies']})")

        exact_match = df[df["Title"].str.lower() == title.lower()]
        if not exact_match.empty:
            is_available = exact_match.iloc[0]["Available Copies"] > 0
            book_info = {
                'title': exact_match.iloc[0]['Title'],
                'author': exact_match.iloc[0].get('Author', 'Unknown'),
                'available': is_available,
                'copies': exact_match.iloc[0]['Available Copies']
            }
            print(f"Exact match found: {exact_match.iloc[0]['Title']}, Available: {is_available}")
            return (bool(is_available), exact_match.index[0], book_info)

        partial_match = df[df["Title"].str.lower().str.contains(title.lower(), na=False)]
        if not partial_match.empty:
            is_available = partial_match.iloc[0]["Available Copies"] > 0
            book_info = {
                'title': partial_match.iloc[0]['Title'],
                'author': partial_match.iloc[0].get('Author', 'Unknown'),
                'available': is_available,
                'copies': partial_match.iloc[0]['Available Copies']
            }
            print(f"Partial match found: {partial_match.iloc[0]['Title']}, Available: {is_available}")
            return (bool(is_available), partial_match.index[0], book_info)

        normalized_input = title.lower().replace(" ", "").replace("_", "")
        df["normalized_title"] = df["Title"].str.lower().str.replace(" ", "").str.replace("_", "")
        normalized_match = df[df["normalized_title"] == normalized_input]

        if not normalized_match.empty:
            is_available = normalized_match.iloc[0]["Available Copies"] > 0
            book_info = {
                'title': normalized_match.iloc[0]['Title'],
                'author': normalized_match.iloc[0].get('Author', 'Unknown'),
                'available': is_available,
                'copies': normalized_match.iloc[0]['Available Copies']
            }
            print(f"Normalized match found: {normalized_match.iloc[0]['Title']}, Available: {is_available}")
            return (bool(is_available), normalized_match.index[0], book_info)

        print("No match found")
        return (False, None, None)
    
    def reserve_book(self, name: str, title: str, phone: str, duration: int) -> Dict[str, Any]:
        print(f"Starting reservation process for: {title}")
        
        # Load current data
        books_df = self.get_available_books()
        bookings_df = self.get_bookings()
        
        print(f"Current books data loaded. Shape: {books_df.shape}")
        print(f"Current bookings data loaded. Shape: {bookings_df.shape}")

        # Find the book and update available copies
        book_match = books_df[books_df['Title'].str.lower() == title.lower()]
        if book_match.empty:
            raise Exception(f"Book '{title}' not found in database")
        
        idx = book_match.index[0]
        current_copies = books_df.at[idx, 'Available Copies']
        
        if current_copies <= 0:
            raise Exception(f"Book '{title}' is not available (0 copies)")
        
        # Decrease available copies
        books_df.at[idx, 'Available Copies'] = current_copies - 1
        print(f"Updated available copies from {current_copies} to {current_copies - 1}")

        # Create new booking entry
        new_booking_id = len(bookings_df) + 1 if len(bookings_df) > 0 else 1
        new_booking = {
            'Booking ID': new_booking_id,
            'Name': name,
            'Book Title': title,
            'Phone Number': phone,
            'Duration (Days)': duration,
            'Date Booked': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        
        # Add new booking to dataframe
        new_booking_df = pd.DataFrame([new_booking])
        bookings_df = pd.concat([bookings_df, new_booking_df], ignore_index=True)
        
        print(f"Created new booking: {new_booking}")

        # Save both sheets
        try:
            print("Saving Books sheet...")
            self.save_sheet('Books', books_df)
            print("Books sheet saved successfully")
            
            print("Saving Bookings sheet...")
            self.save_sheet('Bookings', bookings_df)
            print("Bookings sheet saved successfully")
            
            # Verify the save worked
            verification_books = self.get_available_books()
            verification_bookings = self.get_bookings()
            
            print(f"Verification - Books shape: {verification_books.shape}")
            print(f"Verification - Bookings shape: {verification_bookings.shape}")
            print(f"Verification - Book '{title}' now has {verification_books.at[idx, 'Available Copies']} copies")
            
        except Exception as e:
            print(f"Error saving to Excel: {str(e)}")
            raise Exception(f"Failed to save booking: {str(e)}")

        return new_booking

# === UTILITIES ===
class MessageParser:
    @staticmethod
    def extract_book_title_from_message(message: str) -> str:
        """Try to extract a potential book title from user message"""
        message_lower = message.lower()
        
        # Remove common phrases
        remove_phrases = [
            'i want to reserve', 'i want to borrow', 'i need', 'can i get', 
            'do you have', 'is available', 'check for', 'looking for',
            'i want', 'i would like', 'book called', 'book titled'
        ]
        
        cleaned_message = message_lower
        for phrase in remove_phrases:
            cleaned_message = cleaned_message.replace(phrase, '').strip()
        
        # Remove quotes if present
        cleaned_message = cleaned_message.strip('"\'')
        
        return cleaned_message.strip()

    @staticmethod
    def parse_user_details(message: str) -> Optional[Dict[str, Any]]:
        """Try to parse user details from message"""
        try:
            parts = [x.strip() for x in message.split(',')]
            if len(parts) >= 3:
                name = parts[0]
                phone = parts[1]
                duration = int(parts[2])
                return {'name': name, 'phone': phone, 'duration': duration}
        except:
            pass
        return None

# === CHAT SERVICE ===
class ChatService:
    def __init__(self, ai_provider: AIProvider, book_manager: BookManager, conversation_manager: ConversationManager):
        self.ai_provider = ai_provider
        self.book_manager = book_manager
        self.conversation_manager = conversation_manager
    
    def get_system_prompt(self, conversation_context: Dict[str, Any]) -> str:
        available_books = self.book_manager.get_available_books_list()
        
        base_prompt = f"""
You are a professional library booking assistant. Your role is to ONLY help users with library-related tasks such as:
- Checking book availability
- Taking user details for booking
- Confirming bookings
- Providing information about reservations

❌ You must NOT answer unrelated questions (e.g. general knowledge, jokes, history, programming, etc).
✅ If a user asks something outside the scope of the library, politely say: "Sorry, I can only help with library book reservations."

CURRENT CONVERSATION CONTEXT:
{json.dumps(conversation_context, indent=2)}

AVAILABLE BOOKS IN LIBRARY:
{json.dumps(available_books, indent=2)}

CONVERSATION FLOW RULES:
1. INITIAL GREETING: Welcome users and ask what book they'd like to reserve
2. BOOK INQUIRY: When user mentions a book, check availability and guide them accordingly
3. USER DETAILS: If book is available, ask for: Name, Phone, Duration (in days) in format: "Name, Phone, Duration"
4. CONFIRMATION: Show booking summary and ask for confirmation
5. COMPLETION: Confirm booking with details

RESPONSE GUIDELINES:
- Be friendly, professional, and conversational
- Use emojis appropriately (📚 for books, ✅ for confirmation, etc.)
- Always guide users through the process step by step
- If book is unavailable, suggest alternatives or ask for another title
- For user details, specify the exact format needed
- Always confirm booking details before finalizing

Remember: Stay focused on library services only!
"""
        return base_prompt
    
    def process_message(self, message: str, user_id: str) -> str:
        self.conversation_manager.initialize_user(user_id)
        state = self.conversation_manager.get_state(user_id)
        current_data = self.conversation_manager.get_user_data(user_id)
        
        # Build conversation context
        context = {
            "current_state": state.name,
            "user_data": dict(current_data),
            "last_message": message
        }
        
        # Handle special actions based on message analysis
        action_result = None
        
        # Check if user is trying to specify a book
        if state in [ConversationState.INITIAL, ConversationState.AWAITING_BOOK_TITLE]:
            potential_title = MessageParser.extract_book_title_from_message(message)
            if potential_title:
                available, book_index, book_info = self.book_manager.check_book_availability(potential_title)
                if available:
                    self.conversation_manager.set_state(user_id, ConversationState.AWAITING_USER_DETAILS)
                    self.conversation_manager.update_user_data(user_id, {
                        'book_title': book_info['title'],
                        'book_info': book_info
                    })
                    action_result = f"BOOK_FOUND: {book_info['title']} by {book_info['author']} is available ({book_info['copies']} copies)"
                else:
                    action_result = f"BOOK_NOT_FOUND: '{potential_title}' is not available or not found"
        
        # Check if user is providing details
        elif state == ConversationState.AWAITING_USER_DETAILS:
            details = MessageParser.parse_user_details(message)
            if details:
                self.conversation_manager.update_user_data(user_id, details)
                self.conversation_manager.set_state(user_id, ConversationState.CONFIRMATION)
                action_result = f"DETAILS_RECEIVED: {details}"
        
        # Check for confirmation
        elif state == ConversationState.CONFIRMATION:
            if message.lower() in ['confirm', 'yes', 'y', 'ok', 'sure', 'proceed']:
                try:
                    user_data = self.conversation_manager.get_user_data(user_id)
                    
                    # Validate we have all required data
                    required_fields = ['name', 'book_title', 'phone', 'duration']
                    missing_fields = [field for field in required_fields if field not in user_data]
                    
                    if missing_fields:
                        action_result = f"BOOKING_ERROR: Missing required fields: {missing_fields}"
                    else:
                        print(f"Processing booking for user {user_id}: {user_data}")
                        
                        booking = self.book_manager.reserve_book(
                            user_data['name'],
                            user_data['book_title'], 
                            user_data['phone'],
                            user_data['duration']
                        )
                        
                        # Clean up conversation state
                        self.conversation_manager.reset_user(user_id)
                        
                        action_result = f"BOOKING_CONFIRMED: {json.dumps(booking)}"
                        print(f"Booking completed successfully: {booking}")
                        
                except Exception as e:
                    print(f"Booking error: {str(e)}")
                    action_result = f"BOOKING_ERROR: {str(e)}"
            
            elif message.lower() in ['cancel', 'no', 'n', 'abort']:
                self.conversation_manager.reset_user(user_id)
                action_result = "BOOKING_CANCELLED"
        
        # Update context with action result
        if action_result:
            context["action_result"] = str(action_result)
        
        # Generate AI response
        try:
            json_safe_context = json.dumps(context, indent=2, default=str)
            system_prompt = self.get_system_prompt(json_safe_context)
            response_text = self.ai_provider.generate_response(system_prompt, message)
            return response_text
        
        except Exception as e:
            print(f"AI API Error: {str(e)}")
            return "Sorry, I'm having trouble processing your request. Please try again or contact support."

# === INITIALIZE SERVICES ===
# Choose your AI provider (can be changed to 'gemini' or others as needed)
AI_PROVIDER_NAME = os.getenv("AI_PROVIDER", "openai")  # Default to OpenAI
ai_provider = AIProviderFactory.create_provider(AI_PROVIDER_NAME)
ai_provider.initialize(os.getenv(f"{AI_PROVIDER_NAME.upper()}_API_KEY"))

book_manager = BookManager(EXCEL_PATH)
conversation_manager = ConversationManager()
chat_service = ChatService(ai_provider, book_manager, conversation_manager)

# === ROUTES ===
@app.get("/debug-books")
def debug_books():
    df = book_manager.get_available_books()
    books_list = []
    for idx, row in df.iterrows():
        books_list.append({
            "id": int(row.get("ID", idx)),
            "title": str(row["Title"]),
            "author": str(row.get("Author", "Unknown")),
            "available_copies": int(row["Available Copies"]),
            "total_copies": int(row.get("Total Copies", row["Available Copies"]))
        })
    return {"books": books_list}

@app.get("/debug-bookings")
def debug_bookings():
    """Debug endpoint to see current bookings"""
    try:
        df = book_manager.get_bookings()
        bookings_list = []
        for idx, row in df.iterrows():
            bookings_list.append({
                "booking_id": int(row.get("Booking ID", idx)),
                "name": str(row["Name"]),
                "book_title": str(row["Book Title"]),
                "phone": str(row["Phone Number"]),
                "duration": int(row["Duration (Days)"]),
                "date_booked": str(row["Date Booked"])
            })
        return {"bookings": bookings_list}
    except Exception as e:
        return {"error": str(e), "bookings": []}

@app.post("/check-book")
def check_book(query: BookQuery):
    available, book_index, book_info = book_manager.check_book_availability(query.book_title)
    return {
        "available": bool(available),
        "book_title_searched": query.book_title,
        "book_index": book_index,
        "book_info": book_info
    }

@app.post("/reserve-book")
def book_reservation(payload: BookingRequest):
    available, _, _ = book_manager.check_book_availability(payload.book_title)
    if not available:
        raise HTTPException(status_code=400, detail="Book not available")

    booking = book_manager.reserve_book(payload.name, payload.book_title, payload.phone, payload.duration)
    return {
        "message": "✅ Booking Confirmed",
        "booking": booking
    }

@app.post("/chat")
def chat_with_assistant(payload: ChatMessage):
    reply = chat_service.process_message(payload.message, payload.user_id)
    return {"reply": reply}

# Health check endpoints
@app.get("/")
def root():
    return {"message": "Library Booking API is running!"}

@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "ai_provider": AI_PROVIDER_NAME
    }