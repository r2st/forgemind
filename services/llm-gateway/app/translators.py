"""Translation layer for provider-specific APIs."""

from typing import Any
import httpx
from .schemas import ChatCompletionRequest, ChatCompletionResponse, ChatMessage, ChatCompletionChoice, ChatCompletionUsage, ProviderType
import time
import uuid


class ProviderTranslator:
    """Base class for provider translators."""
    
    async def translate_request(self, request: ChatCompletionRequest, api_key: str) -> tuple[str, dict[str, Any], dict[str, str]]:
        """
        Translate OpenAI request to provider-native format.
        Returns: (url, payload, headers)
        """
        raise NotImplementedError
    
    async def translate_response(self, response: dict[str, Any], model: str) -> ChatCompletionResponse:
        """Translate provider response to OpenAI format."""
        raise NotImplementedError


class OpenAICompatibleTranslator(ProviderTranslator):
    """Pass-through for OpenAI-compatible providers."""
    
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
    
    async def translate_request(self, request: ChatCompletionRequest, api_key: str) -> tuple[str, dict[str, Any], dict[str, str]]:
        url = f"{self.base_url}/chat/completions"
        payload = request.model_dump(exclude_none=True)
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}" if api_key else "",
        }
        return url, payload, headers
    
    async def translate_response(self, response: dict[str, Any], model: str) -> ChatCompletionResponse:
        # Already in OpenAI format
        return ChatCompletionResponse(**response)


class AnthropicTranslator(ProviderTranslator):
    """Translator for Anthropic Claude API."""
    
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
    
    async def translate_request(self, request: ChatCompletionRequest, api_key: str) -> tuple[str, dict[str, Any], dict[str, str]]:
        url = f"{self.base_url}/messages"
        
        # Convert messages to Anthropic format
        system_messages = []
        messages = []
        for msg in request.messages:
            if msg.role == "system":
                system_messages.append(msg.content or "")
            else:
                messages.append({
                    "role": msg.role,
                    "content": msg.content or ""
                })
        
        payload = {
            "model": request.model,
            "messages": messages,
            "max_tokens": request.max_tokens or 1024,
            "temperature": request.temperature,
        }
        
        if system_messages:
            payload["system"] = "\n\n".join(system_messages)
        
        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }
        
        return url, payload, headers
    
    async def translate_response(self, response: dict[str, Any], model: str) -> ChatCompletionResponse:
        # Convert Anthropic response to OpenAI format
        content = ""
        if response.get("content"):
            for block in response["content"]:
                if block.get("type") == "text":
                    content = block.get("text", "")
                    break
        
        usage = response.get("usage", {})
        
        return ChatCompletionResponse(
            id=response.get("id", f"chatcmpl-{uuid.uuid4().hex[:8]}"),
            object="chat.completion",
            created=int(time.time()),
            model=model,
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message=ChatMessage(role="assistant", content=content),
                    finish_reason=response.get("stop_reason", "stop")
                )
            ],
            usage=ChatCompletionUsage(
                prompt_tokens=usage.get("input_tokens", 0),
                completion_tokens=usage.get("output_tokens", 0),
                total_tokens=usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
            )
        )


class GeminiTranslator(ProviderTranslator):
    """Translator for Google Gemini API."""
    
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
    
    async def translate_request(self, request: ChatCompletionRequest, api_key: str) -> tuple[str, dict[str, Any], dict[str, str]]:
        # Gemini uses API key in URL
        url = f"{self.base_url}/models/{request.model}:generateContent?key={api_key}"
        
        # Convert messages to Gemini format
        contents = []
        for msg in request.messages:
            role = "user" if msg.role in ["user", "system"] else "model"
            contents.append({
                "role": role,
                "parts": [{"text": msg.content or ""}]
            })
        
        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": request.temperature,
                "maxOutputTokens": request.max_tokens or 1024,
            }
        }
        
        headers = {"Content-Type": "application/json"}
        
        return url, payload, headers
    
    async def translate_response(self, response: dict[str, Any], model: str) -> ChatCompletionResponse:
        # Convert Gemini response to OpenAI format
        content = ""
        if response.get("candidates"):
            candidate = response["candidates"][0]
            if candidate.get("content", {}).get("parts"):
                content = candidate["content"]["parts"][0].get("text", "")
        
        # Gemini doesn't provide detailed token counts in all responses
        usage_metadata = response.get("usageMetadata", {})
        
        return ChatCompletionResponse(
            id=f"chatcmpl-{uuid.uuid4().hex[:8]}",
            object="chat.completion",
            created=int(time.time()),
            model=model,
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message=ChatMessage(role="assistant", content=content),
                    finish_reason="stop"
                )
            ],
            usage=ChatCompletionUsage(
                prompt_tokens=usage_metadata.get("promptTokenCount", 0),
                completion_tokens=usage_metadata.get("candidatesTokenCount", 0),
                total_tokens=usage_metadata.get("totalTokenCount", 0)
            )
        )


def get_translator(provider_type: ProviderType, base_url: str) -> ProviderTranslator:
    """Get the appropriate translator for a provider type."""
    if provider_type == ProviderType.ANTHROPIC:
        return AnthropicTranslator(base_url)
    elif provider_type == ProviderType.GEMINI:
        return GeminiTranslator(base_url)
    else:
        # All other providers are OpenAI-compatible
        return OpenAICompatibleTranslator(base_url)
