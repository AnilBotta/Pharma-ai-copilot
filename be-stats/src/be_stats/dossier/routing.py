"""Which regulatory test applies, written down as a table a person can audit.

THE FAILURE THIS PREVENTS

A highly variable drug arrives, the engine cannot find a replicate design, and
it analyses the study under the ordinary 80.00-125.00% interval instead. The
report says PASS. Nothing crashed, nothing warned, and the wrong regulatory
question was answered - silently, because falling back to the conventional
interval is the most natural thing an unopinionated piece of code can do.

`spec.resolve_be_spec` already refuses to do that. What was missing is a form
of the routing rule that a reviewer can READ - one row per route, stating the
classification that selects it, the design it requires, the method it picks,
the decision rule it applies, and what it does when it cannot proceed.

THE TABLE IS NOT A SECOND IMPLEMENTATION

It would be worthless if it were: two encodings of the same rule drift, and the
one in the document is the one nobody runs. So
`test_every_route_matches_resolve_be_spec` drives the real router for every row
and asserts the row describes what actually happened - including the routes
whose correct behaviour is to raise.

A route that raises is a route. `SpecificationRequired` for EMA Cmax on an NTI
drug is not a gap in this table; it is the regulator declining to give a
general answer, faithfully reproduced.
"""

from __future__ import annotations

from dataclasses import dataclass

from be_stats.dossier.refusals import RefusalCode
from be_stats.minimums import DesignFamily
from be_stats.spec import DrugClass, Endpoint, Jurisdiction, Method

#: Endpoints a route applies to when it does not distinguish between them.
ANY_ENDPOINT: tuple[Endpoint, ...] = (Endpoint.AUC, Endpoint.CMAX, Endpoint.OTHER)


@dataclass(frozen=True, slots=True)
class RoutingRoute:
    """One row of the regulatory decision routing matrix."""

    route_id: str
    jurisdiction: Jurisdiction
    drug_class: DrugClass
    #: The endpoints this row governs. Rows for the same jurisdiction and drug
    #: class must partition the endpoints - EMA NTI needs two rows because AUC
    #: and Cmax genuinely route differently.
    endpoints: tuple[Endpoint, ...]
    #: How a study is classified INTO this route, in the caller's terms.
    input_classification: str
    #: Designs the selected method accepts. Empty where the route raises
    #: before a design is ever considered.
    design_requirement: tuple[DesignFamily, ...]
    #: The method selected, or None where the route produces no method.
    method: Method | None
    #: The criterion applied once the method is selected.
    decision_rule: str
    #: What happens when the route cannot produce a decision.
    refusal_behaviour: str
    #: The exception `resolve_be_spec` raises for this route, by class name, or
    #: "" where it returns a specification.
    raises: str = ""
    #: The refusal codes reachable downstream of this route.
    refusal_conditions: tuple[RefusalCode, ...] = ()


