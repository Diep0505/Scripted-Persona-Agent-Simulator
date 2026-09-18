from dotenv import load_dotenv
import os

load_dotenv()

# API Keys
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TEST_AGENT_API_KEY = os.getenv("TEST_AGENT_API_KEY") or GEMINI_API_KEY

# Models
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
TEST_AGENT_MODEL = os.getenv("TEST_AGENT_MODEL") or GEMINI_MODEL
FALLBACK_MODELS = [m.strip() for m in os.getenv("FALLBACK_MODELS", "gemini-3.6-flash,gemini-3.5-flash-lite").split(",")]

# Generation Config
TEMPERATURE = float(os.getenv("TEMPERATURE", 0.7))
MAX_OUTPUT_TOKENS = int(os.getenv("MAX_OUTPUT_TOKENS", 512))
TOP_P = float(os.getenv("TOP_P", 0.95))