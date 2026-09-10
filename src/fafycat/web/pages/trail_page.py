"""Audit Trail page: how one transaction got its category."""

from fasthtml.common import H1, H2, H3, A, Div, P, Span, Table, Tbody, Td, Th, Thead, Tr, to_xml

from fafycat.core.audit_trail import PredictionEventView, Ranked, ReviewEventView, TransactionTrail
from fafycat.web.components.layout import create_page_layout

_ACTOR_LABELS = {
    "user_review": "You set the category",
    "auto_accept": "Auto-accepted",
    "bulk_approve": "Bulk-approved",
    "import_label": "Category came with the import",
}

_SOURCE_LABELS = {
    "merchant_rule": "Merchant rule decided",
    "ensemble": "Ensemble decided",
    "lgbm": "LightGBM decided",
}

_TRIGGER_LABELS = {
    "import": "on import",
    "batch_unpredicted": "batch prediction",
    "repredict": "re-prediction",
}


def _pct(value: float | None) -> str:
    return f"{value:.1%}" if value is not None else "n/a"


def _ranked_table(title: str, rows: list[Ranked], weight: float | None = None, empty: str = "not recorded") -> Div:
    heading = title if weight is None else f"{title} (weight {weight:.2f})"
    if not rows:
        return Div(H3(heading, cls="text-sm font-medium mb-1"), P(empty, cls="text-secondary text-sm"))
    return Div(
        H3(heading, cls="text-sm font-medium mb-1"),
        Table(
            Tbody(*[Tr(Td(r.category), Td(_pct(r.probability), cls="amount-cell")) for r in rows]),
            cls="text-sm",
        ),
    )


def _prediction_card(ev: PredictionEventView) -> Div:
    decision = "auto-accepted" if ev.decision == "auto_accepted" else "sent to review"
    if ev.rule_pattern is None:
        rule = P("No merchant rule matched, so the two models decided alone.", cls="text-secondary text-sm")
    else:
        vote = (
            f"voting with weight {ev.rule_weight:.2f}"
            if ev.rule_weight
            else "carrying no weight in this model"
            if ev.source == "ensemble"
            else "decided on its own"
        )
        rule = P(
            Span("Merchant rule: ", cls="font-medium"),
            f"{ev.rule_pattern} proposed {ev.rule_category} at {_pct(ev.rule_confidence)}, {vote}. ",
            A("All rules", href="/rules", cls="text-secondary"),
            cls="text-sm",
        )
    return Div(
        Div(
            Span(f"Prediction {_TRIGGER_LABELS.get(ev.trigger, ev.trigger)}", cls="font-semibold"),
            Span(f" · {ev.created_at:%Y-%m-%d %H:%M} · model {ev.model_id}", cls="text-secondary text-sm"),
        ),
        P(
            f"{_SOURCE_LABELS.get(ev.source, ev.source)}: {ev.final_category} at {_pct(ev.final_confidence)}, "
            f"{decision} (threshold {_pct(ev.threshold)}).",
            cls="mt-1",
        ),
        rule,
        Div(
            _ranked_table("LightGBM", ev.lgbm_top, ev.lgbm_weight),
            _ranked_table("Naive Bayes", ev.nb_top, ev.nb_weight),
            _ranked_table(
                "Merchant rule",
                ev.rule_top,
                ev.rule_weight,
                empty="no rule matched" if ev.rule_pattern is None else "not recorded",
            ),
            _ranked_table("Ensemble", ev.ensemble_top),
            cls="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mt-3",
        ),
        cls="card mb-4",
    )


def _review_card(ev: ReviewEventView) -> Div:
    change = ev.to_category if ev.from_category is None else f"{ev.from_category} → {ev.to_category}"
    context = ""
    if ev.predicted_category is not None:
        agreed = "agreed with" if ev.predicted_category == ev.to_category else "overrode"
        context = f" This {agreed} the prediction ({ev.predicted_category} at {_pct(ev.confidence_score)})."
    return Div(
        Div(
            Span(_ACTOR_LABELS.get(ev.actor, ev.actor), cls="font-semibold"),
            Span(f" · {ev.created_at:%Y-%m-%d %H:%M}", cls="text-secondary text-sm"),
        ),
        P(f"{change}.{context}", cls="mt-1"),
        *([P(ev.note, cls="text-secondary text-sm")] if ev.note else []),
        cls="card mb-4",
    )


def render_trail_page(trail: TransactionTrail) -> str:
    """Render the Audit Trail for one transaction."""
    txn = trail.transaction
    status = "reviewed" if txn.is_reviewed else "needs review"
    header = Div(
        Table(
            Thead(Tr(Th("Date"), Th("Merchant"), Th("Purpose"), Th("Amount"), Th("Category"), Th("Status"))),
            Tbody(
                Tr(
                    Td(str(txn.date)),
                    Td(str(txn.name)),
                    Td(str(txn.purpose or ""), style="max-width: 24rem; overflow-wrap: anywhere;"),
                    Td(f"€{txn.amount:,.2f}", cls="amount-cell"),
                    Td(trail.category or f"predicted: {trail.predicted_category or 'none'}"),
                    Td(status),
                )
            ),
        ),
        cls="table-container mb-6",
    )

    if trail.events:
        cards = [
            _prediction_card(ev) if isinstance(ev, PredictionEventView) else _review_card(ev) for ev in trail.events
        ]
    else:
        cards = [
            Div(
                P("No trail recorded. This transaction was predicted or reviewed before the Audit Trail existed."),
                cls="card",
            )
        ]

    content = Div(
        A("← Back to review", href="/review", cls="text-secondary text-sm"),
        H1("Audit trail", cls="text-2xl font-bold mb-6 mt-2"),
        header,
        H2("Timeline (newest first)", cls="text-lg font-semibold mb-4"),
        *cards,
        cls="container mx-auto px-4 py-8",
    )
    return create_page_layout("Audit Trail - FafyCat", to_xml(content))
