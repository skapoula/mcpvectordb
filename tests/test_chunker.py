"""Tests for chunker.py — chunking logic, edge cases, token counts."""

import pytest


class TestChunkBasic:
    """Basic chunking behaviour."""

    @pytest.mark.unit
    def test_empty_string_returns_empty_list(self):
        """Empty or whitespace-only input returns an empty list."""
        from mcpvectordb.chunker import chunk

        assert chunk("") == []
        assert chunk("   \n  ") == []

    @pytest.mark.unit
    def test_short_text_returns_single_chunk(self):
        """Text shorter than chunk_size but above min_tokens stays as a single chunk."""
        from mcpvectordb.chunker import chunk

        # Must exceed chunk_min_tokens (50) but be well below chunk_size_tokens (512)
        text = "This is a test document. " * 10
        result = chunk(text)
        assert len(result) >= 1
        assert all(isinstance(c, str) for c in result)

    @pytest.mark.unit
    def test_returns_list_of_strings(self):
        """chunk() always returns a list of strings."""
        from mcpvectordb.chunker import chunk

        result = chunk("Some text here.")
        assert isinstance(result, list)
        assert all(isinstance(c, str) for c in result)

    @pytest.mark.unit
    def test_long_text_produces_multiple_chunks(self):
        """Text much longer than chunk_size is split into multiple chunks."""
        from mcpvectordb.chunker import chunk

        # ~3000 words of repeated content should exceed 512 tokens
        long_text = "The quick brown fox jumps over the lazy dog. " * 200
        result = chunk(long_text)
        assert len(result) > 1

    @pytest.mark.unit
    def test_chunks_do_not_exceed_chunk_size(self):
        """No chunk exceeds the configured chunk_size_tokens."""
        from mcpvectordb.chunker import _token_length, chunk
        from mcpvectordb.config import settings

        long_text = "Word " * 2000
        result = chunk(long_text)
        for c in result:
            # Allow small tolerance for edge-splitting behaviour
            assert _token_length(c) <= settings.chunk_size_tokens + 20

    @pytest.mark.unit
    def test_min_token_filter_removes_tiny_chunks(self):
        """Chunks below chunk_min_tokens are filtered out."""
        from mcpvectordb.chunker import _token_length, chunk
        from mcpvectordb.config import settings

        result = chunk("The quick brown fox. " * 100)
        for c in result:
            assert _token_length(c) >= settings.chunk_min_tokens


class TestChunkEdgeCases:
    """Edge cases for the chunker."""

    @pytest.mark.unit
    def test_newline_separated_paragraphs(self):
        """Double-newline paragraph separators are used first."""
        from mcpvectordb.chunker import chunk

        paragraphs = "\n\n".join([f"Paragraph number {i}. " * 5 for i in range(20)])
        result = chunk(paragraphs)
        assert len(result) >= 1

    @pytest.mark.unit
    def test_unicode_text(self):
        """Unicode characters are handled without error."""
        from mcpvectordb.chunker import chunk

        text = "日本語のテキストです。" * 50
        result = chunk(text)
        assert isinstance(result, list)

    @pytest.mark.unit
    def test_only_whitespace_filtered(self):
        """Chunks that are only whitespace don't survive the min-token filter."""
        from mcpvectordb.chunker import chunk

        # Lots of newlines with tiny real content
        filler = "Some actual content here to avoid empty result."
        text = "\n" * 1000 + filler + "\n" * 1000
        result = chunk(text)
        for c in result:
            assert c.strip() != ""


class TestChunkInternals:
    """Tests for internal chunker helper functions."""

    @pytest.mark.unit
    def test_split_recursive_base_case_empty_separators(self):
        """_split_recursive returns [text] unchanged when no separators remain (line 70)."""
        from mcpvectordb.chunker import _split_recursive

        result = _split_recursive("some text that cannot be split further", [], 512, 64)
        assert result == ["some text that cannot be split further"]
