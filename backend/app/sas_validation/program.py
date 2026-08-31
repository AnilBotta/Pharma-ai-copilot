"""Generate the executable SAS program, from the qualified model specification.

TWO THINGS THAT ARE NOT THE SAME, AND WERE CONFLATED IN THE FIRST VERSION

    the REGULATORY SOURCE STATEMENT   what FDA's Appendix C prints
    the EXECUTABLE SAS STATEMENT      what a SAS session will actually run

They are identical for five of the six statements. They differ for one, and
pretending otherwise pushed the problem onto the customer.

FDA's text prints `CLASSES SEQ SUBJ PER TRT;`. The PROC MIXED statement is
`CLASS`. The first version of this module shipped the source text unchanged and
told the customer in the README that `CLASS` was "a syntax alias" they could
substitute themselves. That was wrong twice: `CLASSES` is not documented PROC
MIXED syntax, so calling `CLASS` an alias for it inverts which one is correct;
and asking a client to hand-edit a regulatory model statement destroys the
program hash that ties their output back to the package.

So the normalization happens HERE, once, deterministically, and lands inside
the program hash like every other byte.

THE NORMALIZATION IS ALLOW-LISTED, NOT PATTERN-MATCHED

`SYNTAX_NORMALIZATIONS` holds exactly one entry. A statement that needs any
transformation not on that list raises `UnknownSyntaxNormalization` and no
package is produced - because a generator that could silently rewrite a model
statement is a generator that could quietly change the model.

Every normalization applied is recorded in the returned object, written into
the model specification, and shown in the README, so a reviewer can see what
executed and what the regulator wrote without diffing anything.

THE ONE RULE THIS MODULE STILL ENFORCES

The model statements are read from `be_stats.replicate_abe.APPENDIX_C_MODEL`,
the qualified record of FDA's Appendix C, which carries the citation and was
verified against the primary document. Nothing here retypes them.
"""

from __future__ import annotations

from dataclasses import dataclass

from be_stats.replicate_abe import APPENDIX_C_MODEL

#: What the shipped CSV actually contains. `Y` is NOT among them - it is
#: derived inside SAS - and the first version of this module claimed otherwise,
#: which put a false schema into the package manifest and its hash.
DATASET_COLUMNS = ("SUBJ", "SEQ", "PER", "TRT", "VALUE")

#: The measured value, in its original units. Shipped raw so the data is
#: inspectable as measured and its hash covers what was measured.
RAW_ANALYSIS_INPUT = "VALUE"

#: Derived in the DATA step from `VALUE`. The model is fitted on this.
DERIVED_ANALYSIS_VARIABLE = "Y"
DERIVED_ANALYSIS_DEFINITION = "Y = log(VALUE)"

OUTPUT_ESTIMATE = "be_estimate"
OUTPUT_COVPARMS = "be_covparms"
OUTPUT_FITSTATS = "be_fitstats"
OUTPUT_CONVERGENCE = "be_convergence"
OUTPUT_ENVIRONMENT = "be_environment"


class UnknownSyntaxNormalization(ValueError):
    """A source statement needs a transformation that is not allow-listed.

    Deliberately fatal. The alternative - emitting the statement unchanged and
    hoping - produces a package that fails in the customer's SAS session, and
    the alternative to THAT - a general rewriter - is a component that can
    change the model without anyone noticing.
    """


@dataclass(frozen=True, slots=True)
class SyntaxNormalization:
    """One allow-listed source-to-executable substitution."""

    identifier: str
    source_keyword: str
    executable_keyword: str
    reason: str
    changes_statistical_model: bool = False


#: THE COMPLETE ALLOW-LIST. One entry today.
SYNTAX_NORMALIZATIONS: tuple[SyntaxNormalization, ...] = (
    SyntaxNormalization(
        identifier="classes-to-class",
        source_keyword="CLASSES",
        executable_keyword="CLASS",
        reason=(
            "PROC MIXED's documented statement is CLASS. The FDA guidance "
            "prints CLASSES in its Appendix C listing. Substituting the "
            "keyword changes SAS SYNTAX ONLY: the same four variables are "
            "declared classification variables, so the fixed-effects design, "
            "the covariance structure and every estimate are unchanged."
        ),
        changes_statistical_model=False,
    ),
)


@dataclass(frozen=True, slots=True)
class NormalizedStatement:
    source: str
    executable: str
    normalization: SyntaxNormalization | None

    @property
    def was_normalized(self) -> bool:
        return self.normalization is not None


