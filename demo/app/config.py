"""Configuration. Reads the existing project-root .env (DATABASE_URL, *_API_KEY)
and an optional demo/.env override."""
import os
from pathlib import Path
from dotenv import load_dotenv

# app/ -> demo/ -> project root
ROOT = Path(__file__).resolve().parents[2]
DEMO = Path(__file__).resolve().parents[1]

# Load root .env first (has DATABASE_URL + GROQ_API_KEY), then demo/.env override.
load_dotenv(ROOT / ".env")
load_dotenv(DEMO / ".env", override=True)

DATABASE_URL = os.environ.get("DATABASE_URL", "")

# Target exam + language for this personal demo.
LANGUAGE = "fr"
EXAM = "tcf_canada"
LEVEL = "B2"

# Skills we generate practice for.
SKILLS = ["reading", "listening", "writing", "speaking"]
