"""Turn posting HTML into plain text, then drop the parts that say nothing about the role.

Two texts are kept per posting:
- full text: everything readable, used to verify quotes and as the stored source
- role text: full text minus benefits, company blurbs and legal notices, used for extraction
"""

import hashlib
import re
from dataclasses import dataclass

from bs4 import BeautifulSoup, NavigableString, Tag

_BLOCK_TAGS = {"p", "div", "section", "article", "ul", "ol", "table", "tr", "blockquote", "br"}
_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}

# Section headings whose content is not about the work itself.
# Tuned on real UK AI postings (2026-10-31): see test_real_world_boilerplate_headings.
_BOILERPLATE_HEADING = re.compile(
    r"benefit|perk|what we offer|we offer|what('s| is) in it for you|^why\b|"
    r"compensation|salary|\bpay\b|equal opportunit|diversity|inclusion|\beeo\b|"
    r"accommodation|adjustment|privacy|how to apply|application process|recruit|"
    r"interview|sponsorship|\bvisa\b|compliance|global structure|more about|"
    r"join (the|our) team at|join us|flexible working|\bculture\b|"
    r"(our|the) (mission|values|story)|life at|working at|who (we are|are we)",
    re.IGNORECASE,
)
_ABOUT_HEADING = re.compile(r"^about\b", re.IGNORECASE)
_ABOUT_THE_WORK = re.compile(r"\b(role|team|position|job|you|work|opportunity)\b", re.IGNORECASE)

# Sentences that are legal or HR boilerplate wherever they appear.
_BOILERPLATE_LINE = re.compile(
    r"equal opportunit|regardless of (race|age|gender)|protected (characteristic|veteran)|"
    r"reasonable (adjustment|accommodation)|privacy (notice|policy)|right to work in|"
    r"we (are|'re) committed to (building|creating|fostering) an? (diverse|inclusive)",
    re.IGNORECASE,
)


def _mark(tag: Tag, prefix: str = "", suffix: str = "\n") -> None:
    tag.insert_before(NavigableString(f"\n{prefix}"))
    tag.insert_after(NavigableString(suffix))


def _looks_like_heading(tag: Tag) -> bool:
    """<p><strong>What you'll do</strong></p> is a heading in most posting editors."""
    text = tag.get_text(" ", strip=True)
    if not text or len(text) > 80:
        return False
    strong = tag.find(["strong", "b"])
    return strong is not None and strong.get_text(" ", strip=True) == text


def html_to_text(raw_html: str) -> str:
    soup = BeautifulSoup(raw_html, "html.parser")
    for junk in soup(["script", "style", "noscript"]):
        junk.decompose()
    for tag in soup.find_all(True):
        if tag.name in _HEADING_TAGS or (tag.name == "p" and _looks_like_heading(tag)):
            _mark(tag, "## ")
        elif tag.name == "li":
            _mark(tag, "- ")
        elif tag.name in _BLOCK_TAGS:
            _mark(tag)
    return normalize_whitespace(soup.get_text())


def normalize_whitespace(text: str) -> str:
    lines = [re.sub("[ \t\u00a0]+", " ", line).strip() for line in text.splitlines()]
    lines = [re.sub(r"^(- |## )\s*(•|·|\*|-)\s*", r"\1", line) for line in lines]
    lines = [line for line in lines if line not in {"-", "##"}]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _is_heading(line: str) -> bool:
    if line.startswith("## "):
        return True
    # Plain-text headings: 'WHO ARE WE?' or 'Responsibilities:'
    short = 0 < len(line) <= 60 and not line.startswith("- ")
    return short and (line.isupper() or line.endswith(":"))


def _heading_text(line: str) -> str:
    return line.removeprefix("## ").rstrip(":").strip()


def _drop_section(heading: str) -> bool:
    if _BOILERPLATE_HEADING.search(heading):
        return True
    return bool(_ABOUT_HEADING.search(heading) and not _ABOUT_THE_WORK.search(heading))


@dataclass(frozen=True)
class CleanResult:
    full_text: str
    role_text: str
    dropped_headings: tuple[str, ...]


def strip_boilerplate(text: str) -> CleanResult:
    kept: list[str] = []
    dropped: list[str] = []
    skipping = False
    for line in text.splitlines():
        if _is_heading(line):
            heading = _heading_text(line)
            skipping = _drop_section(heading)
            if skipping:
                dropped.append(heading)
                continue
        if skipping or _BOILERPLATE_LINE.search(line):
            continue
        kept.append(line)
    role_text = normalize_whitespace("\n".join(kept))
    return CleanResult(full_text=text, role_text=role_text, dropped_headings=tuple(dropped))


def clean_posting(body_html: str | None, body_text: str | None) -> CleanResult:
    text = html_to_text(body_html) if body_html else normalize_whitespace(body_text or "")
    return strip_boilerplate(text)


def content_hash(text: str) -> str:
    return hashlib.sha256(normalize_whitespace(text).encode("utf-8")).hexdigest()
