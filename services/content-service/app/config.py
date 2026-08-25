from pydantic_settings import BaseSettings
from dotenv import load_dotenv
import os




load_dotenv()


class Settings(BaseSettings):
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_model: str = "GigaChat-2"
    llm_base_url: str = "https://api.giga.chat/v1"
    llm_scope: str = "GIGACHAT_API_PERS"
    llm_temperature: float = 0.2
    llm_max_tokens: int = 4096

    class Config:
        env_file = ".env"

settings = Settings()