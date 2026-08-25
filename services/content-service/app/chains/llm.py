import httpx
from langchain_openai import ChatOpenAI
from app.config import settings




def get_llm():
    """Возвращает экземпляр LLM"""
    async_client = httpx.AsyncClient(verify=False)
    return ChatOpenAI(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
        verbose=settings.llm_verbose,
        http_async_client=async_client,
        http_client=httpx.Client(verify=False),
    )