@dataclass(frozen=True, slots=True)
class GeneratedProgram:
    text: str
    model_citation: str
    #: The regulator's statements, exactly as the specification records them.
    source_statements: tuple[str, ...]
    #: What the SAS session will run, after allow-listed normalization.
    executable_statements: tuple[str, ...]
    normalizations_applied: tuple[SyntaxNormalization, ...]
    output_datasets: tuple[str, ...]
    result_filename: str

    def normalization_records(self) -> list[dict[str, object]]:
        return [
            {
                "identifier": n.identifier,
                "source_keyword": n.source_keyword,
                "executable_keyword": n.executable_keyword,
                "changes_statistical_model": n.changes_statistical_model,
                "reason": n.reason,
            }
            for n in self.normalizations_applied
        ]


def leading_keyword(statement: str) -> str:
    """The statement's opening keyword, uppercased.

    Taken as the leading run of letters rather than by splitting on a space,
    because Appendix C writes `REPEATED/GRP=TRT SUB=SUBJ;` with no space before
    the slash. Splitting on whitespace yielded `REPEATED/GRP=TRT`, which
    matched nothing and made the allow-list reject a statement it should have
    accepted.
    """
    stripped = statement.strip()
    end = 0
    while end < len(stripped) and stripped[end].isalpha():
        end += 1
    return stripped[:end].upper()


def normalize_statement(statement: str) -> NormalizedStatement:
    """Apply an allow-listed keyword substitution, or none at all.

    Only the leading keyword is considered, and only against the allow-list.
    Nothing else is touched - the variable list, the options after the slash
    and the spacing all pass through unaltered.
    """
    stripped = statement.strip()
    keyword = leading_keyword(stripped)
    for normalization in SYNTAX_NORMALIZATIONS:
        if keyword == normalization.source_keyword:
            executable = (
                normalization.executable_keyword + stripped[len(keyword) :]
            )
            return NormalizedStatement(statement, executable, normalization)
    return NormalizedStatement(statement, statement, None)


def _model_statements() -> tuple[
    list[NormalizedStatement], tuple[SyntaxNormalization, ...]
]:
    """Normalize every statement, and refuse anything unrecognised.

    `PROC MIXED;` is handled separately by the caller because it must name its
    input dataset - a structural requirement of running the program at all,
    not a keyword substitution, and it is recorded as such.
    """
    statements: list[NormalizedStatement] = []
    applied: list[SyntaxNormalization] = []

    for source in APPENDIX_C_MODEL.sas:
        if source.strip().upper().startswith("PROC MIXED"):
            statements.append(NormalizedStatement(source, "", None))
            continue

        normalized = normalize_statement(source)
        statements.append(normalized)
        if normalized.normalization is not None:
            applied.append(normalized.normalization)

        # A statement that begins with a keyword PROC MIXED does not accept,
        # and that is not on the allow-list, must not reach a customer.
        first_word = leading_keyword(normalized.executable)
        if first_word not in _PERMITTED_EXECUTABLE_KEYWORDS:
            raise UnknownSyntaxNormalization(
                f"the source statement {source!r} begins with {first_word!r}, "
                "which is neither a PROC MIXED statement this generator knows "
                "nor an allow-listed normalization. Generation refuses rather "
                "than emitting a program that may not run, or silently "
                "rewriting a regulatory model statement."
            )

    return statements, tuple(applied)


#: The statements PROC MIXED accepts that Appendix C uses, after normalization.
#: Kept explicit so a new statement in the specification is a decision here
#: rather than something that flows through untested.
_PERMITTED_EXECUTABLE_KEYWORDS = frozenset(
    {"CLASS", "MODEL", "RANDOM", "REPEATED", "ESTIMATE", "LSMEANS", "PARMS"}
)


