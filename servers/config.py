
# config.py
"""
Centralized configuration loader for MCP servers.
Loads settings from a .env file and exposes them as module-level variables.
"""
import os
from dotenv import load_dotenv

load_dotenv()

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:5000/api/v1")

HTTP_CONNECT_TIMEOUT = int(os.getenv("HTTP_CONNECT_TIMEOUT", 15))
HTTP_READ_TIMEOUT = int(os.getenv("HTTP_READ_TIMEOUT", 60))
HTTP_TIMEOUT = (HTTP_CONNECT_TIMEOUT, HTTP_READ_TIMEOUT)

# API key for Google Gemini
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
fal_api_key = os.getenv("FAL_KEY")

AI_HTTP_CONNECT_TIMEOUT = int(os.getenv("AI_HTTP_CONNECT_TIMEOUT", 15))
AI_HTTP_READ_TIMEOUT = int(os.getenv("AI_HTTP_READ_TIMEOUT", 180)) # 3 minutes
AI_HTTP_TIMEOUT = (AI_HTTP_CONNECT_TIMEOUT, AI_HTTP_READ_TIMEOUT)

