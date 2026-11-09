"""Category names: unique ignoring case, one length limit, and unambiguous lookups."""

from datetime import date

import pytest

from fafycat.core.config import AppConfig
from fafycat.core.database import CategoryORM, DatabaseManager, TransactionORM


def _txn(db_session, txn_id: str, **fields) -> TransactionORM:
    txn = TransactionORM(id=txn_id, date=date(2024, 5, 1), name="Shop", amount=-5.0, import_batch="b", **fields)
    db_session.add(txn)
    db_session.commit()
    return txn


class TestCreateAndRename:
    def test_a_name_that_differs_only_in_case_is_a_409(self, test_client, db_session):
        first = test_client.post("/api/categories/", json={"name": " Groceries ", "type": "spending"})
        second = test_client.post("/api/categories/", json={"name": "groceries", "type": "spending"})

        assert first.status_code == 200
        assert first.json()["name"] == "groceries"
        assert second.status_code == 409
        assert second.json()["detail"] == "Category 'groceries' already exists"
        assert db_session.query(CategoryORM).count() == 1

    def test_the_same_name_under_another_type_is_a_409(self, test_client):
        test_client.post("/api/categories/", json={"name": "other", "type": "spending"})

        response = test_client.post("/api/categories/", json={"name": "Other", "type": "income"})

        assert response.status_code == 409

    def test_renaming_onto_an_existing_name_is_a_409(self, test_client, db_session):
        db_session.add_all([CategoryORM(name="groceries", type="spending"), CategoryORM(name="rent", type="spending")])
        db_session.commit()
        rent_id = db_session.query(CategoryORM).filter_by(name="rent").one().id

        response = test_client.put(f"/api/categories/{rent_id}", json={"name": "GROCERIES"})

        assert response.status_code == 409
        db_session.expire_all()
        assert db_session.get(CategoryORM, rent_id).name == "rent"

    def test_a_name_in_the_qualified_form_is_rejected(self, test_client):
        response = test_client.post("/api/categories/", json={"name": "other (income)", "type": "spending"})

        assert response.status_code == 422

    def test_a_non_ascii_name_is_unique_ignoring_case(self, test_client, db_session):
        db_session.add(CategoryORM(name="Ärzte", type="spending"))
        db_session.commit()
        _txn(db_session, "t1")

        duplicate = test_client.post("/api/categories/", json={"name": "ärzte", "type": "spending"})
        assigned = test_client.put("/api/transactions/t1/category", json={"actual_category": "ärzte"})

        assert duplicate.status_code == 409
        assert assigned.status_code == 200
        assert assigned.json()["actual_category"] == "Ärzte"

    @pytest.mark.parametrize(("length", "status"), [(50, 200), (51, 422)])
    def test_names_are_limited_to_the_column_length(self, test_client, length, status):
        response = test_client.post("/api/categories/", json={"name": "x" * length, "type": "spending"})

        assert response.status_code == status


def test_the_default_categories_have_distinct_names(tmp_data_dir):
    manager = DatabaseManager(AppConfig())
    manager.create_tables()
    manager.init_default_categories()

    with manager.get_session() as session:
        names = [str(name).lower() for (name,) in session.query(CategoryORM.name)]
    assert len(names) == 17
    assert len(names) == len(set(names))


