"""Evidence passages: split sources into short spans, embed them, and keep them in step.

A passage is what a report sentence cites and what retrieval returns, so each one should
read on its own: passages follow paragraph and bullet boundaries, stay under MAX_CHARS, and
carry the heading of the section they came from ("Responsibilities: ...").

Indexing is incremental. A source is re-chunked only when its text or the chunking rules
change, and re-embedded only when the embedding model changes; everything else is skipped.
Sources that stop being evidence (a posting that ages out of the window or turns out to be
a duplicate) lose their passages, so the index always matches what reports may cite.
"""

import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import delete, select

from firstweek_core.db import EMBEDDING_DIM
from firstweek_core.db.models import EvidencePassage, JobPosting, Source
from firstweek_core.db.session import session_scope
from firstweek_core.llm import LLMGateway
from firstweek_research.clean import content_hash
from firstweek_research.sources.web import is_excluded
from firstweek_research.stats import window_start

MAX_CHARS = 900  # about 200 tokens: precise enough to cite, well inside the model's 512
CHUNKER_VERSION = 3  # raise when the splitting rules change, so every source is re-chunked
MIN_WORDS = 8  # shorter passages are leftovers ("Location: #LI-Remote"), not evidence
EMBED_BATCH = 64  # passages per embedding call and per database commit
WEB_TIERS = ("blog", "forum", "interview")  # evidence that is not a job posting
_MAX_HEADING = 80

_MD_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*$")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")

# Markdown that web pages arrive in (via Firecrawl) but a reader of evidence never sees.
_IMAGE = re.compile(r"!\[[^\]\n]*\]\([^)\n]*\)")
_LINK = re.compile(r"\[([^\]\n]*)\]\([^)\n]*\)")
_URL = re.compile(r"(?:https?://|www\.)\S+")
_HTML_TAG = re.compile(r"</?[A-Za-z][^>\n]*>")
_ESCAPE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!|>])")
_BULLET = re.compile(r"^[ \t]*[*+][ \t]+", flags=re.MULTILINE)
_STRONG = re.compile(r"\*\*|`")
# Hacker News comments arrive as table rows: "| | | user 11 months ago | parent | next [-]Text".
_COMMENT_CHROME = re.compile(
    r"^(?:\|\s*)+[\w.-]+ \d+ \w+ ago(?:\s*\|\s*[a-z]+(?::[^|]*)?(?:\s?\[[\u2013+-]\])?)*",
    flags=re.MULTILINE,
)
_EMPHASIS = re.compile(r"(?<![\w*_])([*_])(?![\s*_])(.+?)(?<![\s*_])\1(?![\w*_])")


def readable(text: str) -> str:
    """The words a person reads on the page: images and bare URLs go, links become their
    text, emphasis markers and HTML tags are dropped. A URL in an image name or link is not
    evidence, and it made keyword search match passages that never mention the term."""
    # Escaped characters ("snake\\_case") are literal: park them while markers are removed.
    text = _ESCAPE.sub(lambda m: f"\x00{ord(m.group(1))}\x01", text)
    text = _IMAGE.sub("", text)
    text = _LINK.sub(lambda m: m.group(1), text)
    text = _URL.sub("", text)
    text = _HTML_TAG.sub("", text)
    text = _COMMENT_CHROME.sub("", text)
    text = _BULLET.sub("- ", text)
    text = _STRONG.sub("", text)
    text = _EMPHASIS.sub(lambda m: m.group(2), text)
    text = re.sub("\x00(\\d+)\x01", lambda m: chr(int(m.group(1))), text)
    return "\n".join(re.sub(r"[ \t]{2,}", " ", line).strip() for line in text.splitlines())


def _heading(line: str) -> str | None:
    """'## What you'll do' (markdown and cleaned postings), or a short plain-text heading
    such as 'WHO WE ARE' or 'Responsibilities:'. The rule matches clean.py's."""
    if m := _MD_HEADING.match(line):
        return m.group(1).strip().rstrip(":").strip()[:_MAX_HEADING]
    plain = 0 < len(line) <= 60 and not line.startswith(("- ", "* "))
    if plain and (line.isupper() or line.endswith(":")):
        return line.rstrip(":").strip()
    return None


def _paragraphs(text: str) -> list[tuple[str, str]]:
    """(heading, paragraph) pairs. Blank lines end a paragraph; a heading line ends one too."""
    units: list[tuple[str, str]] = []
    heading = ""
    lines: list[str] = []
    for raw in [*text.splitlines(), ""]:
        line = raw.strip()
        found = _heading(line) if line else None
        if (not line or found is not None) and lines:
            units.append((heading, "\n".join(lines)))
            lines = []
        if found is not None:
            heading = found
        elif line:
            lines.append(line)
    return units


def _split_long(block: str, max_chars: int) -> list[str]:
    """A paragraph over the limit splits at line breaks (bullets), then at sentence ends,
    and only as a last resort mid-sentence."""
    if len(block) <= max_chars:
        return [block]
    parts: list[tuple[str, str]] = []  # (separator before it, text)
    for line in block.splitlines():
        sep = "\n"
        for sentence in _SENTENCE_END.split(line) if len(line) > max_chars else [line]:
            for i in range(0, len(sentence), max_chars):
                parts.append((sep, sentence[i : i + max_chars]))
                sep = " "
    pieces: list[str] = []
    current = ""
    for sep, part in parts:
        if current and len(current) + len(sep) + len(part) > max_chars:
            pieces.append(current)
            current = ""
        current = f"{current}{sep}{part}" if current else part
    if current:
        pieces.append(current)
    return pieces


