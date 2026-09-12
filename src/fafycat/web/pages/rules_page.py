"""Merchant Rules page: the exact-match rules derived from reviewed transactions."""

from fasthtml.common import H1, A, Div, P, Table, Tbody, Td, Th, Thead, Tr, to_xml
from sqlalchemy.orm import Session

from fafycat.core.database import CategoryORM, MerchantMappingORM
from fafycat.ml.merchant_mapper import RULE_CONFIDENCE_CAPS, RULE_MIN_REVIEWS, RULE_MIN_SHARE
from fafycat.web.components.layout import create_page_layout


def render_rules_page(session: Session) -> str:
    """Render every Merchant Rule with its category, confidence, and evidence."""
    rows = (
        session.query(MerchantMappingORM, CategoryORM.name)
        .join(CategoryORM, CategoryORM.id == MerchantMappingORM.category_id)
        .order_by(MerchantMappingORM.merchant_pattern)
        .all()
    )

    caps = ", ".join(f"{cap:.0%}" for cap in RULE_CONFIDENCE_CAPS)
    intro = P(
        "A merchant rule maps a cleaned merchant name to a category. Rules are rebuilt from your reviewed "
        f"transactions after every review: a merchant needs {RULE_MIN_REVIEWS} review with one category holding "
        f"{RULE_MIN_SHARE:.0%} or more of them. A rule speaks more confidently the more reviews back it, capped at "
        f"{caps} for one, two, and three or more reviews. A rule never decides on its own. It votes in the "
        "ensemble beside LightGBM and Naive Bayes, and the stacked model learns from out-of-fold training rows "
        "how far to trust it.",
        cls="text-secondary mb-6",
    )

    if not rows:
        body = Div(P("No merchant rules yet. Train the model to derive them.", cls="text-secondary"), cls="card")
    else:
        body = Div(
            Table(
                Thead(Tr(Th("Merchant pattern"), Th("Category"), Th("Confidence"), Th("Reviews"), Th("Last seen"))),
                Tbody(
                    *[
                        Tr(
                            Td(str(m.merchant_pattern)),
                            Td(str(category_name)),
                            Td(f"{m.confidence:.0%}", cls="amount-cell"),
                            Td(str(m.occurrence_count), cls="amount-cell"),
                            Td(str(m.last_seen or "")),
                        )
                        for m, category_name in rows
                    ]
                ),
            ),
            cls="table-container",
        )

    content = Div(
        A("← Settings", href="/settings", cls="text-secondary text-sm"),
        H1(f"Merchant rules ({len(rows)})", cls="text-2xl font-bold mb-4 mt-2"),
        intro,
        body,
        cls="container mx-auto px-4 py-8",
    )
    return create_page_layout("Merchant Rules - FafyCat", to_xml(content))
