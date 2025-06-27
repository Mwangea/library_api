import pandas as pd
import os
import json
from datetime import datetime
from typing import Dict, Any, Optional, Tuple, List
from models import ConversationState
from config import EXCEL_PATH

class BookManager:
    def __init__(self, excel_path: str):
        self.excel_path = excel_path
    
    def load_sheet(self, sheet_name: str) -> pd.DataFrame:
        return pd.read_excel(self.excel_path, sheet_name=sheet_name)
    
    def save_sheet(self, sheet_name: str, df: pd.DataFrame):
        try:
            with pd.ExcelFile(self.excel_path) as xls:
                sheet_dict = {}
                for sheet in xls.sheet_names:
                    if sheet != sheet_name:
                        sheet_dict[sheet] = pd.read_excel(xls, sheet_name=sheet)
                
                sheet_dict[sheet_name] = df
                
                with pd.ExcelWriter(self.excel_path, engine='openpyxl') as writer:
                    for name, data in sheet_dict.items():
                        data.to_excel(writer, sheet_name=name, index=False)
                        
        except Exception as e:
            print(f"Error saving sheet {sheet_name}: {str(e)}")
            with pd.ExcelWriter(self.excel_path, engine='openpyxl', mode='a', if_sheet_exists='replace') as writer:
                df.to_excel(writer, sheet_name=sheet_name, index=False)
    
    def get_available_books(self) -> pd.DataFrame:
        return self.load_sheet('Books')
    
    def get_bookings(self) -> pd.DataFrame:
        try:
            return self.load_sheet('Bookings')
        except:
            empty_bookings = pd.DataFrame(columns=[
                'Booking ID', 'Name', 'Book Title', 'Phone Number', 
                'Duration (Days)', 'Date Booked'
            ])
            self.save_sheet('Bookings', empty_bookings)
            return empty_bookings
    
    def get_available_books_list(self) -> List[Dict[str, Any]]:
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
        
        exact_match = df[df["Title"].str.lower() == title.lower()]
        if not exact_match.empty:
            is_available = exact_match.iloc[0]["Available Copies"] > 0
            book_info = {
                'title': exact_match.iloc[0]['Title'],
                'author': exact_match.iloc[0].get('Author', 'Unknown'),
                'available': is_available,
                'copies': exact_match.iloc[0]['Available Copies']
            }
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
            return (bool(is_available), normalized_match.index[0], book_info)

        return (False, None, None)
    
    def reserve_book(self, name: str, title: str, phone: str, duration: int) -> Dict[str, Any]:
        books_df = self.get_available_books()
        bookings_df = self.get_bookings()
        
        book_match = books_df[books_df['Title'].str.lower() == title.lower()]
        if book_match.empty:
            raise Exception(f"Book '{title}' not found in database")
        
        idx = book_match.index[0]
        current_copies = books_df.at[idx, 'Available Copies']
        
        if current_copies <= 0:
            raise Exception(f"Book '{title}' is not available (0 copies)")
        
        books_df.at[idx, 'Available Copies'] = current_copies - 1

        new_booking_id = len(bookings_df) + 1 if len(bookings_df) > 0 else 1
        new_booking = {
            'Booking ID': new_booking_id,
            'Name': name,
            'Book Title': title,
            'Phone Number': phone,
            'Duration (Days)': duration,
            'Date Booked': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        
        new_booking_df = pd.DataFrame([new_booking])
        bookings_df = pd.concat([bookings_df, new_booking_df], ignore_index=True)

        try:
            self.save_sheet('Books', books_df)
            self.save_sheet('Bookings', bookings_df)
        except Exception as e:
            print(f"Error saving to Excel: {str(e)}")
            raise Exception(f"Failed to save booking: {str(e)}")

        return new_booking

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

class MessageParser:
    @staticmethod
    def extract_book_title_from_message(message: str) -> str:
        message_lower = message.lower()
        
        remove_phrases = [
            'i want to reserve', 'i want to borrow', 'i need', 'can i get', 
            'do you have', 'is available', 'check for', 'looking for',
            'i want', 'i would like', 'book called', 'book titled'
        ]
        
        cleaned_message = message_lower
        for phrase in remove_phrases:
            cleaned_message = cleaned_message.replace(phrase, '').strip()
        
        cleaned_message = cleaned_message.strip('"\'')
        return cleaned_message.strip()

    @staticmethod
    def parse_user_details(message: str) -> Optional[Dict[str, Any]]:
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

class ChatService:
    def __init__(self, ai_provider, book_manager: BookManager, conversation_manager: ConversationManager):
        self.ai_provider = ai_provider
        self.book_manager = book_manager
        self.conversation_manager = conversation_manager
    
    def get_system_prompt(self, conversation_context: Dict[str, Any]) -> str:
        available_books = self.book_manager.get_available_books_list()
        
        base_prompt = f"""
You are a professional library booking assistant. Your role is to ONLY help users with library-related tasks:
- Checking book availability
- Taking user details for booking
- Confirming bookings
- Providing information about reservations

❌ You must NOT answer unrelated questions (e.g. general knowledge, jokes, history, programming, etc).
✅ If a user asks something outside the scope, politely say: "Sorry, I can only help with library book reservations."

CURRENT CONTEXT:
{json.dumps(conversation_context, indent=2)}

AVAILABLE BOOKS:
{json.dumps(available_books, indent=2)}

RESPONSE GUIDELINES:
- Be friendly, professional, and conversational
- Use emojis appropriately (📚 for books, ✅ for confirmation)
- Always guide users through the process step by step
- If book is unavailable, suggest alternatives
- For user details, specify the exact format needed
- Always confirm booking details before finalizing
"""
        return base_prompt
    
    def process_message(self, message: str, user_id: str) -> str:
        self.conversation_manager.initialize_user(user_id)
        state = self.conversation_manager.get_state(user_id)
        current_data = self.conversation_manager.get_user_data(user_id)
        
        context = {
            "current_state": state.name,
            "user_data": dict(current_data),
            "last_message": message
        }
        
        action_result = None
        
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
                    action_result = f"BOOK_FOUND: {book_info['title']} by {book_info['author']} is available"
                else:
                    action_result = f"BOOK_NOT_FOUND: '{potential_title}' is not available"
        
        elif state == ConversationState.AWAITING_USER_DETAILS:
            details = MessageParser.parse_user_details(message)
            if details:
                self.conversation_manager.update_user_data(user_id, details)
                self.conversation_manager.set_state(user_id, ConversationState.CONFIRMATION)
                action_result = f"DETAILS_RECEIVED: {details}"
        
        elif state == ConversationState.CONFIRMATION:
            if message.lower() in ['confirm', 'yes', 'y', 'ok', 'sure', 'proceed']:
                try:
                    user_data = self.conversation_manager.get_user_data(user_id)
                    
                    required_fields = ['name', 'book_title', 'phone', 'duration']
                    missing_fields = [field for field in required_fields if field not in user_data]
                    
                    if missing_fields:
                        action_result = f"BOOKING_ERROR: Missing fields: {missing_fields}"
                    else:
                        booking = self.book_manager.reserve_book(
                            user_data['name'],
                            user_data['book_title'], 
                            user_data['phone'],
                            user_data['duration']
                        )
                        
                        self.conversation_manager.reset_user(user_id)
                        action_result = f"BOOKING_CONFIRMED: {json.dumps(booking)}"
                        
                except Exception as e:
                    action_result = f"BOOKING_ERROR: {str(e)}"
            
            elif message.lower() in ['cancel', 'no', 'n', 'abort']:
                self.conversation_manager.reset_user(user_id)
                action_result = "BOOKING_CANCELLED"
        
        if action_result:
            context["action_result"] = str(action_result)
        
        try:
            json_safe_context = json.dumps(context, indent=2, default=str)
            system_prompt = self.get_system_prompt(json_safe_context)
            response_text = self.ai_provider.generate_response(system_prompt, message)
            return response_text
        
        except Exception as e:
            print(f"AI API Error: {str(e)}")
            return "Sorry, I'm having trouble processing your request. Please try again."