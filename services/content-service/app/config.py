import logging
import os
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()

class Settings(BaseSettings):
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_model: str = "GigaChat-2-Max"
    llm_base_url: str = "https://api.giga.chat/v1"
    llm_scope: str = "GIGACHAT_API_PERS"
    llm_temperature: float = 0.2
    llm_max_tokens: int = 4096
    log_file: str = "content_service.log"
    log_level: str = "DEBUG"

    class Config:
        env_file = ".env"

settings = Settings()

def setup_logging():
    logging.basicConfig(
        filename=settings.log_file,
        level=getattr(logging, settings.log_level.upper(), logging.DEBUG),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        encoding="utf-8",
    )
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    logging.getLogger().addHandler(console)