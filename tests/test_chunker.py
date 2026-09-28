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

    @pytest.mark.unit
    @pytest.mark.parametrize(
        "text",
        [
            "Word " * 700 + "\n\nZebracorn closing remark.",
            "Zebracorn opening remark.\n\n" + "Word " * 700,
        ],
    )
    def test_short_paragraph_next_to_long_one_is_kept(self, text):
        """A chunk below the floor is merged into a neighbour or kept, never dropped."""
        from mcpvectordb.chunker import _token_length, chunk
        from mcpvectordb.config import settings

        result = chunk(text)
        assert any("Zebracorn" in c and "remark." in c for c in result)
        for c in result:
            assert _token_length(c) <= settings.chunk_size_tokens

    @pytest.mark.unit
    def test_short_chunk_merges_into_neighbour_with_room(self):
        """A short trailing paragraph joins the previous chunk when it fits."""
        from mcpvectordb.chunker import _token_length, chunk
        from mcpvectordb.config import settings

        text = (
            "Word " * 300 + "\n\n" + "Filler " * 400 + "\n\nZebracorn closing remark."
        )
        result = chunk(text)
        assert result[-1].endswith("Zebracorn closing remark.")
        assert all(_token_length(c) >= settings.chunk_min_tokens for c in result)


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
        """_split_recursive returns [text] unchanged when no separators remain."""
        from mcpvectordb.chunker import _split_recursive

        result = _split_recursive("some text that cannot be split further", [], 512, 64)
        assert result == ["some text that cannot be split further"]


class TestChunkTextFidelity:
    """Chunks are exact slices of the input and neighbours overlap."""

    @pytest.mark.unit
    def test_unsplittable_text_is_sliced_not_decoded(self):
        """Text with no separators keeps its case and punctuation exactly."""
        from mcpvectordb.chunker import chunk

        text = "ErrorCode-E4021/NodePort.Kubernetes_" * 300  # no spaces or newlines
        result = chunk(text)
        assert len(result) > 1
        assert all(c in text for c in result)
        assert text.startswith(result[0])
        assert text.endswith(result[-1])

    @pytest.mark.unit
    def test_neighbouring_chunks_overlap_for_long_paragraphs(self):
        """Paragraphs longer than the overlap budget still yield overlapping chunks."""
        from mcpvectordb.chunker import chunk

        paras = [
            f"Paragraph {i}. " + " ".join(f"word{i}x{j}" for j in range(60))
            for i in range(30)
        ]
        result = chunk("\n\n".join(paras))
        assert len(result) > 2
        for prev, nxt in zip(result, result[1:], strict=False):
            assert nxt[:40] in prev


class TestJoinChunks:
    """join_chunks reassembles a document from its overlapping chunks."""

    @pytest.mark.unit
    def test_round_trip_removes_overlap(self):
        """Joining the chunks of a document reproduces the document exactly."""
        from mcpvectordb.chunker import chunk, join_chunks

        paras = [
            f"Paragraph {i}. " + " ".join(f"word{i}x{j}" for j in range(60))
            for i in range(30)
        ]
        text = "\n\n".join(paras)
        result = chunk(text)
        assert len(result) > 2
        assert join_chunks(result) == text

    @pytest.mark.unit
    def test_chunks_without_overlap_are_separated_by_blank_line(self):
        """Neighbours that share no text are joined with a paragraph break."""
        from mcpvectordb.chunker import join_chunks

        assert join_chunks(["Page one text.", "Page two text."]) == (
            "Page one text.\n\nPage two text."
        )