def chunk_text(text: str, max_chars: int = MAX_CHARS) -> list[str]:
    """Paragraph-aware passages of readable text; each starts with the heading of its first
    section. Passages under MIN_WORDS words are dropped."""
    units = [
        (heading, piece)
        for heading, para in _paragraphs(readable(text))
        for piece in _split_long(para, max_chars - (len(heading) + 2 if heading else 0))
    ]
    passages: list[str] = []
    current, current_heading = "", ""
    for heading, piece in units:
        # "Requirements:" then its bullets on their own lines; "About us: We ..." for prose.
        label = (f"{heading}:\n" if piece.startswith("- ") else f"{heading}: ") if heading else ""
        if current and len(current) + 2 + len(label) + len(piece) > max_chars:
            passages.append(current)
            current = ""
        if not current:
            current = label + piece
        elif heading != current_heading:
            current += f"\n\n{label}{piece}"
        else:
            current += f"\n\n{piece}"
        current_heading = heading
    if current:
        passages.append(current)
    return [p for p in passages if len(re.findall(r"\w+", p)) >= MIN_WORDS]


def passage_key(text: str) -> str:
    """Changes when the text or the way it is cut up changes: either means new passages."""
    return content_hash(f"chunker-v{CHUNKER_VERSION}/{MAX_CHARS}\n{text}")


def check_width(vectors: list[list[float]], model: str) -> None:
    """The database stores vectors of one width; another model's vectors cannot go in it."""
    if vectors and len(vectors[0]) != EMBEDDING_DIM:
        raise ValueError(
            f"MODEL_EMBEDDING={model} makes {len(vectors[0])}-wide vectors, but the database "
            f"stores {EMBEDDING_DIM}. Set MODEL_EMBEDDING=local/BAAI/bge-small-en-v1.5 in .env "
            "(or delete the line): see .env.example."
        )


@dataclass(frozen=True)
class _Doc:
    source_id: uuid.UUID
    text: str


@dataclass
class IndexSummary:
    model: str
    sources: int = 0
    unchanged: int = 0
    indexed: int = 0
    passages_added: int = 0
    sources_removed: int = 0


def _documents() -> list[_Doc]:
    """Postings contribute their role text (boilerplate already removed), and only while they
    can be in a sample: full text, not a duplicate, seen inside the window. Blogs, forums and
    interviews contribute their cleaned content, unless their site is excluded."""
    with session_scope() as session:
        postings = session.execute(
            select(JobPosting.source_id, JobPosting.text).where(
                JobPosting.is_full_text.is_(True),
                JobPosting.is_duplicate.is_(False),
                JobPosting.last_seen_at >= window_start(),
            )
        ).all()
        pages = [
            (sid, content)
            for sid, content, url in session.execute(
                select(Source.id, Source.content, Source.url).where(Source.tier.in_(WEB_TIERS))
            )
            if not is_excluded(url)  # collected before its site was excluded
        ]
    return [_Doc(sid, text) for sid, text in [*postings, *pages] if text and text.strip()]


async def index_evidence(
    gateway: LLMGateway,
    *,
    progress: Callable[[str], None] | None = None,
) -> IndexSummary:
    report = progress or (lambda _: None)
    model = gateway.model_for("embedding")
    docs = _documents()
    summary = IndexSummary(model=model, sources=len(docs))

    with session_scope() as session:
        state: dict[uuid.UUID, set[tuple[str, str | None]]] = {}
        for sid, h, m in session.execute(
            select(
                EvidencePassage.source_id,
                EvidencePassage.source_hash,
                EvidencePassage.embedding_model,
            )
        ):
            state.setdefault(sid, set()).add((h, m))
        gone = set(state) - {d.source_id for d in docs}
        if gone:
            session.execute(delete(EvidencePassage).where(EvidencePassage.source_id.in_(gone)))
        summary.sources_removed = len(gone)

    todo: list[tuple[_Doc, str, list[str]]] = []
    for doc in docs:
        h = passage_key(doc.text)
        if state.get(doc.source_id) == {(h, model)}:
            summary.unchanged += 1
        elif chunks := chunk_text(doc.text):  # headings only: nothing to cite
            todo.append((doc, h, chunks))
    report(
        f"Indexing evidence with {model}: {len(todo)} of {len(docs)} sources are new or "
        f"changed ({sum(len(c) for _, _, c in todo):,} passages)..."
    )

    # Whole sources per batch, saved as each batch finishes: an interrupted run keeps what
    # it embedded, and a source is never left half-indexed.
    batch: list[tuple[_Doc, str, list[str]]] = []
    for i, item in enumerate(todo, 1):
        batch.append(item)
        if sum(len(c) for _, _, c in batch) < EMBED_BATCH and i < len(todo):
            continue
        texts = [t for _, _, chunks in batch for t in chunks]
        embedded = await gateway.embed(texts, kind="passage", purpose="embed-passages")
        check_width(embedded, model)
        vectors = iter(embedded)
        with session_scope() as session:
            for doc, h, chunks in batch:
                session.execute(
                    delete(EvidencePassage).where(EvidencePassage.source_id == doc.source_id)
                )
                session.add_all(
                    EvidencePassage(
                        source_id=doc.source_id,
                        ordinal=ordinal,
                        text=text,
                        embedding=next(vectors),
                        embedding_model=model,
                        source_hash=h,
                    )
                    for ordinal, text in enumerate(chunks)
                )
        summary.indexed += len(batch)
        summary.passages_added += len(texts)
        report(f"  {summary.indexed}/{len(todo)} sources indexed")
        batch = []
    return summary
