"""Tests for converter.py — one test class per supported format, plus error cases."""

import pytest

from mcpvectordb.converter import convert
from mcpvectordb.exceptions import UnsupportedFormatError


class TestPDFConverter:
    """Tests for PDF → Markdown conversion."""

    @pytest.mark.integration
    def test_converts_to_markdown(self, sample_pdf):
        """PDF fixture converts to a non-empty string."""
        result = convert(sample_pdf)
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.integration
    def test_returns_string_type(self, sample_pdf):
        """Return type is str, not bytes."""
        result = convert(sample_pdf)
        assert isinstance(result, str)


class TestDocxConverter:
    """Tests for DOCX → Markdown conversion."""

    @pytest.mark.integration
    def test_converts_to_markdown(self, sample_docx):
        """DOCX fixture converts to a non-empty string."""
        result = convert(sample_docx)
        assert isinstance(result, str)
        assert len(result) > 0


class TestPptxConverter:
    """Tests for PPTX → Markdown conversion."""

    @pytest.mark.integration
    def test_converts_to_markdown(self, sample_pptx):
        """PPTX fixture converts to a non-empty string."""
        result = convert(sample_pptx)
        assert isinstance(result, str)
        assert len(result) > 0


class TestXlsxConverter:
    """Tests for XLSX → Markdown conversion."""

    @pytest.mark.integration
    def test_converts_to_markdown(self, sample_xlsx):
        """XLSX fixture converts to a non-empty string."""
        result = convert(sample_xlsx)
        assert isinstance(result, str)
        assert len(result) > 0


class TestHtmlConverter:
    """Tests for HTML → Markdown conversion."""

    @pytest.mark.integration
    def test_converts_to_markdown(self, sample_html):
        """HTML fixture converts to a non-empty string."""
        result = convert(sample_html)
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.integration
    def test_html_heading_extracted(self, sample_html):
        """HTML fixture contains the heading text from the sample file."""
        result = convert(sample_html)
        assert "Sample" in result


class TestImageConverter:
    """Tests for image → Markdown conversion (OCR — slow)."""

    @pytest.mark.slow
    @pytest.mark.integration
    def test_converts_to_markdown(self, sample_image):
        """Image fixture produces a (possibly empty) string without error."""
        result = convert(sample_image)
        assert isinstance(result, str)


class TestAudioConverter:
    """Tests for audio → Markdown transcription (slow)."""

    @pytest.mark.slow
    @pytest.mark.integration
    def test_converts_to_markdown(self, sample_audio):
        """Audio fixture produces a string without error."""
        result = convert(sample_audio)
        assert isinstance(result, str)


class TestUnsupportedFormat:
    """Tests that unsupported extensions raise UnsupportedFormatError."""

    @pytest.mark.unit
    def test_raises_for_unknown_extension(self, tmp_path):
        """Files with unrecognised extensions raise UnsupportedFormatError."""
        bad_file = tmp_path / "file.xyz"
        bad_file.write_text("content")
        with pytest.raises(UnsupportedFormatError, match=r"\.xyz"):
            convert(bad_file)

    @pytest.mark.unit
    def test_raises_for_exe_extension(self, tmp_path):
        """Executable files raise UnsupportedFormatError."""
        bad_file = tmp_path / "program.exe"
        bad_file.write_bytes(b"\x00\x01\x02")
        with pytest.raises(UnsupportedFormatError):
            convert(bad_file)

    @pytest.mark.unit
    def test_error_message_contains_extension(self, tmp_path):
        """Error message includes the unsupported extension."""
        bad_file = tmp_path / "data.foobar"
        bad_file.write_text("x")
        with pytest.raises(UnsupportedFormatError, match=r"\.foobar"):
            convert(bad_file)
