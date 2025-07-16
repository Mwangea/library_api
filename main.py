from fastapi import FastAPI, HTTPException, Body
from pydantic import BaseModel, EmailStr
from datetime import datetime, date
import pandas as pd
import os
import json
import re
from enum import Enum
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Tuple, List, Union
from pathlib import Path

# === CONFIG ===
load_dotenv()
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

EXCEL_PATH = os.path.abspath("hotel_db.xlsx")
CONVERSATION_STATE_FILE = os.path.abspath("conversation_states.json")
print(f"Excel file path: {EXCEL_PATH}")

# === MODELS ===
class RoomType(str, Enum):
    STANDARD = "standard"
    DELUXE = "deluxe"
    SUITE = "suite"

class BookingRequest(BaseModel):
    customer_name: str
    customer_age: int
    room_type: RoomType
    check_in: date
    check_out: date
    meal_plan: str
    special_requests: Optional[str] = None
    phone: str
    email: str
    guests: Optional[List[Dict[str, Union[str, int]]]] = None

class RoomQuery(BaseModel):
    check_in: date
    check_out: date
    room_type: Optional[RoomType] = None

class ChatMessage(BaseModel):
    message: str
    user_id: str = "default"

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
    AWAITING_DATES = 2
    AWAITING_ROOM_TYPE = 3
    AWAITING_GUEST_DETAILS = 4
    AWAITING_MEAL_PLAN = 5
    AWAITING_CONTACT_INFO = 6
    CONFIRMATION = 7

