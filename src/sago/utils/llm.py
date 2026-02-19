import logging
from collections.abc import Callable
from typing import Any

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)


class LLMError(Exception):
    pass


class LLMRateLimitError(LLMError):
    pass


class LLMClient:
    def __init__(
        self,
        model: str = "gpt-4o",
        api_key: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 4096,
        max_retries: int = 3,
    ) -> None:
        self.model = model
        self.api_key = api_key
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.max_retries = max_retries

    @retry(
        retry=retry_if_exception_type((LLMRateLimitError, ConnectionError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    def chat_completion(
        self,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        max_tokens: int | None = None,
        stream: bool = False,
        stream_callback: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        try:
            return self._do_chat_completion(
                messages,
                temperature,
                max_tokens,
                stream,
                stream_callback,
            )
        except (LLMError, LLMRateLimitError):
            raise
        except Exception as e:
            self._raise_classified_error(e)

    def _do_chat_completion(
        self,
        messages: list[dict[str, str]],
        temperature: float | None,
        max_tokens: int | None,
        stream: bool,
        stream_callback: Callable[[str], None] | None,
    ) -> dict[str, Any]:
        import litellm

        temp = temperature if temperature is not None else self.temperature
        tokens = max_tokens if max_tokens is not None else self.max_tokens

        logger.info(f"LLM request to {self.model} with {len(messages)} messages")

        common_kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temp,
            "max_tokens": tokens,
        }
        if self.api_key:
            common_kwargs["api_key"] = self.api_key

        if stream:
            return self._stream_completion(common_kwargs, stream_callback, litellm)

        response = litellm.completion(**common_kwargs)

        result = {
            "content": response.choices[0].message.content,
            "model": response.model,
            "usage": {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            },
            "finish_reason": response.choices[0].finish_reason,
        }

        logger.info(
            f"LLM response: {result['usage']['total_tokens']} tokens, "
            f"finish_reason={result['finish_reason']}"
        )
        return result

    def _raise_classified_error(self, e: Exception) -> None:
        error_str = str(e).lower()

        if "rate" in error_str and "limit" in error_str:
            logger.warning(f"Rate limit exceeded: {e}")
            raise LLMRateLimitError(f"API rate limit exceeded: {e}") from e

        if "auth" in error_str or "api key" in error_str or "401" in error_str:
            raise LLMError(f"Authentication failed: {e}") from e

        logger.error(f"LLM API error: {e}")
        raise LLMError(f"LLM API call failed: {e}") from e

    def _stream_completion(
        self,
        common_kwargs: dict[str, Any],
        callback: Callable[[str], None] | None,
        litellm: Any,
    ) -> dict[str, Any]:
        response_text = ""
        finish_reason = None
        model_used = self.model
        stream_usage = None

        response = litellm.completion(
            **common_kwargs,
            stream=True,
            stream_options={"include_usage": True},
        )

        for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                content = chunk.choices[0].delta.content
                response_text += content
                if callback:
                    callback(content)

            if chunk.choices and chunk.choices[0].finish_reason:
                finish_reason = chunk.choices[0].finish_reason

            if hasattr(chunk, "model") and chunk.model:
                model_used = chunk.model

            if hasattr(chunk, "usage") and chunk.usage is not None:
                stream_usage = {
                    "prompt_tokens": getattr(chunk.usage, "prompt_tokens", 0),
                    "completion_tokens": getattr(chunk.usage, "completion_tokens", 0),
                    "total_tokens": getattr(chunk.usage, "total_tokens", 0),
                }

        if stream_usage is None:
            stream_usage = self._estimate_stream_usage(common_kwargs, response_text)

        return {
            "content": response_text,
            "model": model_used,
            "finish_reason": finish_reason,
            "usage": stream_usage,
        }

    def _estimate_stream_usage(
        self, common_kwargs: dict[str, Any], response_text: str
    ) -> dict[str, int]:
        msgs = common_kwargs.get("messages", [])
        prompt_text = " ".join(m.get("content", "") for m in msgs)
        prompt_tokens = self.count_tokens(prompt_text)
        completion_tokens = self.count_tokens(response_text)
        return {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        }

    def count_tokens(self, text: str) -> int:
        try:
            import litellm

            return litellm.token_counter(model=self.model, text=text)
        except Exception:
            return len(text) // 4

    def validate_messages(self, messages: list[dict[str, str]]) -> bool:
        if not isinstance(messages, list) or len(messages) == 0:
            return False

        for msg in messages:
            if not isinstance(msg, dict):
                return False
            if "role" not in msg or "content" not in msg:
                return False
            if msg["role"] not in ["system", "user", "assistant"]:
                return False

        return True
