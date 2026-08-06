"""Cross-provider deduplication.

PubMed and Europe PMC index heavily overlapping corpora, so the same paper
routinely arrives twice with different metadata completeness. Counting it twice
would inflate the apparent weight of evidence, which is a correctness problem,
not a cosmetic one: confidence is derived from source counts and agreement.

Identifiers are matched strongest-first (DOI, then PMID, then PMCID) before
falling back to a normalised title. Records are merged rather than discarded so
the surviving record keeps the most complete metadata available from any source.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from app.models.records import LiteratureRecord, PatentRecord

#: Provider preference when merging. Earlier wins ties on scalar fields.
#: PubMed leads for curated metadata; Europe PMC leads for open-access full text,
#: which is handled separately by always preferring a record that has full text.
_LITERATURE_PRIORITY = ("pubmed", "europepmc", "crossref", "openalex")


def _priority(provider: str) -> int:
    try:
        return _LITERATURE_PRIORITY.index(provider)
    except ValueError:
        return len(_LITERATURE_PRIORITY)


def _identity_keys(record: LiteratureRecord) -> list[str]:
    """Candidate identity keys, strongest first."""
    keys = []
    if record.doi:
        keys.append(f"doi:{record.doi}")
    if record.pmid:
        keys.append(f"pmid:{record.pmid}")
    if record.pmcid:
        keys.append(f"pmcid:{record.pmcid}")
    title = record.normalised_title()
    # Very short titles are too collision-prone to be an identity key on their own.
    if len(title) >= 20:
        keys.append(f"title:{title}")
    return keys


def merge_literature(primary: LiteratureRecord, other: LiteratureRecord) -> LiteratureRecord:
    """Combine two records describing the same work.

    Field-level union: any value present in either record survives. Where both
    have a value, the higher-priority provider wins - except for full text,
    where having the text at all beats provider preference, since that is what
    determines whether we may describe the evidence as full text.
    """
    a, b = (
        (primary, other)
        if _priority(primary.provider) <= _priority(other.provider)
        else (other, primary)
    )

    def pick[T](x: T | None, y: T | None) -> T | None:
        return x if x else y

    full_text = a.full_text or b.full_text

    return LiteratureRecord(
        provider=a.provider,
        title=a.title or b.title,
        abstract=pick(a.abstract, b.abstract),
        authors=a.authors or b.authors,
        journal=pick(a.journal, b.journal),
        publication_date=pick(a.publication_date, b.publication_date),
        publication_year=pick(a.publication_year, b.publication_year),
        doi=pick(a.doi, b.doi),
        pmid=pick(a.pmid, b.pmid),
        pmcid=pick(a.pmcid, b.pmcid),
        url=pick(a.url, b.url),
        publication_types=sorted(set(a.publication_types) | set(b.publication_types)),
        is_preprint=a.is_preprint or b.is_preprint,
        is_open_access=a.is_open_access or b.is_open_access,
        full_text=full_text,
        raw=a.raw,
    )


def deduplicate_literature(
    records: Iterable[LiteratureRecord],
) -> list[LiteratureRecord]:
    """Collapse duplicates, preserving first-seen order.

    Uses union-find style consolidation via a key index: a record matching an
    existing group on *any* of its identity keys joins that group, and merging
    then contributes its own keys to the group so transitive matches work. That
    matters because a PubMed record may share a PMID with one duplicate and a
    DOI with another.
    """
    groups: list[LiteratureRecord] = []
    key_to_group: dict[str, int] = {}

    for record in records:
        keys = _identity_keys(record)
        matched = {key_to_group[k] for k in keys if k in key_to_group}

        if not matched:
            index = len(groups)
            groups.append(record)
            for key in keys:
                key_to_group[key] = index
            continue

        # Merge into the lowest-indexed matching group to preserve input order,
        # then repoint every key of the groups being absorbed.
        target = min(matched)
        merged = groups[target]
        for index in sorted(matched - {target}, reverse=True):
            merged = merge_literature(merged, groups[index])
        merged = merge_literature(merged, record)
        groups[target] = merged

        for key in _identity_keys(merged) + keys:
            key_to_group[key] = target
        for key, index in list(key_to_group.items()):
            if index in matched and index != target:
                key_to_group[key] = target

    return groups


def deduplicate_patents(records: Iterable[PatentRecord]) -> list[PatentRecord]:
    """Collapse patent family members to one representative per family.

    A family is one invention filed in many jurisdictions. Listing every member
    separately would misrepresent a single filing as broad patent activity.

    The representative is chosen deterministically: a granted patent outranks a
    published application, then the earliest priority date, then the lowest
    publication number. Absorbed members' jurisdictions are retained on the
    survivor so family breadth is still visible.
    """
    families: dict[str, PatentRecord] = {}
    members: dict[str, list[str]] = {}

    for record in records:
        key = record.family_key
        members.setdefault(key, []).append(record.publication_number)

        incumbent = families.get(key)
        if incumbent is None or _patent_rank(record) < _patent_rank(incumbent):
            families[key] = record

    result = []
    for key, record in families.items():
        raw = dict(record.raw or {})
        raw["family_members"] = sorted(set(members[key]))
        result.append(record.model_copy(update={"raw": raw}))
    return result


def _patent_rank(record: PatentRecord) -> tuple[int, str, str]:
    """Lower sorts better."""
    granted = 0 if record.record_type.value == "granted_patent" else 1
    priority = record.priority_date.isoformat() if record.priority_date else "9999-99-99"
    return (granted, priority, record.publication_number)


def rank_by_relevance[T: (LiteratureRecord, PatentRecord)](
    records: Sequence[T], scores: dict[str, float]
) -> list[T]:
    """Order records by an externally supplied relevance score, descending.

    Scores come from the agent that assessed the records; unscored records sort
    last rather than being dropped, so nothing silently disappears.
    """

    def key(record: T) -> tuple[float, str]:
        identity = (
            record.publication_number
            if isinstance(record, PatentRecord)
            else (record.doi or record.pmid or record.title)
        )
        return (-scores.get(identity, -1.0), identity or "")

    return sorted(records, key=key)
