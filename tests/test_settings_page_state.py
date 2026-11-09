"""Settings page: model status from a real load, and every inactive category reachable."""

import re

from fafycat.core.database import CategoryORM


def test_a_model_file_that_does_not_load_is_not_reported_as_ready(test_client, db_session, tmp_data_dir):
    db_session.add(CategoryORM(name="groceries", type="spending"))
    db_session.commit()
    (tmp_data_dir / "models" / "ensemble_categorizer.pkl").write_bytes(b"not a real model")

    html = test_client.get("/settings").text

    assert "Model is loaded and working!" not in html
    assert "The saved model cannot be used:" in html
    assert "Retrain the model" in html


def test_every_inactive_category_is_on_the_page_behind_a_toggle(test_client, db_session):
    db_session.add(CategoryORM(name="active", type="spending"))
    db_session.add_all(CategoryORM(name=f"old-{i}", type="spending", is_active=False) for i in range(7))
    db_session.commit()

    html = test_client.get("/settings").text

    rows = re.findall(
        r'<div class="flex items-center justify-between p-2 text-sm"( data-inactive-overflow hidden)?>\s*<span>(old-\d)</span>',
        html,
    )
    assert [name for _, name in rows] == [f"old-{i}" for i in range(7)]
    assert [bool(hidden) for hidden, _ in rows] == [False] * 5 + [True] * 2
    assert 'onclick="toggleInactiveCategories(this)">Show 2 more</button>' in html
