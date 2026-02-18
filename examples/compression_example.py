"""Example: Using Context Compression in sago

This example demonstrates how to use sago's context compression features
to reduce LLM token usage and costs.
"""

from sago.utils.compression import ContextManager, LLMLinguaCompressor, SlidingWindowCompressor


def example_1_automatic_compression() -> None:
    """Example 1: Automatic compression when threshold is exceeded."""
    print("=" * 60)
    print("Example 1: Automatic Compression")
    print("=" * 60)

    # Create context manager with low threshold for demo
    manager = ContextManager(
        max_context_tokens=200,  # Small limit for demo
        compression_threshold=0.5,  # Compress when > 100 tokens
        default_compressor="sliding_window",  # Safe default (no external deps)
    )

    # Short text - won't trigger compression
    short_text = "This is a short message."
    result = manager.auto_compress(short_text)

    print(f"\nShort text compression:")
    print(f"  Method: {result.method}")
    print(f"  Original tokens: {result.original_tokens}")
    print(f"  Compressed tokens: {result.compressed_tokens}")
    print(f"  Savings: {result.percentage_saved:.1f}%")

    # Long text - will trigger compression
    long_text = "\n\n".join([f"Paragraph {i}: " + "x" * 100 for i in range(10)])
    result = manager.auto_compress(long_text)

    print(f"\nLong text compression:")
    print(f"  Method: {result.method}")
    print(f"  Original tokens: {result.original_tokens}")
    print(f"  Compressed tokens: {result.compressed_tokens}")
    print(f"  Savings: {result.percentage_saved:.1f}%")
    print(f"  Cost reduction: ~${result.token_savings * 0.00003:.4f} @ $30/1M tokens")


def example_2_sliding_window() -> None:
    """Example 2: Sliding window for conversation history."""
    print("\n" + "=" * 60)
    print("Example 2: Sliding Window Compression")
    print("=" * 60)

    # Simulate conversation history
    conversation = "\n\n".join(
        [
            "User: Hello, how are you?",
            "Assistant: I'm doing well, thank you!",
            "User: Can you help me with Python?",
            "Assistant: Of course! What do you need help with?",
            "User: I want to learn about lists.",
            "Assistant: Lists are ordered collections...",
            "User: What about dictionaries?",
            "Assistant: Dictionaries are key-value pairs...",
            "User: How do I iterate?",
            "Assistant: You can use for loops...",
        ]
    )

    # Keep only last 4 interactions (2 user + 2 assistant pairs)
    compressor = SlidingWindowCompressor(window_size=4)
    result = compressor.compress(conversation)

    print(f"\nConversation history management:")
    print(f"  Total exchanges: {result.metadata['total_chunks']}")
    print(f"  Kept exchanges: {result.metadata['kept_chunks']}")
    print(f"  Original tokens: {result.original_tokens}")
    print(f"  Compressed tokens: {result.compressed_tokens}")
    print(f"  Savings: {result.percentage_saved:.1f}%")

    print(f"\nCompressed conversation:")
    print(result.compressed_text[:200] + "...")


def example_3_llmlingua_compression() -> None:
    """Example 3: Advanced compression with LLMLingua."""
    print("\n" + "=" * 60)
    print("Example 3: LLMLingua Prompt Compression")
    print("=" * 60)

    try:
        # Create LLMLingua compressor (will download model on first use)
        compressor = LLMLinguaCompressor(
            model_name="microsoft/llmlingua-2-bert-base-multilingual-cased-meetingbank",
            device="cpu",
            target_token_ratio=0.5,  # Compress to 50%
        )

        # Long prompt with instruction and context
        instruction = "Summarize the key points from this project documentation."

        context = """
        The sago project is a comprehensive AI-powered project orchestration tool.
        It provides structured templates for project management including PROJECT.md,
        REQUIREMENTS.md, ROADMAP.md, and STATE.md files. The system uses XML-based
        task decomposition to force atomic, verifiable tasks. It integrates with
        multiple LLM providers through LiteLLM and includes a website blocker for
        focus mode. The architecture is modular with separate modules for core
        functionality, agents, blockers, and utilities. Testing is done with
        pytest and the project requires Python 3.11 or higher. The CLI is built
        with Typer and Rich for beautiful terminal output. Context compression
        helps manage token usage and reduce costs when working with LLMs.
        """

        question = "What are the main features of sago?"

        result = compressor.compress(
            text=context,
            instruction=instruction,
            question=question,
            target_tokens=50,  # Aggressive compression
        )

        print(f"\nPrompt compression with LLMLingua:")
        print(f"  Original tokens: {result.original_tokens}")
        print(f"  Compressed tokens: {result.compressed_tokens}")
        print(f"  Compression ratio: {result.compression_ratio:.2f}")
        print(f"  Savings: {result.percentage_saved:.1f}%")

        print(f"\nOriginal text ({len(context)} chars):")
        print(context[:150] + "...")

        print(f"\nCompressed text ({len(result.compressed_text)} chars):")
        print(result.compressed_text[:150] + "...")

        # Calculate cost savings (GPT-4 pricing: ~$30/1M input tokens)
        cost_per_token = 0.00003
        original_cost = result.original_tokens * cost_per_token
        compressed_cost = result.compressed_tokens * cost_per_token
        savings = original_cost - compressed_cost

        print(f"\nCost analysis (GPT-4 pricing):")
        print(f"  Original cost: ${original_cost:.6f}")
        print(f"  Compressed cost: ${compressed_cost:.6f}")
        print(f"  Savings per request: ${savings:.6f}")
        print(f"  Savings per 1000 requests: ${savings * 1000:.2f}")

    except ImportError:
        print("\n⚠️  LLMLingua not installed.")
        print("Install with: pip install llmlingua")
    except Exception as e:
        print(f"\n⚠️  Error: {e}")
        print("Note: LLMLingua downloads models on first use (~500MB)")