def _header(
    case_id: str,
    dataset_filename: str,
    dataset_sha256: str,
    normalizations: tuple[SyntaxNormalization, ...],
) -> list[str]:
    citation = APPENDIX_C_MODEL.citation
    lines = [
        "/" + "*" * 76,
        " * SAS validation program - generated. DO NOT EDIT.",
        " *",
        f" * validation case : {case_id}",
        f" * model           : {citation.authority} {citation.section}",
        f" * document        : {citation.document}",
        f" * version         : {citation.document_version}",
        f" * dataset file    : {dataset_filename}",
        f" * dataset sha256  : {dataset_sha256}",
        " *",
        " * This program is ready to run as supplied. Editing any line breaks",
        " * the program hash that ties your output back to this package, and",
        " * the upload will be rejected as evidence for a different program.",
        " *",
    ]
    if normalizations:
        lines += [
            " * SYNTAX NORMALIZATIONS APPLIED (SAS syntax only, model unchanged):",
            " *",
        ]
        for normalization in normalizations:
            lines += [
                f" *   [{normalization.identifier}] "
                f"{normalization.source_keyword} -> "
                f"{normalization.executable_keyword}",
            ]
            for line in _wrap(normalization.reason, 68):
                lines.append(" *       " + line)
        lines += [
            " *",
            " * The regulatory source statements are recorded verbatim in",
            " * model_specification.json alongside these substitutions.",
            " *",
        ]
    else:  # pragma: no cover - the allow-list currently always applies
        lines += [" * No syntax normalization was required.", " *"]

    lines += [
        " * The data is NOT modified. Every observation supplied was validated",
        " * before this package was generated, so the DATA step below derives",
        " * the analysis variable and drops nothing.",
        " " + "*" * 75 + "/",
        "",
    ]
    return lines


def _wrap(text: str, width: int) -> list[str]:
    words, line, out = text.split(), "", []
    for word in words:
        if len(line) + len(word) + 1 > width:
            out.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    if line:
        out.append(line)
    return out


def _read_step(dataset_filename: str) -> list[str]:
    return [
        "/* ---- read the shipped dataset -------------------------------- */",
        "",
        "%let dsfile = &packagedir./" + dataset_filename + ";",
        "",
        "proc import datafile = \"&dsfile.\"",
        "            out      = be_raw",
        "            dbms     = csv",
        "            replace;",
        "    getnames = yes;",
        "    guessingrows = max;",
        "run;",
        "",
        "/* The CSV carries VALUE, the measurement in its original units. The",
        "   model is fitted on the log scale, so Y is DERIVED here. Y is not a",
        "   column of dataset.csv and the model specification says so.",
        "",
        "   Nothing is dropped. Package generation already refused to build a",
        "   package containing a missing, non-numeric, non-finite or",
        "   non-positive value, so every row reaching this step is valid. The",
        "   check below is defensive: if invalid data somehow arrives, the",
        "   program STOPS rather than silently analysing fewer observations",
        "   than the package claims. */",
        "",
        "data be_input;",
        "    set be_raw;",
        "    if missing(VALUE) or VALUE <= 0 then do;",
        "        put 'ERROR: non-positive or missing VALUE for subject ' SUBJ",
        "            ' period ' PER '. This package was generated from"
        " validated data;';",
        "        put 'ERROR: refusing to continue rather than dropping the"
        " observation.';",
        "        abort cancel;",
        "    end;",
        "    " + DERIVED_ANALYSIS_DEFINITION + ";",
        "    keep SUBJ SEQ PER TRT " + DERIVED_ANALYSIS_VARIABLE + ";",
        "run;",
        "",
    ]


def _model_step(statements: list[NormalizedStatement]) -> list[str]:
    lines = [
        "/* ---- FDA Appendix C model ------------------------------------ */",
        "",
        "ods output Estimates        = " + OUTPUT_ESTIMATE + ";",
        "ods output CovParms         = " + OUTPUT_COVPARMS + ";",
        "ods output FitStatistics    = " + OUTPUT_FITSTATS + ";",
        "ods output ConvergenceStatus = " + OUTPUT_CONVERGENCE + ";",
        "",
    ]
    for statement in statements:
        if statement.source.strip().upper().startswith("PROC MIXED"):
            lines.append("proc mixed data = be_input method = reml;")
            lines.append(f"    /* source: {statement.source} */")
            continue
        if statement.was_normalized:
            lines.append(f"    /* source: {statement.source} */")
            lines.append(
                f"    /* normalization: {statement.normalization.identifier} "
                "- SAS syntax only, statistical model unchanged */"
            )
        lines.append("    " + statement.executable)
    lines += ["run;", ""]
    return lines


def _environment_step() -> list[str]:
    return [
        "/* ---- record the environment, so evidence identifies itself ---- */",
        "",
        "data " + OUTPUT_ENVIRONMENT + ";",
        "    length name $ 40 value $ 200;",
        "    name = 'sas_version';      value = \"&sysvlong.\";      output;",
        "    name = 'sas_scp';          value = \"&syscp.\";         output;",
        "    name = 'run_datetime';     value = put(datetime(), datetime20.); output;",
        "run;",
        "",
    ]