class ConversationManager:
    def __init__(self, state_file: str):
        self.state_file = state_file
        self.conversation_state: Dict[str, ConversationState] = {}
        self.user_data: Dict[str, Dict[str, Any]] = {}
        self.load_state()
    
    def load_state(self):
        """Load conversation state from file"""
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, 'r') as f:
                    data = json.load(f)
                    # Convert state strings back to enums
                    for user_id, state_name in data.get('conversation_state', {}).items():
                        try:
                            self.conversation_state[user_id] = ConversationState[state_name]
                        except KeyError:
                            self.conversation_state[user_id] = ConversationState.INITIAL
                    
                    self.user_data = data.get('user_data', {})
                    
                    # Clean up old sessions (older than 24 hours)
                    self._cleanup_old_sessions()
        except Exception as e:
            print(f"Error loading conversation state: {e}")
            self.conversation_state = {}
            self.user_data = {}
    
    def save_state(self):
        """Save conversation state to file"""
        try:
            data = {
                'conversation_state': {user_id: state.name for user_id, state in self.conversation_state.items()},
                'user_data': self.user_data,
                'last_updated': datetime.now().isoformat()
            }
            with open(self.state_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Error saving conversation state: {e}")
    
    def _cleanup_old_sessions(self):
        """Remove sessions older than 24 hours"""
        current_time = datetime.now()
        users_to_remove = []
        
        for user_id, data in self.user_data.items():
            last_activity = data.get('last_activity')
            if last_activity:
                try:
                    last_time = datetime.fromisoformat(last_activity)
                    if (current_time - last_time).total_seconds() > 86400:  # 24 hours
                        users_to_remove.append(user_id)
                except:
                    users_to_remove.append(user_id)
        
        for user_id in users_to_remove:
            self.conversation_state.pop(user_id, None)
            self.user_data.pop(user_id, None)
    
    def initialize_user(self, user_id: str):
        if user_id not in self.conversation_state:
            self.conversation_state[user_id] = ConversationState.INITIAL
            self.user_data[user_id] = {'last_activity': datetime.now().isoformat()}
        else:
            # Update last activity
            if user_id not in self.user_data:
                self.user_data[user_id] = {}
            self.user_data[user_id]['last_activity'] = datetime.now().isoformat()
        
        self.save_state()
    
    def get_state(self, user_id: str) -> ConversationState:
        return self.conversation_state.get(user_id, ConversationState.INITIAL)
    
    def set_state(self, user_id: str, state: ConversationState):
        self.conversation_state[user_id] = state
        self.save_state()
    
    def get_user_data(self, user_id: str) -> Dict[str, Any]:
        return self.user_data.get(user_id, {})
    
    def update_user_data(self, user_id: str, data: Dict[str, Any]):
        if user_id not in self.user_data:
            self.user_data[user_id] = {}
        self.user_data[user_id].update(data)
        self.user_data[user_id]['last_activity'] = datetime.now().isoformat()
        self.save_state()
    
    def reset_user(self, user_id: str):
        self.conversation_state.pop(user_id, None)
        self.user_data.pop(user_id, None)
        self.save_state()

# === HOTEL MANAGEMENT ===
class HotelManager:
    def __init__(self, excel_path: str):
        self.excel_path = excel_path
        self._initialize_database()
    
    def _initialize_database(self):
        if not Path(self.excel_path).exists():
            with pd.ExcelWriter(self.excel_path, engine='openpyxl') as writer:
                rooms_data = {
                    'room_id': [1, 2, 3],
                    'room_type': ['standard', 'deluxe', 'suite'],
                    'price_per_night': [100, 150, 250],
                    'max_occupancy': [2, 3, 4],
                    'total_rooms': [10, 5, 3],
                    'available_rooms': [10, 5, 3]
                }
                pd.DataFrame(rooms_data).to_excel(writer, sheet_name='Rooms', index=False)
                
                bookings_data = {
                    'booking_id': [],
                    'customer_name': [],
                    'customer_age': [],
                    'room_type': [],
                    'check_in': [],
                    'check_out': [],
                    'length_of_stay': [],
                    'meal_plan': [],
                    'special_requests': [],
                    'booking_date': [],
                    'total_price': [],
                    'status': [],
                    'guests': []
                }
                pd.DataFrame(bookings_data).to_excel(writer, sheet_name='Bookings', index=False)
                
                customers_data = {
                    'customer_id': [],
                    'name': [],
                    'age': [],
                    'phone': [],
                    'email': [],
                    'loyalty_points': []
                }
                pd.DataFrame(customers_data).to_excel(writer, sheet_name='Customers', index=False)

    def load_sheet(self, sheet_name: str) -> pd.DataFrame:
        try:
            df = pd.read_excel(self.excel_path, sheet_name=sheet_name)
            # Ensure all string columns are properly converted
            str_columns = ['room_type', 'customer_name', 'meal_plan', 'status', 'name', 'phone', 'email', 'guests']
            for col in str_columns:
                if col in df.columns:
                    df[col] = df[col].astype(str)
            return df.dropna(how='all')
        except Exception as e:
            raise ValueError(f"Error loading sheet {sheet_name}: {str(e)}")

    def save_sheet(self, sheet_name: str, df: pd.DataFrame):
        try:
            with pd.ExcelFile(self.excel_path) as xls:
                sheets = {sheet: pd.read_excel(xls, sheet_name=sheet) 
                         for sheet in xls.sheet_names if sheet != sheet_name}
            sheets[sheet_name] = df
            
            with pd.ExcelWriter(self.excel_path, engine='openpyxl') as writer:
                for name, data in sheets.items():
                    data.to_excel(writer, sheet_name=name, index=False)
        except Exception as e:
            raise ValueError(f"Error saving sheet {sheet_name}: {str(e)}")

    def get_available_rooms(self) -> pd.DataFrame:
        return self.load_sheet('Rooms')
    
    def get_bookings(self) -> pd.DataFrame:
        return self.load_sheet('Bookings')
    
    def get_customers(self) -> pd.DataFrame:
        return self.load_sheet('Customers')
    
    def get_available_rooms_list(self) -> list:
        df = self.get_available_rooms()
        available_rooms = []
        for _, row in df.iterrows():
            available_rooms.append({
                'room_type': str(row['room_type']),
                'price_per_night': float(row['price_per_night']),
                'max_occupancy': int(row['max_occupancy'])
            })
        return available_rooms
    
    def check_room_availability(self, check_in: date, check_out: date, room_type: Optional[str] = None) -> Tuple[bool, Optional[List[Dict[str, Any]]]]:
        if check_in < date.today():
            raise ValueError("Check-in date cannot be in the past")
        if check_out <= check_in:
            raise ValueError("Check-out date must be after check-in")

        rooms_df = self.get_available_rooms()
        bookings_df = self.get_bookings()
        
        # Ensure all string comparisons are done with strings
        room_type = str(room_type).lower() if room_type is not None else None
        
        if room_type:
            rooms_df = rooms_df[rooms_df['room_type'].astype(str).str.lower() == room_type]
        
        available_rooms = []
        
        for _, room in rooms_df.iterrows():
            room_type_str = str(room['room_type']).lower()
            
            # Convert all relevant columns to strings for comparison
            room_bookings = bookings_df[
                (bookings_df['room_type'].astype(str).str.lower() == room_type_str) &
                (bookings_df['status'].astype(str).str.lower() != 'cancelled') &
                (pd.to_datetime(bookings_df['check_out'].astype(str)) > pd.to_datetime(check_in)) &
                (pd.to_datetime(bookings_df['check_in'].astype(str)) < pd.to_datetime(check_out))
            ]
            
            booked_count = len(room_bookings)
            available = max(0, int(room['available_rooms']) - booked_count)
            
            if available > 0:
                available_rooms.append({
                    'room_type': str(room['room_type']),
                    'price_per_night': float(room['price_per_night']),
                    'max_occupancy': int(room['max_occupancy'])
                })
        
        return bool(available_rooms), available_rooms
    
    def create_booking(self, booking_data: Dict) -> Dict[str, Any]:
        available, _ = self.check_room_availability(
            booking_data['check_in'],
            booking_data['check_out'],
            booking_data['room_type']
        )
        
        if not available:
            raise ValueError("No available rooms for selected dates and type")

        bookings_df = self.get_bookings()
        new_id = bookings_df['booking_id'].max() + 1 if not bookings_df.empty else 1
        
        length_of_stay = (booking_data['check_out'] - booking_data['check_in']).days
        rooms_df = self.get_available_rooms()
        
        # Ensure room_type comparison is done with strings
        room_info = rooms_df[
            rooms_df['room_type'].astype(str).str.lower() == str(booking_data['room_type']).lower()
        ].iloc[0]
        
        base_price = float(room_info['price_per_night'])
        
        meal_prices = {
            'breakfast': 15,
            'half_board': 30,
            'full_board': 50,
            'all_inclusive': 75
        }
        
        meal_price = meal_prices.get(str(booking_data['meal_plan']).lower(), 0)
        total_price = (base_price + meal_price) * length_of_stay
        
        # Calculate loyalty points (1 point per $10 spent)
        loyalty_points = int(total_price // 10)
        
        # Update available rooms count
        rooms_df.loc[
            rooms_df['room_type'].astype(str).str.lower() == str(booking_data['room_type']).lower(), 
            'available_rooms'
        ] -= 1
        self.save_sheet('Rooms', rooms_df)
        
        # Update or create customer record
        customers_df = self.get_customers()
        customer_id = customers_df['customer_id'].max() + 1 if not customers_df.empty else 1
        
        # Check if customer already exists
        existing_customer = customers_df[
            (customers_df['name'].astype(str).str.lower() == str(booking_data['customer_name']).lower()) &
            (customers_df['email'].astype(str).str.lower() == str(booking_data.get('email', '')).lower())
        ]
        
        if not existing_customer.empty:
            # Update existing customer
            customer_id = existing_customer.iloc[0]['customer_id']
            customers_df.loc[customers_df['customer_id'] == customer_id, 'loyalty_points'] += loyalty_points
        else:
            # Create new customer
            new_customer = {
                'customer_id': customer_id,
                'name': str(booking_data['customer_name']),
                'age': int(booking_data['customer_age']),
                'phone': str(booking_data.get('phone', '')),
                'email': str(booking_data.get('email', '')),
                'loyalty_points': loyalty_points
            }
            customers_df = pd.concat([customers_df, pd.DataFrame([new_customer])], ignore_index=True)
        
        self.save_sheet('Customers', customers_df)
        
        # Prepare guests information
        guests = booking_data.get('guests', [])
        if not guests:
            # If no guests provided, use primary customer as the only guest
            guests = [{
                'name': booking_data['customer_name'],
                'age': booking_data['customer_age']
            }]
        
        new_booking = {
            'booking_id': new_id,
            'customer_name': str(booking_data['customer_name']),
            'customer_age': int(booking_data['customer_age']),
            'room_type': str(booking_data['room_type']),
            'check_in': booking_data['check_in'].strftime('%Y-%m-%d'),
            'check_out': booking_data['check_out'].strftime('%Y-%m-%d'),
            'length_of_stay': length_of_stay,
            'meal_plan': str(booking_data['meal_plan']),
            'special_requests': str(booking_data.get('special_requests', '')),
            'booking_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'total_price': float(total_price),
            'status': 'confirmed',
            'guests': json.dumps(guests)  # Store guests as JSON string
        }
        
        bookings_df = pd.concat([bookings_df, pd.DataFrame([new_booking])], ignore_index=True)
        self.save_sheet('Bookings', bookings_df)
        
        # Prepare confirmation message with all guests
        guests_list = "\n".join([f"- {guest['name']} ({guest['age']} years)" for guest in guests])
        
        return {
            **new_booking,
            'confirmation_message': f"Thank you for booking with us, {booking_data['customer_name']}!\n\n"
                                  f"📅 Your {booking_data['room_type']} room is confirmed from "
                                  f"{booking_data['check_in']} to {booking_data['check_out']}.\n"
                                  f"👥 Guests:\n{guests_list}\n"
                                  f"🛏️ Max occupancy: {int(room_info['max_occupancy'])} guests\n"
                                  f"🍽️ Meal plan: {booking_data['meal_plan']}\n"
                                  f"💰 Total amount: ${total_price:.2f}\n\n"
                                  f"Please arrive by 3 PM on your check-in date.\n"
                                  f"You've earned {loyalty_points} loyalty points!"
        }

# === UTILITIES ===
class MessageParser:
    @staticmethod
    def extract_dates_from_message(message: str) -> Optional[Tuple[date, date]]:
        try:
            # Handle "from X to Y" format
            if " to " in message:
                parts = message.split(" to ")
                check_in = MessageParser._parse_single_date(parts[0].strip())
                check_out = MessageParser._parse_single_date(parts[1].strip())
                if check_in and check_out:
                    return (check_in, check_out)
            
            # Look for date patterns
            date_patterns = [
                r"\b\d{4}-\d{2}-\d{2}\b",
                r"\b\d{1,2}/\d{1,2}/\d{4}\b",
                r"\b\d{1,2}-\d{1,2}-\d{4}\b"
            ]
            
            dates = []
            for pattern in date_patterns:
                matches = re.findall(pattern, message)
                for match in matches:
                    parsed_date = MessageParser._parse_single_date(match)
                    if parsed_date:
                        dates.append(parsed_date)
                        
            if len(dates) >= 2:
                return (dates[0], dates[1])
                
        except Exception as e:
            print(f"Date parsing error: {e}")
        
        return None

    @staticmethod
    def _parse_single_date(date_str: str) -> Optional[date]:
        """Parse a single date string into a date object"""
        date_formats = [
            "%Y-%m-%d",
            "%m/%d/%Y",
            "%d/%m/%Y",
            "%m-%d-%Y",
            "%d-%m-%Y"
        ]
        
        for fmt in date_formats:
            try:
                return datetime.strptime(date_str, fmt).date()
            except ValueError:
                continue
        return None

    @staticmethod
    def extract_room_type_from_message(message: str) -> Optional[str]:
        message_lower = message.lower()
        room_types = ['standard', 'deluxe', 'suite']
        
        for room_type in room_types:
            if room_type in message_lower:
                return room_type
        
        return None

    @staticmethod
    def parse_guest_details(message: str) -> Optional[Dict[str, Any]]:
        try:
            # Try to extract multiple guests pattern like "Musa Mwangea (23) and Amina Njeri (22)"
            guests_pattern = r'([A-Za-z\s]+)\s*\((\d+)\)(?:\s*and\s*([A-Za-z\s]+)\s*\((\d+)\))?'
            guests_match = re.search(guests_pattern, message)
            
            if guests_match:
                guests = []
                # First guest
                guests.append({
                    'name': guests_match.group(1).strip(),
                    'age': int(guests_match.group(2))
                })
                # Second guest if exists
                if guests_match.group(3) and guests_match.group(4):
                    guests.append({
                        'name': guests_match.group(3).strip(),
                        'age': int(guests_match.group(4))
                    })
                
                return {
                    'name': guests[0]['name'],  # Primary guest
                    'age': guests[0]['age'],    # Primary guest age
                    'guests': guests            # All guests including primary
                }

            # Fall back to single guest pattern
            # Try to extract name from patterns like "It'll just be me — Musa Mwangea"
            name_match = re.search(r"(?:It'?s|It will|I'?m|It'll just be me)\s*[—\-]\s*([A-Za-z\s]+)", message, re.IGNORECASE)
            if name_match:
                name = name_match.group(1).strip()
            else:
                # Fall back to comma-separated format
                parts = [x.strip() for x in message.split(',')]
                if len(parts) >= 1:
                    name = parts[0]
                else:
                    return None

            # Look for age (number)
            age_match = re.search(r'\b(\d{1,3})\b', message)
            age = int(age_match.group(1)) if age_match else None
            
            if name and age:
                return {
                    'name': name,
                    'age': age,
                    'guests': [{'name': name, 'age': age}]  # Single guest as list
                }
        except Exception as e:
            print(f"Error parsing guest details: {e}")
        
        return None

    @staticmethod
    def extract_meal_plan(message: str) -> Optional[str]:
        message_lower = message.lower()
        meal_plans = ['breakfast', 'half_board', 'full_board', 'all_inclusive']
        
        for plan in meal_plans:
            if plan in message_lower or plan.replace('_', ' ') in message_lower:
                return plan
        
        return None

    @staticmethod
    def parse_contact_info(message: str) -> Optional[Dict[str, Any]]:
        try:
            # Extract phone number
            phone_match = re.search(r'(\+?\d[\d\s\-\(\)]{7,}\d)', message)
            phone = phone_match.group(1).strip() if phone_match else None
            
            # Extract email
            email_match = re.search(r'([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)', message)
            email = email_match.group(1).strip() if email_match else None
            
            if phone or email:
                return {
                    'phone': phone or '',
                    'email': email or ''
                }
        except Exception as e:
            print(f"Error parsing contact info: {e}")
        
        return None

    @staticmethod
    def is_thank_you(message: str) -> bool:
        """Check if the message is a thank you message"""
        thank_you_phrases = [
            'thank you', 'thanks', 'appreciate it', 'much obliged', 
            'thank you very much', 'thanks a lot', 'cheers'
        ]
        message_lower = message.lower()
        return any(phrase in message_lower for phrase in thank_you_phrases)

    @staticmethod
    def is_new_booking_request(message: str) -> bool:
        """Check if the message is requesting a new booking"""
        new_booking_phrases = [
            'new booking', 'book again', 'another reservation', 
            'make another booking', 'book another'
        ]
        message_lower = message.lower()
        return any(phrase in message_lower for phrase in new_booking_phrases)

    @staticmethod
    def is_confirmation(message: str) -> bool:
        """Check if the message is confirming the booking"""
        confirm_phrases = ['yes', 'confirm', 'y', 'ok', 'sure', 'proceed', 'book', 'book it']
        message_lower = message.lower()
        return any(phrase in message_lower for phrase in confirm_phrases)

    @staticmethod
    def is_cancellation(message: str) -> bool:
        """Check if the message is cancelling the booking"""
        cancel_phrases = ['no', 'cancel', 'n', 'abort', 'stop']
        message_lower = message.lower()
        return any(phrase in message_lower for phrase in cancel_phrases)

# === CHAT SERVICE ===
class ChatService:
    def __init__(self, ai_provider: AIProvider, hotel_manager: HotelManager, conversation_manager: ConversationManager):
        self.ai_provider = ai_provider
        self.hotel_manager = hotel_manager
        self.conversation_manager = conversation_manager
    
    def get_system_prompt(self, conversation_context: Dict[str, Any]) -> str:
        available_rooms = self.hotel_manager.get_available_rooms_list()
        state = conversation_context.get('current_state', 'INITIAL')
        user_data = conversation_context.get('user_data', {})
        
        prompt = f"""
You are a professional hotel booking assistant. Your role is to ONLY help users with hotel-related tasks.

IMPORTANT RULES:
1. NEVER disclose specific numbers of available rooms - just say "we have availability" or "we're fully booked"
2. Guide users through the booking process step by step without repeating questions
3. Never answer unrelated questions
4. Be conversational and helpful
5. If user says "thank you", respond with a simple "You're welcome!"
6. If user asks to make another booking, reset the conversation and start over
7. If user provides multiple pieces of information at once (dates, room type, meal plan), accept all and move to next step

Current conversation stage: {state}
Current user data: {json.dumps(user_data, default=str)}

ROOM TYPES:
- Standard: $100/night (max 2 guests)
- Deluxe: $150/night (max 3 guests) 
- Suite: $250/night (max 4 guests)

MEAL PLANS:
- breakfast (+$15/night)
- half_board (+$30/night) 
- full_board (+$50/night)
- all_inclusive (+$75/night)

CONVERSATION FLOW:
1. INITIAL: Ask for check-in/out dates (format: YYYY-MM-DD)
2. AWAITING_DATES: Once dates received, confirm and ask for room type preference
3. AWAITING_ROOM_TYPE: Once room type selected, ask for guest details (Name, Age)
4. AWAITING_GUEST_DETAILS: Once guest details received, ask for meal plan
5. AWAITING_MEAL_PLAN: Once meal plan received, ask for contact information (phone and email)
6. AWAITING_CONTACT_INFO: Once contact info received, summarize booking and ask for confirmation
7. CONFIRMATION: Complete booking or cancel
"""
        if state == "AWAITING_GUEST_DETAILS":
            prompt += "\nCURRENT TASK: Ask for guest details in this format: Full Name (Age) and Another Name (Age) if multiple guests"
        elif state == "AWAITING_MEAL_PLAN":
            prompt += "\nCURRENT TASK: Ask for meal plan preference (breakfast, half_board, full_board, all_inclusive)"
        elif state == "AWAITING_CONTACT_INFO":
            prompt += "\nCURRENT TASK: Ask for contact information (phone number and email)"
        elif state == "CONFIRMATION":
            prompt += "\nCURRENT TASK: Summarize the booking details and ask for confirmation"
        
        return prompt
    
    def process_message(self, message: str, user_id: str) -> str:
        self.conversation_manager.initialize_user(user_id)
        state = self.conversation_manager.get_state(user_id)
        current_data = self.conversation_manager.get_user_data(user_id)
        
        print(f"DEBUG: User {user_id}, State: {state}, Data: {current_data}")
        
        # Check for thank you messages
        if MessageParser.is_thank_you(message):
            return "You're welcome! Is there anything else I can help you with?"
        
        # Check for new booking requests
        if MessageParser.is_new_booking_request(message):
            self.conversation_manager.reset_user(user_id)
            return "Great! Let's start a new booking. When would you like to check in and check out?"
        
        context = {
            "current_state": state.name,
            "user_data": dict(current_data),
            "last_message": message
        }
        
        action_result = None
        
        try:
            if state == ConversationState.INITIAL:
                dates = MessageParser.extract_dates_from_message(message)
                if dates:
                    check_in, check_out = dates
                    try:
                        available, rooms_info = self.hotel_manager.check_room_availability(check_in, check_out)
                        if available:
                            self.conversation_manager.set_state(user_id, ConversationState.AWAITING_ROOM_TYPE)
                            self.conversation_manager.update_user_data(user_id, {
                                'check_in': check_in.strftime('%Y-%m-%d'),
                                'check_out': check_out.strftime('%Y-%m-%d'),
                                'available_rooms': rooms_info
                            })
                            action_result = "DATES_ACCEPTED"
                        else:
                            action_result = "NO_ROOMS_AVAILABLE"
                    except ValueError as e:
                        action_result = f"DATE_ERROR: {str(e)}"
        
            elif state == ConversationState.AWAITING_ROOM_TYPE:
                room_type = MessageParser.extract_room_type_from_message(message)
                if room_type:
                    user_data = self.conversation_manager.get_user_data(user_id)
                    available_rooms = user_data.get('available_rooms', [])
                    
                    selected_room = next((room for room in available_rooms 
                                        if room['room_type'].lower() == room_type.lower()), None)
                    
                    if selected_room:
                        self.conversation_manager.set_state(user_id, ConversationState.AWAITING_GUEST_DETAILS)
                        self.conversation_manager.update_user_data(user_id, {
                            'room_type': selected_room['room_type'],
                            'price_per_night': selected_room['price_per_night'],
                            'max_occupancy': selected_room['max_occupancy']
                        })
                        action_result = "ROOM_SELECTED"
                    else:
                        action_result = "INVALID_ROOM_TYPE"
        
            elif state == ConversationState.AWAITING_GUEST_DETAILS:
                details = MessageParser.parse_guest_details(message)
                if details:
                    self.conversation_manager.update_user_data(user_id, details)
                    self.conversation_manager.set_state(user_id, ConversationState.AWAITING_MEAL_PLAN)
                    action_result = "GUEST_DETAILS_RECEIVED"
                else:
                    action_result = "INVALID_GUEST_DETAILS_FORMAT"
            
            elif state == ConversationState.AWAITING_MEAL_PLAN:
                meal_plan = MessageParser.extract_meal_plan(message)
                if meal_plan:
                    self.conversation_manager.update_user_data(user_id, {'meal_plan': meal_plan})
                    self.conversation_manager.set_state(user_id, ConversationState.AWAITING_CONTACT_INFO)
                    action_result = "MEAL_PLAN_RECEIVED"
                else:
                    action_result = "INVALID_MEAL_PLAN"
            
            elif state == ConversationState.AWAITING_CONTACT_INFO:
                contact_info = MessageParser.parse_contact_info(message)
                if contact_info:
                    self.conversation_manager.update_user_data(user_id, contact_info)
                    self.conversation_manager.set_state(user_id, ConversationState.CONFIRMATION)
                    action_result = "CONTACT_INFO_RECEIVED"
                else:
                    action_result = "INVALID_CONTACT_FORMAT"
        
            elif state == ConversationState.CONFIRMATION:
                if MessageParser.is_confirmation(message):
                    try:
                        user_data = self.conversation_manager.get_user_data(user_id)
                        booking = self.hotel_manager.create_booking({
                            'customer_name': user_data['name'],
                            'customer_age': user_data['age'],
                            'room_type': user_data['room_type'],
                            'check_in': datetime.strptime(user_data['check_in'], '%Y-%m-%d').date(),
                            'check_out': datetime.strptime(user_data['check_out'], '%Y-%m-%d').date(),
                            'meal_plan': user_data['meal_plan'],
                            'special_requests': user_data.get('special_requests', ''),
                            'phone': user_data.get('phone', ''),
                            'email': user_data.get('email', ''),
                            'guests': user_data.get('guests', [])
                        })
                        self.conversation_manager.reset_user(user_id)
                        action_result = f"BOOKING_CONFIRMED: {booking['booking_id']}"
                        return booking['confirmation_message']
                    except Exception as e:
                        action_result = f"BOOKING_ERROR: {str(e)}"
                        return f"Sorry, we encountered an error processing your booking: {str(e)}"
                elif MessageParser.is_cancellation(message):
                    self.conversation_manager.reset_user(user_id)
                    action_result = "BOOKING_CANCELLED"
                    return "Your booking has been cancelled. Let us know if you'd like to book another time."
            
            # Handle combined inputs (e.g., "2024-12-25 to 2024-12-28 standard full board")
            if state == ConversationState.INITIAL or state == ConversationState.AWAITING_DATES:
                # Try to extract all information at once
                dates = MessageParser.extract_dates_from_message(message)
                if dates:
                    check_in, check_out = dates
                    try:
                        available, rooms_info = self.hotel_manager.check_room_availability(check_in, check_out)
                        if available:
                            self.conversation_manager.update_user_data(user_id, {
                                'check_in': check_in.strftime('%Y-%m-%d'),
                                'check_out': check_out.strftime('%Y-%m-%d'),
                                'available_rooms': rooms_info
                            })
                            
                            room_type = MessageParser.extract_room_type_from_message(message)
                            if room_type:
                                selected_room = next((room for room in rooms_info 
                                                    if room['room_type'].lower() == room_type.lower()), None)
                                if selected_room:
                                    self.conversation_manager.update_user_data(user_id, {
                                        'room_type': selected_room['room_type'],
                                        'price_per_night': selected_room['price_per_night'],
                                        'max_occupancy': selected_room['max_occupancy']
                                    })
                                    action_result = "ROOM_SELECTED"
                                    
                                    meal_plan = MessageParser.extract_meal_plan(message)
                                    if meal_plan:
                                        self.conversation_manager.update_user_data(user_id, {'meal_plan': meal_plan})
                                        action_result = "MEAL_PLAN_RECEIVED"
                                        self.conversation_manager.set_state(user_id, ConversationState.AWAITING_GUEST_DETAILS)
                                    else:
                                        self.conversation_manager.set_state(user_id, ConversationState.AWAITING_GUEST_DETAILS)
                                else:
                                    self.conversation_manager.set_state(user_id, ConversationState.AWAITING_ROOM_TYPE)
                            else:
                                self.conversation_manager.set_state(user_id, ConversationState.AWAITING_ROOM_TYPE)
                        else:
                            action_result = "NO_ROOMS_AVAILABLE"
                    except ValueError as e:
                        action_result = f"DATE_ERROR: {str(e)}"
            
            if action_result:
                context["action_result"] = str(action_result)
                print(f"DEBUG: Action result: {action_result}")
            
            try:
                system_prompt = self.get_system_prompt(context)
                response_text = self.ai_provider.generate_response(system_prompt, message)
                return response_text
            
            except Exception as e:
                print(f"AI API Error: {str(e)}")
                return "Sorry, I'm having trouble processing your request. Please try again or contact support."
                
        except Exception as e:
            print(f"Error processing message: {str(e)}")
            return "Sorry, something went wrong. Please try again."

# === INITIALIZE SERVICES ===
AI_PROVIDER_NAME = os.getenv("AI_PROVIDER", "gemini")
ai_provider = AIProviderFactory.create_provider(AI_PROVIDER_NAME)
ai_provider.initialize(os.getenv(f"{AI_PROVIDER_NAME.upper()}_API_KEY"))

hotel_manager = HotelManager(EXCEL_PATH)
conversation_manager = ConversationManager(CONVERSATION_STATE_FILE)
chat_service = ChatService(ai_provider, hotel_manager, conversation_manager)

# === ROUTES ===
@app.get("/debug-conversation/{user_id}")
def debug_conversation(user_id: str):
    state = conversation_manager.get_state(user_id)
    data = conversation_manager.get_user_data(user_id)
    return {
        "user_id": user_id,
        "state": state.name,
        "data": data
    }

@app.post("/reset-conversation")
def reset_conversation(payload: dict):
    user_id = payload.get("user_id", "default")
    conversation_manager.reset_user(user_id)
    return {"message": f"Conversation reset for user {user_id}"}

@app.get("/debug-rooms")
def debug_rooms():
    df = hotel_manager.get_available_rooms()
    rooms_list = []
    for _, row in df.iterrows():
        rooms_list.append({
            "room_id": int(row["room_id"]),
            "room_type": str(row["room_type"]),
            "price_per_night": float(row["price_per_night"]),
            "max_occupancy": int(row["max_occupancy"]),
            "total_rooms": int(row["total_rooms"]),
            "available_rooms": int(row["available_rooms"])
        })
    return {"rooms": rooms_list}

@app.get("/debug-bookings")
def debug_bookings():
    try:
        df = hotel_manager.get_bookings()
        bookings_list = []
        for _, row in df.iterrows():
            guests = json.loads(row["guests"]) if row["guests"] and row["guests"] != 'nan' else []
            bookings_list.append({
                "booking_id": int(row["booking_id"]),
                "customer_name": str(row["customer_name"]),
                "room_type": str(row["room_type"]),
                "check_in": str(row["check_in"]),
                "check_out": str(row["check_out"]),
                "length_of_stay": int(row["length_of_stay"]),
                "total_price": float(row["total_price"]),
                "status": str(row["status"]),
                "guests": guests
            })
        return {"bookings": bookings_list}
    except Exception as e:
        return {"error": str(e), "bookings": []}

@app.get("/debug-customers")
def debug_customers():
    try:
        df = hotel_manager.get_customers()
        customers_list = []
        for _, row in df.iterrows():
            customers_list.append({
                "customer_id": int(row["customer_id"]),
                "name": str(row["name"]),
                "age": int(row["age"]),
                "phone": str(row["phone"]),
                "email": str(row["email"]),
                "loyalty_points": int(row["loyalty_points"])
            })
        return {"customers": customers_list}
    except Exception as e:
        return {"error": str(e), "customers": []}

@app.post("/check-availability")
def check_availability(query: RoomQuery):
    available, rooms_info = hotel_manager.check_room_availability(query.check_in, query.check_out, query.room_type.value if query.room_type else None)
    return {
        "available": bool(available),
        "check_in": query.check_in,
        "check_out": query.check_out,
        "room_type": query.room_type,
        "available_rooms": rooms_info
    }

@app.post("/create-booking")
def create_booking(payload: BookingRequest):
    available, _ = hotel_manager.check_room_availability(
        payload.check_in,
        payload.check_out,
        payload.room_type.value
    )
    if not available:
        raise HTTPException(status_code=400, detail="Room not available for selected dates")

    booking = hotel_manager.create_booking({
        'customer_name': payload.customer_name,
        'customer_age': payload.customer_age,
        'room_type': payload.room_type.value,
        'check_in': payload.check_in,
        'check_out': payload.check_out,
        'meal_plan': payload.meal_plan,
        'special_requests': payload.special_requests,
        'phone': payload.phone,
        'email': payload.email,
        'guests': payload.guests
    })
    return {
        "message": "✅ Booking Confirmed",
        "booking": booking
    }

@app.post("/chat")
def chat_with_assistant(payload: ChatMessage):
    reply = chat_service.process_message(payload.message, payload.user_id)
    return {"reply": reply}

@app.get("/")
def root():
    return {"message": "Hotel Booking API is running!"}

@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "ai_provider": AI_PROVIDER_NAME
    }