"""Find re-posted and syndicated jobs so one opening is counted once.

Recruiters repost the same job, agencies copy it, and one job can arrive from both a
company board and Adzuna. Without this step one employer can skew every statistic.

Method:
- MinHash LSH on word 5-gram shingles finds candidate near-duplicates quickly.
- Each candidate pair is confirmed with exact Jaccard similarity (>= 0.8).
- A ~500-character snippet is compared by containment instead: if 90% of its shingles
  appear in a full posting from the same company and title, it is the same job.
- Groups are formed with union-find. The canonical posting is the full-text one, then the
  earliest posted, then the longest.
"""

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from datasketch import MinHash, MinHashLSH

SHINGLE = 5
JACCARD_THRESHOLD = 0.8
CONTAINMENT_THRESHOLD = 0.9
NUM_PERM = 128


@dataclass(frozen=True)
class DedupDoc:
    id: str
    text: str
    title: str
    company: str | None
    is_full_text: bool
    posted_at: date | None


@dataclass(frozen=True)
class DedupResult:
    group_of: dict[str, str]  # doc id -> group id (the canonical doc's id)
    duplicates: frozenset[str]  # ids that are not their group's canonical doc

    @property
    def group_count(self) -> int:
        return len(set(self.group_of.values()))


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9+#]+", text.lower())


def shingles(text: str, k: int = SHINGLE) -> set[str]:
    words = _tokens(text)
    if len(words) < k:
        return {" ".join(words)} if words else set()
    return {" ".join(words[i : i + k]) for i in range(len(words) - k + 1)}


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def containment(small: set[str], big: set[str]) -> float:
    return len(small & big) / len(small) if small else 0.0


def _key(doc: DedupDoc) -> tuple[str, str]:
    return (" ".join(_tokens(doc.company or "")), " ".join(_tokens(doc.title)))


class _UnionFind:
    def __init__(self, ids: list[str]) -> None:
        self.parent = {i: i for i in ids}

    def find(self, x: str) -> str:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def _rank(doc: DedupDoc) -> tuple[bool, date, int]:
    """Lower sorts first: full text, then earliest, then longest."""
    return (not doc.is_full_text, doc.posted_at or date.max, -len(doc.text))


def find_duplicates(docs: list[DedupDoc]) -> DedupResult:
    by_id = {d.id: d for d in docs}
    sh = {d.id: shingles(d.text) for d in docs}
    uf = _UnionFind(list(by_id))

    lsh = MinHashLSH(threshold=JACCARD_THRESHOLD, num_perm=NUM_PERM)
    for doc_id, s in sh.items():
        if not s:
            continue
        m = MinHash(num_perm=NUM_PERM)
        for shingle in s:
            m.update(shingle.encode("utf-8"))
        for other in lsh.query(m):
            if jaccard(s, sh[other]) >= JACCARD_THRESHOLD:
                uf.union(other, doc_id)
        lsh.insert(doc_id, m)

    # Snippets versus full postings of the same job (same company and title).
    blocks: dict[tuple[str, str], list[DedupDoc]] = defaultdict(list)
    for d in docs:
        blocks[_key(d)].append(d)
    for block in blocks.values():
        snippets = [d for d in block if not d.is_full_text]
        fulls = [d for d in block if d.is_full_text]
        for snip in snippets:
            for full in fulls:
                if containment(sh[snip.id], sh[full.id]) >= CONTAINMENT_THRESHOLD:
                    uf.union(full.id, snip.id)

    members: dict[str, list[DedupDoc]] = defaultdict(list)
    for d in docs:
        members[uf.find(d.id)].append(d)
    group_of: dict[str, str] = {}
    duplicates: set[str] = set()
    for group in members.values():
        canonical = min(group, key=_rank)
        for d in group:
            group_of[d.id] = canonical.id
            if d.id != canonical.id:
                duplicates.add(d.id)
    return DedupResult(group_of=group_of, duplicates=frozenset(duplicates))
