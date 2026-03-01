import logging
from collections.abc import Callable
from typing import Any, NoReturn

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

logger = logging.getLogger(__name__)


class LLMError(Exception):
    pass


class LLMRateLimitError(LLMError):
    pass


_RETRY_DECORATOR = retry(
    retry=retry_if_exception_type((LLMRateLimitError, ConnectionError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential_jitter(initial=2, max=30),
    reraise=True,
)


class LLMClient:
    def __init__(
        self,
        model: str = "gpt-4o",
        api_key: str | None = None,
        temperature: float = 0.1,
        max_tokens: int = 4096,
        max_retries: int = 3,
        warn_token_threshold: int = 50_000,
    ) -> None:
        self.model = model
        self.api_key = api_key
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.max_retries = max_retries
        self.warn_token_threshold = warn_token_threshold

    def _build_kwargs(
        self,
        messages: list[dict[str, Any]],
        temperature: float | None,
        max_tokens: int | None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
    ) -> dict[str, Any]:
        temp = temperature if temperature is not None else self.temperature
        tokens = max_tokens if max_tokens is not None else self.max_tokens
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temp,
            "max_tokens": tokens,
        }
        if self.api_key:
            kwargs["api_key"] = self.api_key
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice or "auto"
        return kwargs

    @_RETRY_DECORATOR
    def chat_completion(
        self,
        messages: list[dict[str, Any]],
        temperature: float | None = None,
        max_tokens: int | None = None,
        stream: bool = False,
        stream_callback: Callable[[str], None] | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
    ) -> dict[str, Any]:
        if not self.validate_messages(messages):
            raise LLMError("Invalid messages: each must have 'role' and 'content' keys")
        try:
            return self._do_chat_completion(
                messages,
                temperature,
                max_tokens,
                stream,
                stream_callback,
                tools=tools,
                tool_choice=tool_choice,
            )
        except (LLMError, LLMRateLimitError):
            raise
        except Exception as e:
            self._raise_classified_error(e)

    @_RETRY_DECORATOR
    async def achat_completion(
        self,
        messages: list[dict[str, Any]],
        temperature: float | None = None,
        max_tokens: int | None = None,
        stream: bool = False,
        stream_callback: Callable[[str], None] | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
    ) -> dict[str, Any]:
        if not self.validate_messages(messages):
            raise LLMError("Invalid messages: each must have 'role' and 'content' keys")
        try:
            return await self._ado_chat_completion(
                messages,
                temperature,
                max_tokens,
                stream,
                stream_callback,
                tools=tools,
                tool_choice=tool_choice,
            )
        except (LLMError, LLMRateLimitError):
            raise
        except Exception as e:
            self._raise_classified_error(e)

    def _warn_if_over_threshold(self, messages: list[dict[str, Any]]) -> None:
        """Log a warning if the input messages exceed the token threshold."""
        try:
            input_text = " ".join(m.get("content", "") or "" for m in messages)
            input_tokens = self.count_tokens(input_text)
            if input_tokens > self.warn_token_threshold:
                logger.warning(
                    f"Large input: ~{input_tokens} tokens (threshold: {self.warn_token_threshold})"
                )
            else:
                logger.debug(f"Input token estimate: ~{input_tokens}")
        except Exception as exc:
            logger.debug(f"Token threshold check failed: {exc}")

    def _log_usage(self, result: dict[str, Any]) -> None:
        """Log token usage from a completed response."""
        usage = result.get("usage", {})
        logger.info(
            f"Token usage: prompt={usage.get('prompt_tokens', 0)}, "
            f"completion={usage.get('completion_tokens', 0)}, "
            f"total={usage.get('total_tokens', 0)}"
        )

    def _do_chat_completion(
        self,
        messages: list[dict[str, Any]],
        temperature: float | None,
        max_tokens: int | None,
        stream: bool,
        stream_callback: Callable[[str], None] | None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
    ) -> dict[str, Any]:
        import litellm

        common_kwargs = self._build_kwargs(
            messages, temperature, max_tokens, tools=tools, tool_choice=tool_choice
        )

        self._warn_if_over_threshold(messages)
        logger.info(f"LLM request to {self.model} with {len(messages)} messages")

        if stream:
            result = self._stream_completion(common_kwargs, stream_callback, litellm)
            self._log_usage(result)
            return result

        response = litellm.completion(**common_kwargs)
        result = self._parse_response(response)
        self._log_usage(result)
        return result

    async def _ado_chat_completion(
        self,
        messages: list[dict[str, Any]],
        temperature: float | None,
        max_tokens: int | None,
        stream: bool,
        stream_callback: Callable[[str], None] | None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
    ) -> dict[str, Any]:
        import litellm

        common_kwargs = self._build_kwargs(
            messages, temperature, max_tokens, tools=tools, tool_choice=tool_choice
        )

        self._warn_if_over_threshold(messages)
        logger.info(f"LLM request to {self.model} with {len(messages)} messages")

        if stream:
            result = await self._astream_completion(common_kwargs, stream_callback, litellm)
            self._log_usage(result)
            return result

        response = await litellm.acompletion(**common_kwargs)
        result = self._parse_response(response)
        self._log_usage(result)
        return result

    def _parse_response(self, response: Any) -> dict[str, Any]:
        message = response.choices[0].message
        result: dict[str, Any] = {
            "content": message.content,
            "model": response.model,
            "usage": {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            },
            "finish_reason": response.choices[0].finish_reason,
            "raw_message": message,
        }
        if hasattr(message, "tool_calls") and message.tool_calls:
            result["tool_calls"] = message.tool_calls
        logger.info(
            f"LLM response: {result['usage']['total_tokens']} tokens, "
            f"finish_reason={result['finish_reason']}"
        )
        return result

    def _raise_classified_error(self, e: Exception) -> NoReturn:
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
        response = litellm.completion(
            **common_kwargs,
            stream=True,
            stream_options={"include_usage": True},
        )
        return self._collect_stream(response, callback)

    async def _astream_completion(
        self,
        common_kwargs: dict[str, Any],
        callback: Callable[[str], None] | None,
        litellm: Any,
    ) -> dict[str, Any]:
        response = await litellm.acompletion(
            **common_kwargs,
            stream=True,
            stream_options={"include_usage": True},
        )
        return await self._acollect_stream(response, callback)

    def _collect_stream(
        self,
        response: Any,
        callback: Callable[[str], None] | None,
    ) -> dict[str, Any]:
        response_text = ""
        finish_reason = None
        model_used = self.model
        stream_usage = None

        for chunk in response:
            response_text, finish_reason, model_used, stream_usage = self._process_chunk(
                chunk, response_text, finish_reason, model_used, stream_usage, callback
            )

        if stream_usage is None:
            stream_usage = self._estimate_usage(response_text)

        return {
            "content": response_text,
            "model": model_used,
            "finish_reason": finish_reason,
            "usage": stream_usage,
        }

    async def _acollect_stream(
        self,
        response: Any,
        callback: Callable[[str], None] | None,
    ) -> dict[str, Any]:
        response_text = ""
        finish_reason = None
        model_used = self.model
        stream_usage = None

        async for chunk in response:
            response_text, finish_reason, model_used, stream_usage = self._process_chunk(
                chunk, response_text, finish_reason, model_used, stream_usage, callback
            )

        if stream_usage is None:
            stream_usage = self._estimate_usage(response_text)

        return {
            "content": response_text,
            "model": model_used,
            "finish_reason": finish_reason,
            "usage": stream_usage,
        }

    def _process_chunk(
        self,
        chunk: Any,
        response_text: str,
        finish_reason: str | None,
        model_used: str,
        stream_usage: dict[str, int] | None,
        callback: Callable[[str], None] | None,
    ) -> tuple[str, str | None, str, dict[str, int] | None]:
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

        return response_text, finish_reason, model_used, stream_usage

    def _estimate_usage(self, response_text: str) -> dict[str, int]:
        completion_tokens = self.count_tokens(response_text)
        return {
            "prompt_tokens": 0,
            "completion_tokens": completion_tokens,
            "total_tokens": completion_tokens,
        }

    def count_tokens(self, text: str) -> int:
        try:
            import litellm

            return litellm.token_counter(model=self.model, text=text)
        except Exception:
            return len(text) // 4

    def validate_messages(self, messages: list[dict[str, Any]]) -> bool:
        if not isinstance(messages, list) or len(messages) == 0:
            return False

        _VALID_ROLES = {"system", "user", "assistant", "tool", "function"}

        for msg in messages:
            if not isinstance(msg, dict):
                return False
            if "role" not in msg:
                return False
            if msg["role"] not in _VALID_ROLES:
                return False
            if msg["role"] in ("system", "user") and "content" not in msg:
                return False

        return True

    def supports_function_calling(self) -> bool:
        """Check if the current model supports function calling / tool use."""
        try:
            import litellm

            return bool(litellm.supports_function_calling(model=self.model))
        except Exception:
            return False