#: The routing matrix. Ordered FDA then EMA, ordinary then HVD then NTI, so it
#: reads the way a reviewer looks things up.
ROUTING_MATRIX: tuple[RoutingRoute, ...] = (
    # --------------------------------------------------------------- FDA ---
    RoutingRoute(
        route_id="FDA_STANDARD",
        jurisdiction=Jurisdiction.FDA,
        drug_class=DrugClass.STANDARD,
        endpoints=ANY_ENDPOINT,
        input_classification=(
            "A drug that is neither highly variable nor narrow therapeutic "
            "index. Note that the classification is an INPUT: this engine "
            "does not infer 'highly variable' from an observed CV, because "
            "FDA's classification and FDA's analysis switch are two different "
            "rules using two different quantities."
        ),
        design_requirement=(DesignFamily.CROSSOVER, DesignFamily.PARALLEL),
        method=Method.STANDARD_ABE,
        decision_rule=(
            "The 90% confidence interval for the T/R geometric mean ratio "
            "must fall entirely within 80.00-125.00%."
        ),
        refusal_behaviour=(
            "Insufficient degrees of freedom yields decided=false, "
            "passes=null, with diagnostics naming the excluded subjects. "
            "Never passes=false."
        ),
        refusal_conditions=(RefusalCode.QUANTITY_NOT_ESTIMABLE,),
    ),
    RoutingRoute(
        route_id="FDA_HVD",
        jurisdiction=Jurisdiction.FDA,
        drug_class=DrugClass.HIGHLY_VARIABLE,
        endpoints=ANY_ENDPOINT,
        input_classification=(
            "A drug declared highly variable - within-subject variability of "
            "30% or greater and not an NTI drug."
        ),
        design_requirement=(DesignFamily.REPLICATE, DesignFamily.PARTIAL_REPLICATE),
        method=Method.FDA_HVD_RSABE,
        decision_rule=(
            "The estimated sWR selects the analysis. sWR >= 0.294 applies "
            "reference-scaled average BE, whose upper 95% bound on "
            "(muT-muR)^2 - theta.sWR^2 must be <= 0, AND the point estimate "
            "must fall within 0.8000-1.2500. sWR < 0.294 routes the endpoint "
            "to ordinary average BE under Appendix C's mixed model."
        ),
        refusal_behaviour=(
            "A non-replicate design is refused outright. Below the switch on "
            "a PARTIAL replicate design the endpoint is NOT DECIDED - "
            "Appendix C is not implemented for that design and no verdict is "
            "produced. It never falls back to the Appendix G contrast, which "
            "is a different model."
        ),
        refusal_conditions=(
            RefusalCode.FDA_HVD_DESIGN_REQUIRED,
            RefusalCode.APPENDIX_C_PARTIAL_REPLICATE_NOT_IMPLEMENTED,
            RefusalCode.APPENDIX_C_REQUIRES_RAW_OBSERVATIONS,
            RefusalCode.QUANTITY_NOT_ESTIMABLE,
        ),
    ),
    RoutingRoute(
        route_id="FDA_NTI",
        jurisdiction=Jurisdiction.FDA,
        drug_class=DrugClass.NARROW_THERAPEUTIC_INDEX,
        endpoints=ANY_ENDPOINT,
        input_classification="A drug declared narrow therapeutic index.",
        design_requirement=(DesignFamily.REPLICATE,),
        method=Method.FDA_NTI_RSABE,
        decision_rule=(
            "ALL THREE Appendix F criteria must hold: (a) the 95% upper bound "
            "for (muT-muR)^2 - theta.sigma_WR^2 <= 0; (b) the ordinary "
            "unscaled 80.00-125.00% interval; (c) the upper limit of the 90% "
            "equal-tails interval for sigma_WT/sigma_WR <= 2.500. FDA ADDS "
            "criteria; it does not narrow the interval."
        ),
        refusal_behaviour=(
            "Anything but a fully replicate crossover is refused before any "
            "arithmetic runs. If any single criterion is not estimable the "
            "endpoint is NOT DECIDED rather than failed."
        ),
        refusal_conditions=(
            RefusalCode.FDA_NTI_FULL_REPLICATE_REQUIRED,
            RefusalCode.APPENDIX_C_REQUIRES_RAW_OBSERVATIONS,
            RefusalCode.QUANTITY_NOT_ESTIMABLE,
        ),
    ),
    # --------------------------------------------------------------- EMA ---
    RoutingRoute(
        route_id="EMA_STANDARD",
        jurisdiction=Jurisdiction.EMA,
        drug_class=DrugClass.STANDARD,
        endpoints=ANY_ENDPOINT,
        input_classification=(
            "A drug that is neither highly variable nor narrow therapeutic "
            "index."
        ),
        design_requirement=(DesignFamily.CROSSOVER, DesignFamily.PARALLEL),
        method=Method.STANDARD_ABE,
        decision_rule=(
            "The 90% confidence interval for the T/R geometric mean ratio "
            "must fall entirely within 80.00-125.00%."
        ),
        refusal_behaviour=(
            "As for the FDA standard route: not estimable yields "
            "decided=false, passes=null."
        ),
        refusal_conditions=(RefusalCode.QUANTITY_NOT_ESTIMABLE,),
    ),
    RoutingRoute(
        route_id="EMA_HVD_ABEL",
        jurisdiction=Jurisdiction.EMA,
        drug_class=DrugClass.HIGHLY_VARIABLE,
        endpoints=ANY_ENDPOINT,
        input_classification=(
            "A drug declared highly variable. EMA's WIDENING is available for "
            "Cmax only; the route accepts every endpoint and the widening "
            "does not."
        ),
        design_requirement=(DesignFamily.REPLICATE, DesignFamily.PARTIAL_REPLICATE),
        method=Method.EMA_HVD_ABEL,
        decision_rule=(
            "Where CVwR for Cmax exceeds 30% strictly, the limits widen to "
            "exp(+/- 0.760.sWR) capped at 69.84-143.19%; the Method A 90% "
            "interval must fall within them AND the GMR must fall within "
            "80.00-125.00%. Both are required. AUC stays at 80.00-125.00% "
            "regardless of variability."
        ),
        refusal_behaviour=(
            "Widening requested for AUC is refused rather than granted. A "
            "non-replicate design is refused. CVwR at or below 30% does not "
            "widen - it is not a failure, the ordinary limits simply apply."
        ),
        refusal_conditions=(
            RefusalCode.EMA_ABEL_CMAX_ONLY,
            RefusalCode.EMA_ABEL_REPLICATE_DESIGN_REQUIRED,
            RefusalCode.QUANTITY_NOT_ESTIMABLE,
        ),
    ),
    RoutingRoute(
        route_id="EMA_NTI_AUC",
        jurisdiction=Jurisdiction.EMA,
        drug_class=DrugClass.NARROW_THERAPEUTIC_INDEX,
        endpoints=(Endpoint.AUC,),
        input_classification=(
            "A drug declared narrow therapeutic index, endpoint AUC."
        ),
        design_requirement=(DesignFamily.CROSSOVER, DesignFamily.REPLICATE),
        method=Method.EMA_NTI_NARROW_ABE,
        decision_rule=(
            "The 90% confidence interval must fall within the NARROWED "
            "90.00-111.11%. EMA narrows the interval where FDA adds criteria; "
            "the two NTI procedures are not variants of one rule."
        ),
        refusal_behaviour=(
            "Not estimable yields decided=false, passes=null. The narrowed "
            "interval is never widened back to 80.00-125.00%."
        ),
        refusal_conditions=(RefusalCode.QUANTITY_NOT_ESTIMABLE,),
    ),
    RoutingRoute(
        route_id="EMA_NTI_CMAX",
        jurisdiction=Jurisdiction.EMA,
        drug_class=DrugClass.NARROW_THERAPEUTIC_INDEX,
        endpoints=(Endpoint.CMAX,),
        input_classification=(
            "A drug declared narrow therapeutic index, endpoint Cmax, with no "
            "product-specific guidance supplied."
        ),
        design_requirement=(),
        method=None,
        decision_rule=(
            "None is selected. EMA narrows Cmax only where Cmax itself "
            "matters for safety, efficacy or therapeutic drug monitoring, and "
            "that is a per-product decision: ciclosporin narrows both AUC and "
            "Cmax, colchicine narrows AUC and leaves Cmax at 80.00-125.00%."
        ),
        refusal_behaviour=(
            "Raises SpecificationRequired. Both available defaults are wrong "
            "for some products, so neither is chosen. Supplying the limits as "
            "a ProductOverride routes to EMA_NTI_NARROW_ABE with those limits."
        ),
        raises="SpecificationRequired",
        refusal_conditions=(RefusalCode.EMA_NTI_CMAX_PRODUCT_SPECIFIC,),
    ),
    RoutingRoute(
        route_id="EMA_NTI_OTHER",
        jurisdiction=Jurisdiction.EMA,
        drug_class=DrugClass.NARROW_THERAPEUTIC_INDEX,
        endpoints=(Endpoint.OTHER,),
        input_classification=(
            "A drug declared narrow therapeutic index, on an endpoint the "
            "general guideline does not address."
        ),
        design_requirement=(),
        method=None,
        decision_rule="None is selected.",
        refusal_behaviour=(
            "Raises SpecificationRequired. The general guideline defines "
            "narrowed limits for AUC and conditionally for Cmax, and for "
            "nothing else."
        ),
        raises="SpecificationRequired",
        refusal_conditions=(RefusalCode.EMA_NTI_CMAX_PRODUCT_SPECIFIC,),
    ),
)


