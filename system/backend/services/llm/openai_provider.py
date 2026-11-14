"""OpenAI-compatible LLM provider (Aliyun MaaS Qwen-VL by default).

Supports both text and vision (image) API calls.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from backend.services.llm.base import LLMMessage, LLMProvider, LLMResponse
from backend.services.llm.config import (
    DEFAULT_OPENAI_BASE_URL,
    DEFAULT_OPENAI_MODEL,
    openai_api_key,
    openai_base_url,
    openai_model,
)

logger = logging.getLogger(__name__)

LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "120"))
LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "2"))


class OpenAIProvider(LLMProvider):
    """OpenAI-compatible API provider for text and vision LLM calls.

    Supports any OpenAI-compatible API (OpenAI, Azure, Aliyun MaaS, etc.)
    by setting a custom base_url.
    """

    provider_name = "openai"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        default_model: str | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else openai_api_key()
        self.base_url = base_url if base_url is not None else openai_base_url()
        self.default_model = default_model if default_model is not None else openai_model()
        if not self.base_url:
            self.base_url = DEFAULT_OPENAI_BASE_URL
        if not self.default_model:
            self.default_model = DEFAULT_OPENAI_MODEL

    async def generate(
        self,
        messages: list[LLMMessage],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate a response using OpenAI-compatible API."""
        from backend.progress import raise_if_job_cancelled

        raise_if_job_cancelled()
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=LLM_TIMEOUT_SECONDS,
            max_retries=LLM_MAX_RETRIES,
        )
        model = model or self.default_model

        # Convert LLMMessage to OpenAI format
        openai_messages = []
        for msg in messages:
            # Check if content is a list (multimodal)
            try:
                content = json.loads(msg.content)
                if isinstance(content, list):
                    openai_messages.append({"role": msg.role, "content": content})
                else:
                    openai_messages.append({"role": msg.role, "content": msg.content})
            except (json.JSONDecodeError, TypeError):
                openai_messages.append({"role": msg.role, "content": msg.content})

        response = await client.chat.completions.create(
            model=model,
            messages=openai_messages,  # type: ignore
            temperature=temperature,
            max_tokens=max_tokens,
        )

        choice = response.choices[0]
        return LLMResponse(
            content=choice.message.content or "",
            model=response.model,
            usage={
                "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                "completion_tokens": response.usage.completion_tokens if response.usage else 0,
            },
            finish_reason=choice.finish_reason or "",
        )

    async def generate_structured(
        self,
        messages: list[LLMMessage],
        response_schema: dict[str, Any],
        model: str | None = None,
        temperature: float = 0.3,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Generate a structured JSON response using OpenAI-compatible API."""
        response = await self.generate(
            messages=messages,
            model=model,
            temperature=temperature,
            **kwargs,
        )
        try:
            return json.loads(response.content)
        except json.JSONDecodeError:
            return {"raw_response": response.content}

    async def generate_vision(
        self,
        system_prompt: str,
        text_content: str,
        image_paths: list[str] | None = None,
        image_data_list: list[str] | None = None,
        model: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ) -> LLMResponse:
        """Generate a response with image inputs.

        This is the primary method for Image LLM Analysis.

        Args:
            system_prompt: System message.
            text_content: User text instruction.
            image_paths: Paths to image files to include.
            image_data_list: Pre-encoded base64 image data.
            model: Model to use (default: OPENAI_MODEL / qwen3-vl-plus).
            temperature: Sampling temperature.
            max_tokens: Max tokens in response.

        Returns:
            LLMResponse with analysis.
        """
        from backend.progress import raise_if_job_cancelled

        raise_if_job_cancelled()
        import base64

        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=LLM_TIMEOUT_SECONDS,
            max_retries=LLM_MAX_RETRIES,
        )
        model = model or self.default_model

        # Build content parts
        content_parts: list[dict[str, Any]] = [
            {"type": "text", "text": text_content},
        ]

        if image_paths:
            for path in image_paths:
                with open(path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("utf-8")
                content_parts.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{b64}",
                        "detail": "high",
                    },
                })

        if image_data_list:
            for b64 in image_data_list:
                content_parts.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{b64}",
                        "detail": "high",
                    },
                })

        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content_parts},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )

        choice = response.choices[0]
        return LLMResponse(
            content=choice.message.content or "",
            model=response.model,
            usage={
                "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                "completion_tokens": response.usage.completion_tokens if response.usage else 0,
            },
            finish_reason=choice.finish_reason or "",
        )
