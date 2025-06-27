import os
from dotenv import load_dotenv

load_dotenv()

EXCEL_PATH = os.path.abspath("library_db.xlsx")
AI_PROVIDER_NAME = os.getenv("AI_PROVIDER", "openai") 