import os
from pydantic_settings import BaseSettings
from dotenv import load_dotenv




load_dotenv()

LLM_API_KEY = os.getenv("LLM_API_KEY", "YOUR API KEY FROM .env")

class Settings(BaseSettings):
    """Настройки сервиса"""
    llm_base_url: str = "https://gigachat.devices.sberbank.ru/api/v1"
    llm_api_key: str = LLM_API_KEY
    llm_model: str = "GigaChat:latest"
    llm_temperature: float = 0.2
    llm_max_tokens: int = 2048
    llm_verbose: bool = False

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()