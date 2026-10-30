"""Text extraction for supported resume file formats."""

from dataclasses import dataclass
from io import BytesIO
from zipfile import BadZipFile, ZipFile

from docx import Document
from pypdf import PdfReader

MAX_PDF_PAGES = 100
MAX_DOCX_UNPACKED_BYTES = 20 * 1024 * 1024
MAX_EXTRACTED_CHARS = 100_000


class ResumeParseError(ValueError):
    """Raised when a resume file is invalid or has no extractable text."""


@dataclass(frozen=True)
class ParsedResume:
    """Normalized extracted text and content type."""

    text: str
    content_type: str


def parse_resume(data: bytes, extension: str) -> ParsedResume:
    """Extract text from a PDF or DOCX document and enforce parser limits."""

    if extension == ".pdf":
        text = _extract_pdf(data)
        content_type = "application/pdf"
    elif extension == ".docx":
        text = _extract_docx(data)
        content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    else:
        raise ResumeParseError("仅支持 PDF 或 DOCX 简历")

    normalized = "\n".join(line.strip() for line in text.splitlines()).strip()
    normalized = "".join(character for character in normalized if character in "\n\t" or ord(character) >= 32)
    if not normalized:
        raise ResumeParseError("文件中没有可提取的文本，请粘贴简历内容")
    if len(normalized) > MAX_EXTRACTED_CHARS:
        raise ResumeParseError("简历文本超过 100,000 字符限制")
    return ParsedResume(text=normalized, content_type=content_type)


def _extract_pdf(data: bytes) -> str:
    if not data.startswith(b"%PDF-"):
        raise ResumeParseError("文件内容不是有效的 PDF")
    try:
        reader = PdfReader(BytesIO(data), strict=True)
        if reader.is_encrypted:
            raise ResumeParseError("暂不支持加密 PDF")
        if len(reader.pages) > MAX_PDF_PAGES:
            raise ResumeParseError("PDF 页数不能超过 100 页")
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except ResumeParseError:
        raise
    except Exception as exc:
        raise ResumeParseError("PDF 解析失败，请确认文件未损坏") from exc


def _extract_docx(data: bytes) -> str:
    try:
        with ZipFile(BytesIO(data)) as archive:
            names = set(archive.namelist())
            if "word/document.xml" not in names:
                raise ResumeParseError("文件内容不是有效的 DOCX")
            if len(names) > 2_000 or sum(item.file_size for item in archive.infolist()) > MAX_DOCX_UNPACKED_BYTES:
                raise ResumeParseError("DOCX 解压后内容超过安全限制")
        document = Document(BytesIO(data))
    except ResumeParseError:
        raise
    except (BadZipFile, KeyError, ValueError, OSError) as exc:
        raise ResumeParseError("DOCX 解析失败，请确认文件未损坏") from exc

    paragraphs = [paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]
    for table in document.tables:
        for row in table.rows:
            paragraphs.append("\t".join(cell.text.strip() for cell in row.cells))
    return "\n".join(paragraphs)
