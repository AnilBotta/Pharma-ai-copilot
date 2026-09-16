"""Renaming subjects for the invariance tests, without losing any of them.

WHAT THE INVARIANCE TESTS CLAIM

That a regulatory result depends on the subjects, not on how they are spelled.
Anonymise a study before analysis and every quantity must come back identical:
sWR, the treatment contrast, the criterion, the verdict. That property is what
makes a result reproducible from a re-exported file, and it is the reason three
test files rename subjects and compare the whole answer.

WHAT WENT WRONG

All three built the new names with

    f"ANON-{abs(hash(subject_id)) % 99991}"

and that is not a renaming. `hash` is randomised per process, `%` folds its
range, and two of twenty-four subjects landing on one name is not a rare
accident: under PYTHONHASHSEED 280, 372 and 846 the FDA highly-variable fixture
maps `TRR-7` and `RTR-3` to the same name, and under 160, 416, 633, 637 and 724
the NTI fixture does the same to `RTRT-3` and `RTRT-9`. Roughly three runs in a
thousand.

The engine then did exactly the right thing with what it was handed. Two
subjects sharing one identifier is one subject with contradictory rows - two
sequences, or two values for one period - so `validate_subject_rows` excluded
it, both originals went with it, and the analysis ran on twenty-two subjects
instead of twenty-four. sWR moved, the degrees of freedom moved, the comparison
failed. The statistics were never in question. The test had destroyed a subject
and then asked why the answer had changed.

Reproduced on unmodified `main` at those seeds; passes at seed 0, which is why
it looked intermittent.

WHAT THIS MODULE GUARANTEES

A rename that is injective, deterministic, and independent of the interpreter:
distinct subjects keep distinct names, every row of one subject gets the same
name, and nothing but the identifier changes. Names are `S0001`, `S0002`, ...
in order of first appearance, so the mapping is the same on every machine, on
every Python version, under every hash seed.

`rename_subjects` will also accept a caller's own naming function, and refuses
one that is not injective. That is not decoration: it is how the tests below
demonstrate, deterministically and without depending on any particular
interpreter's hash values, that a folded hash is not a renaming strategy.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import replace

from be_stats.diagnostics import Diagnostic
from be_stats.replicate import ReplicateObservation


class CollidingRename(AssertionError):
    """Two distinct subjects were given one name.

    An `AssertionError` on purpose. This is a fault in a test fixture, not a
    condition the engine is being asked to handle, and it should read like a
    failed assertion wherever it surfaces.
    """


def sequential_names(subject_ids: Iterable[str]) -> dict[str, str]:
    """`S0001`, `S0002`, ... in order of first appearance.

    Injective by construction - the counter never repeats - and dependent on
    nothing but the order the subjects arrive in, which the caller controls.
    """
    mapping: dict[str, str] = {}
    for subject_id in subject_ids:
        if subject_id not in mapping:
            mapping[subject_id] = f"S{len(mapping) + 1:04d}"
    return mapping


def subject_rename_map(
    observations: Iterable[ReplicateObservation],
    *,
    name: Callable[[str], str] | None = None,
) -> dict[str, str]:
    """The old-name -> new-name mapping, checked for collisions.

    One entry per distinct subject, so a subject cannot be renamed one way in
    period 1 and another way in period 3: the mapping is built once and applied
    to every row.

    Raises `CollidingRename` if two subjects share a new name, naming both, so
    a rename that silently merges subjects fails as a rename rather than later
    as a statistical disagreement nobody can place.

    The check guards the CALLER-SUPPLIED path only. `sequential_names` cannot
    collide - the counter never repeats - so checking it would be a guard no
    test could ever make fire, and a guard that cannot fail is a guard nobody
    can trust. What defends the default instead is
    `test_the_rename_map_is_the_same_on_every_machine`, which pins the mapping
    itself, and `test_the_rename_does_not_consult_pythons_hash`, which reads
    this module's syntax tree. Both fail under every seed rather than under
    one in three hundred.
    """
    subject_ids = [o.subject_id for o in observations]
    if name is None:
        return sequential_names(subject_ids)

    mapping: dict[str, str] = {}
    taken: dict[str, str] = {}
    for subject_id in subject_ids:
        if subject_id in mapping:
            continue
        new = name(subject_id)
        if new in taken:
            raise CollidingRename(
                f"{taken[new]!r} and {subject_id!r} would both be renamed to "
                f"{new!r}. That is not a rename: it merges two subjects into "
                f"one, and the merged subject is excluded from the analysis."
            )
        taken[new] = subject_id
        mapping[subject_id] = new
    return mapping


def rename_subjects(
    observations: Sequence[ReplicateObservation],
    *,
    name: Callable[[str], str] | None = None,
) -> list[ReplicateObservation]:
    """The same observations under new subject identifiers, and nothing else.

    Built with `dataclasses.replace`, so sequence, period, treatment, endpoint
    and value are carried across by the dataclass itself rather than by a list
    of field assignments somebody could mistype.
    """
    mapping = subject_rename_map(observations, name=name)
    return [replace(o, subject_id=mapping[o.subject_id]) for o in observations]


def diagnostic_signature(
    diagnostics: Iterable[Diagnostic],
) -> tuple[tuple[str, str], ...]:
    """What the engine said about the data, with the names taken out.

    Code and severity, sorted. The subject a diagnostic names is DELIBERATELY
    dropped: a renamed study is expected to report the same problems about the
    same rows under different labels, so comparing the labels would fail on the
    one difference the rename is allowed to make. Sorted because the order
    diagnostics arrive in follows the order the rows did, which the shuffling
    tests change on purpose.

    Empty on both sides is not a vacuous comparison here. The collision that
    started this produced an EXCLUSION diagnostic on the renamed run and none on
    the baseline, so this is the assertion that names the defect directly.
    """
    return tuple(sorted((d.code.name, d.severity.name) for d in diagnostics))
