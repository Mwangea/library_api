from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from models import BookingRequest, BookQuery, ChatMessage
from services import BookManager, ChatService, ConversationManager
from providers import AIProviderFactory
from config import EXCEL_PATH, AI_PROVIDER_NAME
import os
from datetime import datetime

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize services
ai_provider = AIProviderFactory.create_provider(AI_PROVIDER_NAME)
ai_provider.initialize(os.getenv(f"{AI_PROVIDER_NAME.upper()}_API_KEY"))

book_manager = BookManager(EXCEL_PATH)
conversation_manager = ConversationManager()
chat_service = ChatService(ai_provider, book_manager, conversation_manager)

# Routes
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