import abc
import time
import logging
from typing import Dict, Any, List, Optional
import google.generativeai as genai
from app.config import settings

logger = logging.getLogger(__name__)


class BaseAIProvider(abc.ABC):
    """Abstract Base Class for AI Providers."""

    @abc.abstractmethod
    async def generate_text(self, prompt: str, system_instruction: Optional[str] = None) -> Dict[str, Any]:
        """Generate response text and return text + token usage metadata."""
        pass

    @abc.abstractmethod
    async def generate_embedding(self, text: str) -> Dict[str, Any]:
        """Generate vector embedding and return vector + token usage metadata."""
        pass


class GeminiAIProvider(BaseAIProvider):
    """Google Gemini AI Provider Implementation."""

    def __init__(self):
        if settings.GEMINI_API_KEY:
            genai.configure(api_key=settings.GEMINI_API_KEY)
        self.text_model_name = settings.GEMINI_MODEL
        self.embedding_model_name = settings.GEMINI_EMBEDDING_MODEL

    async def generate_text(self, prompt: str, system_instruction: Optional[str] = None) -> Dict[str, Any]:
        start_time = time.time()
        try:
            model = genai.GenerativeModel(
                model_name=self.text_model_name,
                system_instruction=system_instruction
            )
            response = model.generate_content(prompt)
            latency = time.time() - start_time

            # Retrieve actual token counts if available from Gemini response
            usage_metadata = getattr(response, 'usage_metadata', None)
            input_tokens = getattr(usage_metadata, 'prompt_token_count', len(prompt.split()) * 2) if usage_metadata else len(prompt.split()) * 2
            output_tokens = getattr(usage_metadata, 'candidates_token_count', len(response.text.split()) * 2) if usage_metadata else len(response.text.split()) * 2

            return {
                "text": response.text.strip(),
                "model": self.text_model_name,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "latency_seconds": round(latency, 3),
                "provider": "gemini"
            }
        except Exception as e:
            logger.error(f"Gemini AI provider text generation error: {e}")
            raise e

    async def generate_embedding(self, text: str) -> Dict[str, Any]:
        start_time = time.time()
        try:
            result = genai.embed_content(
                model=self.embedding_model_name,
                content=text,
                task_type="retrieval_document"
            )
            latency = time.time() - start_time
            embedding_vector = result.get("embedding", [])
            tokens = len(text.split()) * 2

            return {
                "embedding": embedding_vector,
                "model": self.embedding_model_name,
                "input_tokens": tokens,
                "output_tokens": 0,
                "latency_seconds": round(latency, 3),
                "provider": "gemini"
            }
        except Exception as e:
            logger.error(f"Gemini AI provider embedding generation error: {e}")
            raise e


# Singleton instance
ai_provider = GeminiAIProvider()
