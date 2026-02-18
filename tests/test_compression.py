from unittest.mock import MagicMock, patch

import pytest

from sago.utils.compression import (
    ContextManager,
    LLMLinguaCompressor,
    PassthroughCompressor,
    SlidingWindowCompressor,
)

try:
    import llmlingua

    HAS_LLMLINGUA = True
except ImportError:
    HAS_LLMLINGUA = False


@pytest.fixture
def sample_text() -> str:
    return """
    This is a long piece of text that needs to be compressed.
    It contains multiple sentences and paragraphs.
    The compression system should reduce its size while maintaining meaning.
    This is important for managing LLM context windows efficiently.
    We want to save tokens and reduce costs.
    """ * 10


def test_passthrough_compressor(sample_text: str) -> None:
    """Test that passthrough returns text unchanged."""
    compressor = PassthroughCompressor()
    result = compressor.compress(sample_text)

    assert result.compressed_text == sample_text
    assert result.original_text == sample_text
    assert result.compression_ratio == 1.0
    assert result.token_savings == 0
    assert result.method == "passthrough"


def test_sliding_window_compressor() -> None:
    """Test sliding window keeps only recent items."""
    text = "chunk1\n\nchunk2\n\nchunk3\n\nchunk4\n\nchunk5"
    compressor = SlidingWindowCompressor(window_size=3)

    result = compressor.compress(text)

    # Should keep only last 3 chunks
    assert "chunk1" not in result.compressed_text
    assert "chunk2" not in result.compressed_text
    assert "chunk3" in result.compressed_text
    assert "chunk4" in result.compressed_text
    assert "chunk5" in result.compressed_text
    assert result.method == "sliding_window"
    assert result.compression_ratio < 1.0


def test_sliding_window_metadata() -> None:
    text = "a\n\nb\n\nc\n\nd\n\ne"
    compressor = SlidingWindowCompressor(window_size=2)

    result = compressor.compress(text)

    assert result.metadata["total_chunks"] == 5
    assert result.metadata["kept_chunks"] == 2
    assert result.metadata["window_size"] == 2


def test_context_manager_should_compress() -> None:
    """Test compression threshold detection."""
    manager = ContextManager(max_context_tokens=100, compression_threshold=0.8)

    short_text = "Short text"
    assert manager.should_compress(short_text) is False

    long_text = "x" * 400
    assert manager.should_compress(long_text) is True


def test_context_manager_auto_compress() -> None:
    """Test automatic compression."""
    manager = ContextManager(
        max_context_tokens=100,
        compression_threshold=0.5,
        default_compressor="sliding_window",
    )

    short_result = manager.auto_compress("Short")
    assert short_result.method == "passthrough"
    assert short_result.compression_ratio == 1.0

    # Long text - should trigger compression attempt
    long_text = "\n\n".join([f"This is a longer chunk number {i}" * 10 for i in range(50)])
    long_result = manager.auto_compress(long_text)
    assert long_result is not None
    assert long_result.method in ["sliding_window", "passthrough"]


def test_context_manager_compress_with_strategy() -> None:
    manager = ContextManager()

    text = "\n\n".join([f"chunk{i}" for i in range(20)])
    result = manager.compress(text, strategy="sliding_window")

    assert result.method == "sliding_window"
    assert result.compressed_tokens < result.original_tokens


def test_context_manager_unknown_strategy() -> None:
    manager = ContextManager()
    result = manager.compress("test", strategy="unknown_strategy")
    assert result.method == "passthrough"


def test_context_manager_get_stats() -> None:
    """Test getting context manager statistics."""
    manager = ContextManager(
        max_context_tokens=5000,
        compression_threshold=0.75,
        default_compressor="sliding_window",
    )

    stats = manager.get_stats()

    assert stats["max_context_tokens"] == 5000
    assert stats["compression_threshold"] == 0.75
    assert stats["default_compressor"] == "sliding_window"
    assert "passthrough" in stats["available_compressors"]
    assert "sliding_window" in stats["available_compressors"]


def test_compression_result_properties() -> None:
    from sago.utils.compression import CompressionResult

    result = CompressionResult(
        original_text="original",
        compressed_text="comp",
        original_tokens=100,
        compressed_tokens=50,
        compression_ratio=0.5,
        method="test",
        metadata={},
    )

    assert result.token_savings == 50
    assert result.percentage_saved == 50.0


def test_compression_result_zero_tokens() -> None:
    """Test CompressionResult with zero tokens."""
    from sago.utils.compression import CompressionResult

    result = CompressionResult(
        original_text="",
        compressed_text="",
        original_tokens=0,
        compressed_tokens=0,
        compression_ratio=0.0,
        method="test",
        metadata={},
    )

    assert result.token_savings == 0
    assert result.percentage_saved == 0.0


def test_llmlingua_compressor_initialization() -> None:
    """Test LLMLingua compressor initialization."""
    compressor = LLMLinguaCompressor(
        model_name="test-model",
        device="cpu",
    )

    assert compressor.model_name == "test-model"
    assert compressor.device == "cpu"
    assert compressor._compressor is None


@pytest.mark.skipif(not HAS_LLMLINGUA, reason="llmlingua not installed")
@pytest.mark.skipif(not HAS_LLMLINGUA, reason="llmlingua not installed")
@patch("llmlingua.PromptCompressor")
def test_llmlingua_compress_success(mock_compressor_class: MagicMock) -> None:
    mock_instance = MagicMock()
    mock_instance.compress_prompt.return_value = {
        "compressed_prompt": "compressed text",
        "origin_tokens": 100,
    }
    mock_compressor_class.return_value = mock_instance

    compressor = LLMLinguaCompressor()
    result = compressor.compress("original long text", target_tokens=50)

    assert result.compressed_text == "compressed text"
    assert result.method == "llmlingua"
    assert result.compression_ratio < 1.0
    mock_instance.compress_prompt.assert_called_once()


@pytest.mark.skipif(not HAS_LLMLINGUA, reason="llmlingua not installed")
@patch("llmlingua.PromptCompressor")
def test_llmlingua_compress_with_instruction(mock_compressor_class: MagicMock) -> None:
    """Test LLMLingua compression with instruction."""
    mock_instance = MagicMock()
    mock_instance.compress_prompt.return_value = {
        "compressed_prompt": "compressed",
        "origin_tokens": 50,
    }
    mock_compressor_class.return_value = mock_instance

    compressor = LLMLinguaCompressor()
    result = compressor.compress(
        "text",
        instruction="Summarize this",
        question="What is the main point?",
    )

    assert result.metadata["has_instruction"] is True
    assert result.metadata["has_question"] is True


@pytest.mark.skipif(not HAS_LLMLINGUA, reason="llmlingua not installed")
@patch("llmlingua.PromptCompressor")
def test_llmlingua_compress_failure_fallback(mock_compressor_class: MagicMock) -> None:
    mock_instance = MagicMock()
    mock_instance.compress_prompt.side_effect = Exception("Compression failed")
    mock_compressor_class.return_value = mock_instance

    compressor = LLMLinguaCompressor()
    result = compressor.compress("original text")

    assert result.compressed_text == "original text"
    assert result.method == "passthrough"
    assert "error" in result.metadata


def test_estimate_tokens_approximation() -> None:
    compressor = PassthroughCompressor()
    text = "x" * 100
    tokens = compressor.estimate_tokens(text)

    assert tokens == 25


def test_context_manager_target_tokens_calculation() -> None:
    manager = ContextManager(max_context_tokens=1000)
    result = manager.compress("test", strategy="passthrough")
    assert result is not None
