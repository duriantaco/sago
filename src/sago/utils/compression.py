import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CompressionResult:
    original_text: str
    compressed_text: str
    original_tokens: int
    compressed_tokens: int
    compression_ratio: float
    method: str
    metadata: dict[str, Any]

    @property
    def token_savings(self) -> int:
        return self.original_tokens - self.compressed_tokens

    @property
    def percentage_saved(self) -> float:
        if self.original_tokens == 0:
            return 0.0
        return (self.token_savings / self.original_tokens) * 100


class CompressorInterface(ABC):
    @abstractmethod
    def compress(
        self,
        text: str,
        target_tokens: int | None = None,
        instruction: str | None = None,
        **kwargs: Any,
    ) -> CompressionResult:
        pass

    @abstractmethod
    def estimate_tokens(self, text: str) -> int:
        pass


class LLMLinguaCompressor(CompressorInterface):
    def __init__(
        self,
        model_name: str = "microsoft/llmlingua-2-bert-base-multilingual-cased-meetingbank",
        device: str = "cpu",
        target_token_ratio: float = 0.5,
    ) -> None:
        self.model_name = model_name
        self.device = device
        self.target_token_ratio = target_token_ratio
        self._compressor = None

    def _get_compressor(self) -> Any:
        """Lazy load the LLMLingua compressor."""
        if self._compressor is None:
            try:
                from llmlingua import PromptCompressor

                self._compressor = PromptCompressor(
                    model_name=self.model_name,
                    device_map=self.device,
                )
                logger.info(f"Loaded LLMLingua compressor: {self.model_name}")
            except ImportError:
                raise ImportError("llmlingua not installed. Run: pip install llmlingua") from None
            except Exception as e:
                raise RuntimeError(f"Failed to load LLMLingua: {e}") from e

        return self._compressor

    def compress(
        self,
        text: str,
        target_tokens: int | None = None,
        instruction: str | None = None,
        question: str | None = None,
        rate: float | None = None,
        **kwargs: Any,
    ) -> CompressionResult:
        compressor = self._get_compressor()
        original_tokens = self.estimate_tokens(text)

        if rate is None:
            if target_tokens:
                rate = min(target_tokens / original_tokens, 1.0)
            else:
                rate = self.target_token_ratio

        try:
            return self._do_compress(
                compressor, text, original_tokens, rate, instruction, question, **kwargs
            )
        except Exception as e:
            logger.error(f"LLMLingua compression failed: {e}")
            return CompressionResult(
                original_text=text,
                compressed_text=text,
                original_tokens=original_tokens,
                compressed_tokens=original_tokens,
                compression_ratio=1.0,
                method="passthrough",
                metadata={"error": str(e)},
            )

    def _do_compress(
        self,
        compressor: Any,
        text: str,
        original_tokens: int,
        rate: float,
        instruction: str | None,
        question: str | None,
        **kwargs: Any,
    ) -> CompressionResult:
        result = compressor.compress_prompt(
            context=text,
            instruction=instruction or "",
            question=question or "",
            rate=rate,
            **kwargs,
        )
        compressed_text = result["compressed_prompt"]
        compressed_tokens = self.estimate_tokens(compressed_text)
        compression_ratio = compressed_tokens / original_tokens if original_tokens > 0 else 1.0

        return CompressionResult(
            original_text=text,
            compressed_text=compressed_text,
            original_tokens=original_tokens,
            compressed_tokens=compressed_tokens,
            compression_ratio=compression_ratio,
            method="llmlingua",
            metadata={
                "model": self.model_name,
                "rate": rate,
                "has_instruction": instruction is not None,
                "has_question": question is not None,
                "origin_tokens": result.get("origin_tokens", original_tokens),
            },
        )

    def estimate_tokens(self, text: str) -> int:
        return len(text) // 4


