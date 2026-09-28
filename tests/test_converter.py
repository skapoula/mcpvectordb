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

    @pytest.mark.integration
    def test_keeps_page_breaks(self, sample_pdf_2pages):
        """PDF text keeps form-feed page breaks so pages can be numbered."""
        pages = convert(sample_pdf_2pages).split("\x0c")
        assert "alpha quantum" in pages[0]
        assert "beta lattice" in pages[1]


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


class TestFormatsWithoutUsableText:
    """Formats MarkItDown cannot turn into text here are rejected up front."""

    @pytest.mark.unit
    def test_image_rejected_with_ocr_hint(self, sample_image):
        """Images carry no text without OCR, so they are refused, not indexed empty."""
        with pytest.raises(UnsupportedFormatError, match="OCR"):
            convert(sample_image)

    @pytest.mark.unit
    def test_audio_rejected_with_privacy_reason(self, sample_audio):
        """Audio transcription would send the file to a cloud service."""
        with pytest.raises(UnsupportedFormatError, match="speech service"):
            convert(sample_audio)

    @pytest.mark.unit
    @pytest.mark.parametrize(("ext", "modern"), [(".doc", ".docx"), (".ppt", ".pptx")])
    def test_legacy_office_rejected_with_resave_hint(self, tmp_path, ext, modern):
        """Legacy Office files have no converter; the error names the fix."""
        f = tmp_path / f"old{ext}"
        f.write_bytes(b"\xd0\xcf\x11\xe0")  # OLE2 header
        with pytest.raises(UnsupportedFormatError, match=modern):
            convert(f)

    @pytest.mark.unit
    def test_zip_with_audio_rejected(self, tmp_path, sample_audio):
        """A ZIP would transcribe audio members through the cloud; refuse it."""
        import zipfile

        archive = tmp_path / "bundle.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("notes.txt", "hello")
            zf.write(sample_audio, "Voice Memo.MP3")
        with pytest.raises(UnsupportedFormatError, match="Voice Memo.MP3"):
            convert(archive)


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