def _export_step(result_filename: str) -> list[str]:
    return [
        "/* ---- write ONE structured result file ------------------------- */",
        "",
        "data be_result;",
        "    length section $ 24 name $ 40 value $ 200;",
        "",
        "    set " + OUTPUT_ESTIMATE + "(in=a)",
        "        " + OUTPUT_COVPARMS + "(in=b)",
        "        " + OUTPUT_CONVERGENCE + "(in=c)",
        "        " + OUTPUT_ENVIRONMENT + "(in=d rename=(name=envname value=envvalue));",
        "",
        "    if a then do;",
        "        section = 'estimate';",
        "        name = strip(Label);",
        "        value = strip(put(Estimate, best16.)) || '|' ||",
        "                strip(put(StdErr,   best16.)) || '|' ||",
        "                strip(put(DF,       best16.)) || '|' ||",
        "                strip(put(Lower,    best16.)) || '|' ||",
        "                strip(put(Upper,    best16.));",
        "        output;",
        "    end;",
        "    else if b then do;",
        "        section = 'covparm';",
        "        name  = strip(CovParm) || ' ' || strip(vvalue(Group));",
        "        value = strip(put(Estimate, best16.));",
        "        output;",
        "    end;",
        "    else if c then do;",
        "        section = 'convergence';",
        "        name  = 'status';",
        "        value = strip(put(Status, best16.)) || '|' || strip(Reason);",
        "        output;",
        "    end;",
        "    else if d then do;",
        "        section = 'environment';",
        "        name  = envname;",
        "        value = envvalue;",
        "        output;",
        "    end;",
        "",
        "    keep section name value;",
        "run;",
        "",
        "proc export data    = be_result",
        "            outfile = \"&packagedir./" + result_filename + "\"",
        "            dbms    = csv",
        "            replace;",
        "run;",
        "",
        "/* Upload the file above together with the SAS log. Neither is treated",
        "   as a regulatory conclusion: they are compared with the engine's own",
        "   result and a reviewer decides what the comparison means. */",
    ]


def generate_program(
    *,
    case_id: str,
    dataset_filename: str,
    dataset_sha256: str,
    result_filename: str = "be_result.csv",
) -> GeneratedProgram:
    """Deterministic: identical inputs give a byte-identical program.

    No timestamp, no hostname, no random identifier - the program's hash is
    recorded in the manifest and re-derived on upload, so a generator that
    varied between calls would make every upload look like evidence for a
    different program.

    The normalizations are part of the text and therefore part of that hash.
    """
    statements, applied = _model_statements()

    lines: list[str] = []
    lines += _header(case_id, dataset_filename, dataset_sha256, applied)
    lines += [
        "/* Set this to the folder holding the package files before running.",
        "   This is the ONLY line you should change. */",
        "%let packagedir = .;",
        "",
    ]
    lines += _read_step(dataset_filename)
    lines += _model_step(statements)
    lines += _environment_step()
    lines += _export_step(result_filename)

    return GeneratedProgram(
        text="\n".join(lines) + "\n",
        model_citation=(
            f"{APPENDIX_C_MODEL.citation.authority} "
            f"{APPENDIX_C_MODEL.citation.section} "
            f"({APPENDIX_C_MODEL.citation.document_version})"
        ),
        source_statements=tuple(APPENDIX_C_MODEL.sas),
        executable_statements=tuple(
            s.executable for s in statements if s.executable
        ),
        normalizations_applied=applied,
        output_datasets=(
            OUTPUT_ESTIMATE,
            OUTPUT_COVPARMS,
            OUTPUT_FITSTATS,
            OUTPUT_CONVERGENCE,
            OUTPUT_ENVIRONMENT,
        ),
        result_filename=result_filename,
    )


__all__ = [
    "DATASET_COLUMNS",
    "DERIVED_ANALYSIS_DEFINITION",
    "DERIVED_ANALYSIS_VARIABLE",
    "RAW_ANALYSIS_INPUT",
    "SYNTAX_NORMALIZATIONS",
    "GeneratedProgram",
    "NormalizedStatement",
    "SyntaxNormalization",
    "UnknownSyntaxNormalization",
    "generate_program",
    "normalize_statement",
]
