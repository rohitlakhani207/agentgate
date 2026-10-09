"""One place that turns (provider, model) into a LangChain chat model. All free options."""

from __future__ import annotations

from langchain_core.language_models import BaseChatModel

from .config import Provider, Settings


def chat_model(settings: Settings, provider: Provider, model: str) -> BaseChatModel:
    if provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(model=model, base_url=settings.ollama_url, temperature=0)
    if provider == "groq":
        from langchain_groq import ChatGroq

        if not settings.groq_api_key:
            raise RuntimeError("GROQ_API_KEY is not set")
        extra = {}
        if "gpt-oss" in model:
            # Reasoning models: their thinking counts against the free tier's per-minute and
            # per-day token limits, so keep it short.
            extra["reasoning_effort"] = "low"
        return ChatGroq(
            model=model, api_key=settings.groq_api_key, temperature=0, max_retries=3, **extra
        )
    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI

        if not settings.google_api_key:
            raise RuntimeError("GOOGLE_API_KEY is not set")
        return ChatGoogleGenerativeAI(
            model=model, google_api_key=settings.google_api_key, temperature=0, max_retries=3
        )
    raise ValueError(f"unknown provider {provider}")


def judge_model(settings: Settings) -> BaseChatModel:
    return chat_model(settings, settings.effective_judge_provider, settings.effective_judge_model)
