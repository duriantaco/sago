from unittest.mock import MagicMock, patch
import pytest
from sago.utils.llm import LLMClient, LLMError


@pytest.fixture
def llm_client() -> LLMClient:
    return LLMClient(model="gpt-4", api_key="test-key")


def test_llm_client_initialization() -> None:
    client = LLMClient(
        model="gpt-4",
        api_key="test-key",
        temperature=0.5,
        max_tokens=2000,
    )

    assert client.model == "gpt-4"
    assert client.api_key == "test-key"
    assert client.temperature == 0.5
    assert client.max_tokens == 2000


@patch("litellm.completion")
def test_llm_client_calls_api(mock_completion: MagicMock, llm_client: LLMClient) -> None:
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "Test response"
    mock_response.choices[0].finish_reason = "stop"
    mock_response.model = "gpt-4"
    mock_response.usage.prompt_tokens = 10
    mock_response.usage.completion_tokens = 20
    mock_response.usage.total_tokens = 30

    mock_completion.return_value = mock_response

    messages = [{"role": "user", "content": "Hello"}]
    result = llm_client.chat_completion(messages)

    assert result["content"] == "Test response"
    assert result["model"] == "gpt-4"
    assert result["usage"]["total_tokens"] == 30
    assert result["finish_reason"] == "stop"

    mock_completion.assert_called_once()


def test_validate_messages(llm_client: LLMClient) -> None:
    valid = [
        {"role": "system", "content": "You are helpful"},
        {"role": "user", "content": "Hello"},
    ]
    assert llm_client.validate_messages(valid) is True

    # Invalid: empty list
    assert llm_client.validate_messages([]) is False

    # Invalid: missing role
    invalid1 = [{"content": "Hello"}]
    assert llm_client.validate_messages(invalid1) is False

    # Invalid: missing content
    invalid2 = [{"role": "user"}]
    assert llm_client.validate_messages(invalid2) is False

    # Invalid: bad role
    invalid3 = [{"role": "invalid", "content": "Hello"}]
    assert llm_client.validate_messages(invalid3) is False


def test_count_tokens(llm_client: LLMClient) -> None:
    text = "This is a test message for token counting."

    count = llm_client.count_tokens(text)
    assert isinstance(count, int)
    assert count > 0

    long_text = text * 10
    long_count = llm_client.count_tokens(long_text)
    assert long_count > count


@patch("litellm.completion")
def test_llm_client_handles_errors(mock_completion: MagicMock, llm_client: LLMClient) -> None:
    """Test that client handles API errors."""
    mock_completion.side_effect = Exception("API Error")

    messages = [{"role": "user", "content": "Hello"}]

    with pytest.raises(LLMError, match="LLM API call failed"):
        llm_client.chat_completion(messages)


@patch("litellm.completion")
def test_llm_client_custom_temperature(
    mock_completion: MagicMock, llm_client: LLMClient
) -> None:
    """Test using custom temperature."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "Response"
    mock_response.choices[0].finish_reason = "stop"
    mock_response.model = "gpt-4"
    mock_response.usage.prompt_tokens = 10
    mock_response.usage.completion_tokens = 20
    mock_response.usage.total_tokens = 30

    mock_completion.return_value = mock_response

    messages = [{"role": "user", "content": "Hello"}]
    llm_client.chat_completion(messages, temperature=0.8)

    call_args = mock_completion.call_args
    assert call_args[1]["temperature"] == 0.8


@patch("litellm.completion")
def test_llm_client_streaming(mock_completion: MagicMock, llm_client: LLMClient) -> None:
    """Test streaming completion."""
    chunk1 = MagicMock()
    chunk1.choices = [MagicMock()]
    chunk1.choices[0].delta.content = "Hello "
    chunk1.choices[0].finish_reason = None
    chunk1.model = "gpt-4"

    chunk2 = MagicMock()
    chunk2.choices = [MagicMock()]
    chunk2.choices[0].delta.content = "world"
    chunk2.choices[0].finish_reason = "stop"
    chunk2.model = "gpt-4"

    mock_completion.return_value = [chunk1, chunk2]

    messages = [{"role": "user", "content": "Hello"}]
    chunks_received = []

    def callback(chunk: str) -> None:
        chunks_received.append(chunk)

    result = llm_client.chat_completion(messages, stream=True, stream_callback=callback)

    assert result["content"] == "Hello world"
    assert result["finish_reason"] == "stop"
    assert chunks_received == ["Hello ", "world"]
