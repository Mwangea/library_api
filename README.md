# Library Booking API

A FastAPI-based backend for managing library book reservations, availability, and conversational AI assistance. This project enables users to check book availability, reserve books, and interact with an AI-powered assistant for library-related queries.

## Features
- **Book Availability:** Check if a book is available in the library.
- **Book Reservation:** Reserve books by providing user details.
- **Booking Management:** View all current bookings.
- **Conversational Assistant:** AI-powered chat for guiding users through the reservation process.
- **Excel Database:** Uses an Excel file (`library_db.xlsx`) for storing books and bookings.
- **Pluggable AI Providers:** Supports OpenAI GPT and Google Gemini for conversational AI.
- **CORS Enabled:** Ready for integration with frontend applications.

## Project Structure
```
├── app.py                # Main FastAPI application
├── config.py             # Configuration and environment variables
├── conversation_states.json # Stores user conversation states
├── library_db.xlsx       # Excel database for books and bookings
├── models.py             # Pydantic models and AI provider interface
├── providers.py          # AI provider implementations and factory
├── services.py           # Core business logic (book management, chat, conversation)
├── main.py, Library.py   # (Other related apps or legacy code)
```

## Setup Instructions

### 1. Clone the Repository
```bash
git clone <repo-url>
cd library_api
```

### 2. Create and Activate a Virtual Environment (Recommended)
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 3. Install Dependencies
Create a `requirements.txt` file with the following content:
```txt
fastapi
uvicorn
pandas
openpyxl
python-dotenv
pydantic
openai  # For OpenAI GPT support
google-generativeai  # For Gemini support
```
Then install:
```bash
pip install -r requirements.txt
```

### 4. Environment Variables
Create a `.env` file in the project root with the following variables:
```
AI_PROVIDER=openai  # or 'gemini'
OPENAI_API_KEY=your-openai-api-key  # If using OpenAI
GEMINI_API_KEY=your-gemini-api-key  # If using Gemini
```

### 5. Prepare the Excel Database
- Ensure `library_db.xlsx` exists in the project root with at least two sheets:
  - `Books`: Columns should include `ID`, `Title`, `Author`, `Available Copies`, `Total Copies`.
  - `Bookings`: Columns should include `Booking ID`, `Name`, `Book Title`, `Phone Number`, `Duration (Days)`, `Date Booked`.

## Running the Application
Start the FastAPI server:
```bash
uvicorn app:app --reload
```
The API will be available at `http://127.0.0.1:8000/`.

## API Endpoints

### Health Check
- `GET /health` — Returns API status and AI provider info.

### Book Management
- `GET /debug-books` — List all available books.
- `POST /check-book` — Check if a book is available. Requires JSON body:
  ```json
  { "book_title": "Book Title" }
  ```
- `POST /reserve-book` — Reserve a book. Requires JSON body:
  ```json
  { "book_title": "Book Title", "name": "User Name", "phone": "1234567890", "duration": 7 }
  ```
- `GET /debug-bookings` — List all current bookings.

### Conversational Assistant
- `POST /chat` — Interact with the AI assistant. Requires JSON body:
  ```json
  { "message": "I want to reserve 'Book Title'", "user_id": "unique_user_id" }
  ```
  The assistant will guide the user through the reservation process.

## Configuration
- **AI Provider:** Set `AI_PROVIDER` in `.env` to `openai` or `gemini`.
- **API Keys:** Provide the corresponding API key in `.env` (`OPENAI_API_KEY` or `GEMINI_API_KEY`).
- **Excel Path:** By default, uses `library_db.xlsx` in the project root. Change in `config.py` if needed.

## Dependencies
- fastapi
- uvicorn
- pandas
- openpyxl
- python-dotenv
- pydantic
- openai
- google-generativeai

## Example Usage
1. Check available books:
   ```bash
   curl http://127.0.0.1:8000/debug-books
   ```
2. Reserve a book:
   ```bash
   curl -X POST http://127.0.0.1:8000/reserve-book -H "Content-Type: application/json" -d '{"book_title": "Book Title", "name": "Alice", "phone": "1234567890", "duration": 7}'
   ```
3. Chat with the assistant:
   ```bash
   curl -X POST http://127.0.0.1:8000/chat -H "Content-Type: application/json" -d '{"message": "I want to reserve The Great Gatsby", "user_id": "user123"}'
   ```

## Notes
- The AI assistant is strictly limited to library-related queries.
- The Excel file must be properly formatted for the API to function.
- For production, secure your API keys and consider deploying with a production-ready server.

## License
MIT 