"""Merchant Rules page: the exact-match rules derived from reviewed transactions."""

from fasthtml.common import H1, A, Div, P, Table, Tbody, Td, Th, Thead, Tr, to_xml
from sqlalchemy.orm import Session

from fafycat.core.database import CategoryORM, MerchantMappingORM
from fafycat.ml.merchant_mapper import RULE_MIN_SHARE, RULE_OVERRIDE_CONFIDENCE
from fafycat.web.components.layout import create_page_layout


def render_rules_page(session: Session) -> str:
    """Render every Merchant Rule with its category, confidence, and evidence."""
    rows = (
        session.query(MerchantMappingORM, CategoryORM.name)
        .join(CategoryORM, CategoryORM.id == MerchantMappingORM.category_id)
        .order_by(MerchantMappingORM.merchant_pattern)
        .all()
    )

    intro = P(
        "A merchant rule maps a cleaned merchant name to a category. Rules are rebuilt from your reviewed "
        f"transactions every time the model is trained: a merchant needs at least 3 reviews with one category "
        f"holding {RULE_MIN_SHARE:.0%} or more of them. A rule decides a prediction on its own only when it matches "
        f"exactly and its confidence is at least {RULE_OVERRIDE_CONFIDENCE:.0%}; otherwise the ML ensemble decides.",
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