#: What happens to a jurisdiction and drug-class combination with no row.
#:
#: Stated as data rather than left to the reader to infer from the absence of a
#: row, because "unsupported" is a route with a behaviour and the behaviour is
#: the important part: it refuses, and specifically it does not fall back to
#: the conventional interval.
UNSUPPORTED_COMBINATION = RoutingRoute(
    route_id="UNSUPPORTED",
    jurisdiction=Jurisdiction.FDA,  # nominal; the row applies to any
    drug_class=DrugClass.STANDARD,  # nominal; see `route_for`
    endpoints=(),
    input_classification=(
        "Any jurisdiction and drug-class combination not carried by a row "
        "above - a new regulator, or a drug class this engine does not "
        "classify."
    ),
    design_requirement=(),
    method=None,
    decision_rule="None is selected and no acceptance interval is assumed.",
    refusal_behaviour=(
        "Raises NotApplicable. It does NOT fall back to 80.00-125.00%: a "
        "conventional interval applied where the regulator requires something "
        "else produces a verdict that looks identical to a correct one."
    ),
    raises="NotApplicable",
    refusal_conditions=(RefusalCode.UNSUPPORTED_REGULATORY_ROUTE,),
)


def route_for(
    jurisdiction: Jurisdiction,
    drug_class: DrugClass,
    endpoint: Endpoint = Endpoint.AUC,
) -> RoutingRoute:
    """The row governing this combination, or `UNSUPPORTED_COMBINATION`.

    Endpoint-specific rows win over endpoint-agnostic ones, which is what lets
    EMA NTI carry three rows without the AUC row shadowing the other two.
    """
    candidates = [
        row
        for row in ROUTING_MATRIX
        if row.jurisdiction is jurisdiction
        and row.drug_class is drug_class
        and endpoint in row.endpoints
    ]
    if not candidates:
        return UNSUPPORTED_COMBINATION
    # A specific row lists fewer endpoints than a general one.
    return min(candidates, key=lambda row: len(row.endpoints))


def routes_for(jurisdiction: Jurisdiction) -> list[RoutingRoute]:
    """Every row for one regulator, in matrix order."""
    return [row for row in ROUTING_MATRIX if row.jurisdiction is jurisdiction]
