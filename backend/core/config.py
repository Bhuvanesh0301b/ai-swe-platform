import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "")
    GROQ_REASONING_EFFORT: str = os.getenv("GROQ_REASONING_EFFORT", "low")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "openai/gpt-oss-120b")
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./storage/app.db")
    CHROMA_DB_PATH: str = os.getenv("CHROMA_DB_PATH", "./storage/chroma_db")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")

    def validate(self):
        missing = []
        if not self.GROQ_API_KEY:
            missing.append("GROQ_API_KEY")
        if not self.GITHUB_TOKEN:
            missing.append("GITHUB_TOKEN")
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

settings = Settings()