def example_4_context_manager_strategies() -> None:
    """Example 4: Using ContextManager with different strategies."""
    print("\n" + "=" * 60)
    print("Example 4: Multiple Compression Strategies")
    print("=" * 60)

    manager = ContextManager(max_context_tokens=1000)

    text = """
    This is a sample document that needs compression.
    It contains multiple paragraphs and sentences.
    The content discusses various topics related to programming.
    """ * 20  # Make it longer

    # Compare different strategies
    strategies = ["passthrough", "sliding_window"]

    print(f"\nOriginal text: {len(text)} characters\n")

    for strategy in strategies:
        result = manager.compress(text, strategy=strategy)

        print(f"{strategy.upper()}:")
        print(f"  Compressed tokens: {result.compressed_tokens}")
        print(f"  Compression ratio: {result.compression_ratio:.2f}")
        print(f"  Savings: {result.percentage_saved:.1f}%")
        print()

    # Show manager stats
    stats = manager.get_stats()
    print("Context Manager Configuration:")
    print(f"  Max tokens: {stats['max_context_tokens']}")
    print(f"  Threshold: {stats['compression_threshold']}")
    print(f"  Default: {stats['default_compressor']}")
    print(f"  Available: {', '.join(stats['available_compressors'])}")


def example_5_real_world_usage() -> None:
    """Example 5: Real-world integration with LLM calls."""
    print("\n" + "=" * 60)
    print("Example 5: Real-World LLM Integration")
    print("=" * 60)

    manager = ContextManager(
        max_context_tokens=4000,
        compression_threshold=0.75,
        default_compressor="sliding_window",
    )

    # Simulate accumulating context from multiple sources
    project_docs = "PROJECT.md content here..." * 50
    requirements = "REQUIREMENTS.md content..." * 30
    conversation_history = "Previous chat messages..." * 40

    # Combine all context
    full_context = f"{project_docs}\n\n{requirements}\n\n{conversation_history}"

    print(f"\nAccumulated context: {len(full_context)} characters")
    print(f"Estimated tokens: {len(full_context) // 4}")

    # Check if compression needed
    if manager.should_compress(full_context):
        print("❗ Context exceeds threshold, compressing...")

        result = manager.auto_compress(full_context)

        print(f"\nCompression applied:")
        print(f"  Method: {result.method}")
        print(f"  Before: {result.original_tokens} tokens")
        print(f"  After: {result.compressed_tokens} tokens")
        print(f"  Saved: {result.token_savings} tokens ({result.percentage_saved:.1f}%)")

        # This compressed context can now be safely sent to LLM
        llm_prompt = f"Context: {result.compressed_text}\n\nUser question: What's next?"
        print(f"\n✅ Ready to send to LLM (total: {len(llm_prompt) // 4} tokens)")

    else:
        print("✅ Context within limits, no compression needed")


if __name__ == "__main__":
    """Run all examples."""

    print("\n🚀 sago Context Compression Examples\n")

    # Run examples
    example_1_automatic_compression()
    example_2_sliding_window()
    example_4_context_manager_strategies()
    example_5_real_world_usage()

    # LLMLingua example (requires installation)
    print("\n" + "=" * 60)
    print("Would you like to try LLMLingua compression? (requires installation)")
    print("This will download a ~500MB model on first use.")
    response = input("Run example? [y/N]: ").strip().lower()

    if response == "y":
        example_3_llmlingua_compression()
    else:
        print("\nSkipping LLMLingua example.")
        print("To try it later, install with: pip install llmlingua")

    print("\n" + "=" * 60)
    print("Examples completed!")
    print("=" * 60)