class TestLegacyDuplicateNames:
    """Databases initialised before the fix hold ('spending', 'other') and ('income', 'other')."""

    @pytest.fixture
    def others(self, db_session) -> dict[str, int]:
        rows = [CategoryORM(name="other", type="spending"), CategoryORM(name="other", type="income")]
        db_session.add_all(rows)
        db_session.commit()
        return {str(row.type): int(row.id) for row in rows}

    def test_the_review_dropdown_names_each_one_and_selects_the_right_one(self, test_client, db_session, others):
        _txn(db_session, "t1", predicted_category_id=others["income"], confidence_score=0.4)

        html = test_client.get("/api/transactions/table?status=pending").text

        assert '<option value="other (income)" selected>other (income)</option>' in html
        assert '<option value="other (spending)">other (spending)</option>' in html

    def test_a_qualified_name_assigns_that_category(self, test_client, db_session, others):
        _txn(db_session, "t1")

        response = test_client.put(
            "/api/transactions/t1/category", json={"actual_category": "other (income)", "is_reviewed": True}
        )

        assert response.status_code == 200, response.text
        db_session.expire_all()
        assert db_session.get(TransactionORM, "t1").category_id == others["income"]

    def test_a_shared_name_means_the_only_active_one(self, test_client, db_session, others):
        db_session.get(CategoryORM, others["income"]).is_active = False
        db_session.commit()
        _txn(db_session, "t1")

        response = test_client.put("/api/transactions/t1/category", json={"actual_category": "other"})

        assert response.status_code == 200, response.text
        db_session.expire_all()
        assert db_session.get(TransactionORM, "t1").category_id == others["spending"]

    def test_a_qualified_filter_lists_only_that_category(self, test_client, db_session, others):
        _txn(db_session, "income-row", predicted_category_id=others["income"])
        _txn(db_session, "spending-row", predicted_category_id=others["spending"])

        html = test_client.get("/api/transactions/table", params={"category_filter": "other (income)"}).text

        assert 'id="transaction-income-row"' in html
        assert 'id="transaction-spending-row"' not in html

    def test_an_ambiguous_name_is_a_400_not_a_guess(self, test_client, db_session, others):
        _txn(db_session, "t1")

        response = test_client.put("/api/transactions/t1/category", json={"actual_category": "other"})

        assert response.status_code == 400
        assert "other (spending)" in response.json()["detail"]
        db_session.expire_all()
        assert db_session.get(TransactionORM, "t1").category_id is None


class TestCategorizeErrors:
    def test_an_unknown_category_is_reported_as_such(self, test_client, db_session):
        _txn(db_session, "t1")

        response = test_client.put("/api/transactions/t1/category", json={"actual_category": "nope"})

        assert response.status_code == 400
        assert response.json()["detail"] == "Category not found: nope"

    def test_an_unknown_transaction_is_a_404(self, test_client, db_session):
        db_session.add(CategoryORM(name="groceries", type="spending"))
        db_session.commit()

        response = test_client.put("/api/transactions/missing/category", json={"actual_category": "groceries"})

        assert response.status_code == 404
        assert response.json()["detail"] == "Transaction not found"

    def test_names_match_ignoring_case(self, test_client, db_session):
        db_session.add(CategoryORM(name="groceries", type="spending"))
        db_session.commit()
        _txn(db_session, "t1")

        response = test_client.put("/api/transactions/t1/category", json={"actual_category": "Groceries"})

        assert response.status_code == 200
        assert response.json()["actual_category"] == "groceries"

    def test_htmx_unknown_category_says_so(self, test_client, db_session):
        _txn(db_session, "t1")

        response = test_client.put("/api/transactions/t1/categorize-htmx", data={"actual_category": "nope"})

        assert response.status_code == 400
        assert "Category not found: nope" in response.text


@pytest.mark.parametrize("sort_by", ["category", "metadata", "__table__", "id; drop"])
def test_an_unknown_sort_column_is_a_400(test_client, sort_by):
    response = test_client.get("/api/transactions/table", params={"sort_by": sort_by})

    assert response.status_code == 400


@pytest.mark.parametrize("sort_by", ["review_impact", "date", "confidence_score", "amount", "name"])
def test_every_offered_sort_column_works(test_client, db_session, sort_by):
    _txn(db_session, "t1")

    response = test_client.get("/api/transactions/table", params={"sort_by": sort_by, "status": "all"})

    assert response.status_code == 200
    assert 'id="transaction-t1"' in response.text
