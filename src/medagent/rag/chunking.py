import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class TextChunk:
    content: str
    section: str | None = None
    page_number: int | None = None
    metadata: dict = field(default_factory=dict)


SECTION_RE = re.compile(r"^(#{1,6}\s+.+|[0-9]+(?:\.[0-9]+)*\s+.+)$")
PAGE_MARKER_RE = re.compile(r"^\s*(?:page|p\.|第)\s*(\d+)\s*(?:页)?\s*$", re.IGNORECASE)


def chunk_text(
    text: str,
    *,
    chunk_size: int = 1800,
    overlap: int = 180,
) -> list[TextChunk]:
    normalized = normalize_text(text)
    if not normalized:
        return []

    paragraphs = split_paragraphs(normalized)
    chunks: list[TextChunk] = []
    current: list[str] = []
    current_len = 0
    section: str | None = None
    page_number: int | None = None

    for paragraph in paragraphs:
        detected_page = detect_page_number(paragraph)
        if detected_page is not None:
            page_number = detected_page
            continue

        detected_section = detect_section(paragraph)
        if detected_section is not None:
            section = detected_section

        if len(paragraph) > chunk_size:
            if current:
                chunks.append(build_chunk(current, section, page_number))
                current, current_len = overlap_tail(current, overlap)
            chunks.extend(split_long_paragraph(paragraph, section, page_number, chunk_size, overlap))
            continue

        extra_len = len(paragraph) + (2 if current else 0)
        if current and current_len + extra_len > chunk_size:
            chunks.append(build_chunk(current, section, page_number))
            current, current_len = overlap_tail(current, overlap)

        current.append(paragraph)
        current_len += extra_len

    if current:
        chunks.append(build_chunk(current, section, page_number))

    return [chunk for chunk in chunks if chunk.content.strip()]


def normalize_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"[ \t]+", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def split_paragraphs(text: str) -> list[str]:
    paragraphs = []
    for block in re.split(r"\n\s*\n", text):
        cleaned = " ".join(line.strip() for line in block.splitlines() if line.strip())
        if cleaned:
            paragraphs.append(cleaned)
    return paragraphs


def detect_section(paragraph: str) -> str | None:
    if len(paragraph) > 160:
        return None
    match = SECTION_RE.match(paragraph)
    if not match:
        return None
    return paragraph.lstrip("#").strip()


def detect_page_number(paragraph: str) -> int | None:
    match = PAGE_MARKER_RE.match(paragraph)
    if not match:
        return None
    return int(match.group(1))


def split_long_paragraph(
    paragraph: str,
    section: str | None,
    page_number: int | None,
    chunk_size: int,
    overlap: int,
) -> list[TextChunk]:
    chunks = []
    start = 0
    while start < len(paragraph):
        end = min(start + chunk_size, len(paragraph))
        content = paragraph[start:end].strip()
        if content:
            chunks.append(TextChunk(content=content, section=section, page_number=page_number))
        if end == len(paragraph):
            break
        start = max(end - overlap, start + 1)
    return chunks


def build_chunk(paragraphs: list[str], section: str | None, page_number: int | None) -> TextChunk:
    content = "\n\n".join(paragraphs).strip()
    return TextChunk(
        content=content,
        section=section,
        page_number=page_number,
        metadata={"paragraph_count": len(paragraphs)},
    )


def overlap_tail(paragraphs: list[str], overlap: int) -> tuple[list[str], int]:
    if overlap <= 0:
        return [], 0
    tail: list[str] = []
    tail_len = 0
    for paragraph in reversed(paragraphs):
        if tail and tail_len + len(paragraph) > overlap:
            break
        tail.insert(0, paragraph)
        tail_len += len(paragraph)
    return tail, tail_len