class SlidingWindowCompressor(CompressorInterface):
    def __init__(self, window_size: int = 10) -> None:
        self.window_size = window_size

    def compress(
        self,
        text: str,
        target_tokens: int | None = None,
        instruction: str | None = None,
        **kwargs: Any,
    ) -> CompressionResult:
        delimiter: str = kwargs.pop("delimiter", "\n\n")
        chunks = text.split(delimiter)
        windowed_chunks = chunks[-self.window_size :]
        compressed_text = delimiter.join(windowed_chunks)

        original_tokens = self.estimate_tokens(text)
        compressed_tokens = self.estimate_tokens(compressed_text)
        compression_ratio = compressed_tokens / original_tokens if original_tokens > 0 else 1.0

        return CompressionResult(
            original_text=text,
            compressed_text=compressed_text,
            original_tokens=original_tokens,
            compressed_tokens=compressed_tokens,
            compression_ratio=compression_ratio,
            method="sliding_window",
            metadata={
                "window_size": self.window_size,
                "total_chunks": len(chunks),
                "kept_chunks": len(windowed_chunks),
            },
        )

    def estimate_tokens(self, text: str) -> int:
        return len(text) // 4


class PassthroughCompressor(CompressorInterface):
    def compress(
        self,
        text: str,
        target_tokens: int | None = None,
        instruction: str | None = None,
        **kwargs: Any,
    ) -> CompressionResult:
        tokens = self.estimate_tokens(text)
        return CompressionResult(
            original_text=text,
            compressed_text=text,
            original_tokens=tokens,
            compressed_tokens=tokens,
            compression_ratio=1.0,
            method="passthrough",
            metadata={},
        )

    def estimate_tokens(self, text: str) -> int:
        return len(text) // 4


class ContextManager:
    def __init__(
        self,
        max_context_tokens: int = 4000,
        compression_threshold: float = 0.8,
        default_compressor: str = "llmlingua",
    ) -> None:
        self.max_context_tokens = max_context_tokens
        self.compression_threshold = compression_threshold
        self.default_compressor = default_compressor

        self.compressors: dict[str, CompressorInterface] = {
            "passthrough": PassthroughCompressor(),
            "sliding_window": SlidingWindowCompressor(),
        }

        self._llmlingua_loaded = False

    def _ensure_llmlingua(self) -> None:
        if not self._llmlingua_loaded:
            try:
                self.compressors["llmlingua"] = LLMLinguaCompressor()
                self._llmlingua_loaded = True
                logger.info("LLMLingua compressor loaded successfully")
            except Exception as e:
                logger.warning(f"Could not load LLMLingua: {e}. Using fallback.")
                self.compressors["llmlingua"] = PassthroughCompressor()

    def should_compress(self, text: str) -> bool:
        estimated_tokens = len(text) // 4
        threshold_tokens = int(self.max_context_tokens * self.compression_threshold)
        return estimated_tokens > threshold_tokens

    def compress(
        self,
        text: str,
        strategy: str | None = None,
        target_tokens: int | None = None,
        **kwargs: Any,
    ) -> CompressionResult:
        strategy = strategy or self.default_compressor

        if strategy == "llmlingua":
            self._ensure_llmlingua()

        compressor = self.compressors.get(strategy)
        if compressor is None:
            logger.warning(f"Unknown compressor: {strategy}, using passthrough")
            compressor = self.compressors["passthrough"]

        if target_tokens is None:
            target_tokens = int(self.max_context_tokens * 0.7)

        result = compressor.compress(text, target_tokens=target_tokens, **kwargs)

        logger.info(
            f"Compressed {result.original_tokens} → {result.compressed_tokens} tokens "
            f"({result.percentage_saved:.1f}% saved) using {strategy}"
        )

        return result

    def auto_compress(self, text: str, **kwargs: Any) -> CompressionResult:
        if self.should_compress(text):
            logger.info("Context exceeds threshold, applying compression")
            return self.compress(text, **kwargs)
        else:
            logger.debug("Context within limits, no compression needed")
            return self.compressors["passthrough"].compress(text)

    def get_stats(self) -> dict[str, Any]:
        return {
            "max_context_tokens": self.max_context_tokens,
            "compression_threshold": self.compression_threshold,
            "default_compressor": self.default_compressor,
            "available_compressors": list(self.compressors.keys()),
            "llmlingua_loaded": self._llmlingua_loaded,
        }
