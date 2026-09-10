"""Corrections reach the siblings that share a transaction's merchant pattern."""

from datetime import UTC, date, datetime

from fafycat.core.audit_trail import ReviewActor
from fafycat.core.database import CategoryORM, MerchantMappingORM, ReviewEventORM, TransactionORM
from fafycat.core.models import TransactionInput
from fafycat.data.merchant_pattern import backfill_merchant_patterns
from fafycat.ml.merchant_mapper import MerchantMapper, refresh_rule_for_pattern

SHELL = "VISA SHELL 1234 Berlin"
"""A name the MerchantCleaner strips down to a shared pattern."""


def _categories(db_session) -> tuple[CategoryORM, CategoryORM]:
    fuel = CategoryORM(name="fuel", type="spending", budget=0.0)
    groceries = CategoryORM(name="groceries", type="spending", budget=0.0)
    db_session.add_all([fuel, groceries])
    db_session.flush()
    return fuel, groceries


def _seed(db_session, name: str, txn_id: str, **overrides) -> TransactionORM:
    """Insert one transaction. ``merchant_pattern`` is left unset unless given."""
    txn = TransactionORM(
        id=txn_id.ljust(16, "0"),
        date=date(2026, 8, 4),
        name=name,
        purpose="",
        amount=-42.0,
        currency="EUR",
        import_batch="b",
        imported_at=datetime.now(UTC),
        **overrides,
    )
    db_session.add(txn)
    db_session.flush()
    return txn


def _pattern_of(name: str) -> str:
    from fafycat.ml.feature_extractor import MerchantCleaner

    return MerchantCleaner().clean(name)


class TestBackfill:
    def test_fills_the_cleaned_merchant_name_on_rows_that_lack_one(self, db_session):
        _seed(db_session, SHELL, "a")
        _seed(db_session, "REWE Markt 42", "b")
        db_session.commit()

        assert backfill_merchant_patterns(db_session) == 2

        patterns = {t.id: t.merchant_pattern for t in db_session.query(TransactionORM).all()}
        assert patterns["a".ljust(16, "0")] == _pattern_of(SHELL)
        assert patterns["b".ljust(16, "0")] == _pattern_of("REWE Markt 42")

    def test_is_idempotent_and_leaves_existing_patterns_alone(self, db_session):
        _seed(db_session, SHELL, "a")
        _seed(db_session, "REWE", "b", merchant_pattern="HAND EDITED")
        db_session.commit()

        assert backfill_merchant_patterns(db_session) == 1
        # Second pass finds nothing left to do.
        assert backfill_merchant_patterns(db_session) == 0

        rows = {t.id: t.merchant_pattern for t in db_session.query(TransactionORM).all()}
        assert rows["b".ljust(16, "0")] == "HAND EDITED"

    def test_runs_in_batches(self, db_session):
        for i in range(7):
            _seed(db_session, f"{SHELL} {i}", f"x{i}")
        db_session.commit()

        assert backfill_merchant_patterns(db_session, batch_size=2) == 7
        assert db_session.query(TransactionORM).filter(TransactionORM.merchant_pattern.is_(None)).count() == 0

    def test_a_name_that_cleans_to_nothing_is_stored_as_empty_not_null(self, db_session):
        _seed(db_session, "   ", "a")
        db_session.commit()

        backfill_merchant_patterns(db_session)

        assert db_session.query(TransactionORM).one().merchant_pattern == ""
        # Empty is a finished state, not a row still waiting for a pattern.
        assert backfill_merchant_patterns(db_session) == 0


class TestSavePrompt:
    def test_offers_to_propagate_when_unreviewed_siblings_exist(self, test_client, db_session):
        fuel, _ = _categories(db_session)
        pattern = _pattern_of(SHELL)
        _seed(db_session, SHELL, "a", merchant_pattern=pattern, predicted_category_id=fuel.id)
        _seed(db_session, SHELL, "b", merchant_pattern=pattern)
        _seed(db_session, SHELL, "c", merchant_pattern=pattern)
        db_session.commit()

        resp = test_client.put(
            "/api/transactions/" + "a".ljust(16, "0") + "/categorize-htmx", data={"actual_category": "fuel"}
        )

        assert resp.status_code == 200
        assert f'id="propagate-{"a".ljust(16, "0")}"' in resp.text
        assert f"2 more unreviewed from {pattern}" in resp.text
        assert "Apply fuel to all" in resp.text
        assert "/api/transactions/propagate" in resp.text
        assert "Dismiss" in resp.text
        # The saved row still comes back, under the id the form swaps.
        assert f'id="transaction-{"a".ljust(16, "0")}"' in resp.text

    def test_stays_quiet_when_every_sibling_is_already_reviewed(self, test_client, db_session):
        fuel, _ = _categories(db_session)
        pattern = _pattern_of(SHELL)
        _seed(db_session, SHELL, "a", merchant_pattern=pattern)
        _seed(db_session, SHELL, "b", merchant_pattern=pattern, is_reviewed=True, category_id=fuel.id)
        db_session.commit()

        resp = test_client.put(
            "/api/transactions/" + "a".ljust(16, "0") + "/categorize-htmx", data={"actual_category": "fuel"}
        )

        assert resp.status_code == 200
        assert "propagate-" not in resp.text

    def test_stays_quiet_when_the_transaction_has_no_pattern(self, test_client, db_session):
        _categories(db_session)
        _seed(db_session, "   ", "a", merchant_pattern="")
        _seed(db_session, "   ", "b", merchant_pattern="")
        db_session.commit()

        resp = test_client.put(
            "/api/transactions/" + "a".ljust(16, "0") + "/categorize-htmx", data={"actual_category": "fuel"}
        )

        assert resp.status_code == 200
        assert "propagate-" not in resp.text


class TestPropagateEndpoint:
    def test_reviews_the_unreviewed_siblings_and_leaves_the_rest_alone(self, test_client, db_session):
        fuel, groceries = _categories(db_session)
        pattern = _pattern_of(SHELL)
        source = _seed(db_session, SHELL, "a", merchant_pattern=pattern, is_reviewed=True, category_id=fuel.id)
        _seed(db_session, SHELL, "b", merchant_pattern=pattern)
        _seed(db_session, SHELL, "c", merchant_pattern=pattern)
        # Already reviewed into another category: must not be touched.
        _seed(db_session, SHELL, "d", merchant_pattern=pattern, is_reviewed=True, category_id=groceries.id)
        # Different merchant: must not be touched.
        _seed(db_session, "REWE", "e", merchant_pattern="REWE")
        db_session.commit()

        resp = test_client.post(
            "/api/transactions/propagate",
            data={"source_id": source.id, "actual_category": "fuel"},
        )

        assert resp.status_code == 200
        assert "Applied to 2 transactions" in resp.text
        assert resp.headers["HX-Trigger"] == "transactions-changed"

        rows = {t.id: t for t in db_session.query(TransactionORM).all()}
        assert rows["b".ljust(16, "0")].is_reviewed is True
        assert rows["b".ljust(16, "0")].category_id == fuel.id
        assert rows["c".ljust(16, "0")].is_reviewed is True
        assert rows["d".ljust(16, "0")].category_id == groceries.id
        assert rows["e".ljust(16, "0")].is_reviewed is False
        assert rows["e".ljust(16, "0")].category_id is None

    def test_writes_one_review_event_per_sibling_naming_the_source(self, test_client, db_session):
        fuel, _ = _categories(db_session)
        pattern = _pattern_of(SHELL)
        source = _seed(db_session, SHELL, "a", merchant_pattern=pattern, is_reviewed=True, category_id=fuel.id)
        _seed(db_session, SHELL, "b", merchant_pattern=pattern)
        _seed(db_session, SHELL, "c", merchant_pattern=pattern)
        db_session.commit()

        test_client.post("/api/transactions/propagate", data={"source_id": source.id, "actual_category": "fuel"})

        events = db_session.query(ReviewEventORM).all()
        assert len(events) == 2
        assert {e.transaction_id for e in events} == {"b".ljust(16, "0"), "c".ljust(16, "0")}
        for event in events:
            assert event.actor == ReviewActor.PROPAGATION.value
            assert event.note == f"propagated from {source.id}"
            assert event.to_category_id == fuel.id

    def test_does_nothing_for_a_source_without_a_pattern(self, test_client, db_session):
        _categories(db_session)
        source = _seed(db_session, "   ", "a", merchant_pattern="", is_reviewed=True)
        _seed(db_session, "   ", "b", merchant_pattern="")
        db_session.commit()

        resp = test_client.post(
            "/api/transactions/propagate",
            data={"source_id": source.id, "actual_category": "fuel"},
        )

        assert resp.status_code == 200
        assert "Applied to 0 transactions" in resp.text
        assert (
            db_session.query(TransactionORM).filter(TransactionORM.id == "b".ljust(16, "0")).one().is_reviewed is False
        )

    def test_dismiss_removes_the_prompt_row(self, test_client):
        resp = test_client.get("/api/transactions/propagate/dismiss")

        assert resp.status_code == 200
        assert resp.text == ""


class TestRuleRefresh:
    def _review(self, db_session, txn_id: str, category: CategoryORM, pattern: str) -> None:
        _seed(db_session, SHELL, txn_id, merchant_pattern=pattern, is_reviewed=True, category_id=category.id)

    def test_creates_a_rule_once_the_third_consistent_review_lands(self, db_session):
        fuel, _ = _categories(db_session)
        pattern = _pattern_of(SHELL)

        self._review(db_session, "a", fuel, pattern)
        self._review(db_session, "b", fuel, pattern)
        db_session.commit()
        assert refresh_rule_for_pattern(db_session, pattern) is False
        assert db_session.query(MerchantMappingORM).count() == 0

        self._review(db_session, "c", fuel, pattern)
        db_session.commit()
        assert refresh_rule_for_pattern(db_session, pattern) is True

        rule = db_session.query(MerchantMappingORM).one()
        assert rule.merchant_pattern == pattern
        assert rule.category_id == fuel.id
        assert rule.occurrence_count == 3
        assert rule.confidence == 0.98  # capped by RULE_MAX_CONFIDENCE

    def test_deletes_the_rule_once_the_reviews_diverge(self, db_session):
        fuel, groceries = _categories(db_session)
        pattern = _pattern_of(SHELL)
        for txn_id in ("a", "b", "c"):
            self._review(db_session, txn_id, fuel, pattern)
        db_session.commit()
        refresh_rule_for_pattern(db_session, pattern)
        assert db_session.query(MerchantMappingORM).count() == 1

        # Two of five now say groceries: the fuel share drops below RULE_MIN_SHARE.
        self._review(db_session, "d", groceries, pattern)
        self._review(db_session, "e", groceries, pattern)
        db_session.commit()

        assert refresh_rule_for_pattern(db_session, pattern) is False
        assert db_session.query(MerchantMappingORM).count() == 0

    def test_unreviewed_transactions_do_not_count_towards_a_rule(self, db_session):
        fuel, _ = _categories(db_session)
        pattern = _pattern_of(SHELL)
        self._review(db_session, "a", fuel, pattern)
        _seed(db_session, SHELL, "b", merchant_pattern=pattern, category_id=fuel.id)
        _seed(db_session, SHELL, "c", merchant_pattern=pattern, category_id=fuel.id)
        db_session.commit()

        assert refresh_rule_for_pattern(db_session, pattern) is False

    def test_saving_a_category_refreshes_the_rule_without_a_retrain(self, test_client, db_session):
        fuel, _ = _categories(db_session)
        pattern = _pattern_of(SHELL)
        self._review(db_session, "a", fuel, pattern)
        self._review(db_session, "b", fuel, pattern)
        _seed(db_session, SHELL, "c", merchant_pattern=pattern, predicted_category_id=fuel.id)
        db_session.commit()
        assert db_session.query(MerchantMappingORM).count() == 0

        test_client.put(
            "/api/transactions/" + "c".ljust(16, "0") + "/categorize-htmx",
            data={"actual_category": "fuel"},
        )

        assert db_session.query(MerchantMappingORM).one().merchant_pattern == pattern

    def test_propagating_refreshes_the_rule(self, test_client, db_session):
        fuel, _ = _categories(db_session)
        pattern = _pattern_of(SHELL)
        source = _seed(db_session, SHELL, "a", merchant_pattern=pattern, is_reviewed=True, category_id=fuel.id)
        _seed(db_session, SHELL, "b", merchant_pattern=pattern)
        _seed(db_session, SHELL, "c", merchant_pattern=pattern)
        db_session.commit()

        test_client.post("/api/transactions/propagate", data={"source_id": source.id, "actual_category": "fuel"})

        rule = db_session.query(MerchantMappingORM).one()
        assert rule.merchant_pattern == pattern
        assert rule.occurrence_count == 3


class TestMapperSeesNewRules:
    def test_reload_picks_up_a_rule_written_after_the_mapper_was_built(self, db_session):
        fuel, _ = _categories(db_session)
        pattern = _pattern_of(SHELL)
        # A long-lived mapper, as the categorizer singleton holds.
        mapper = MerchantMapper(db_session)
        assert mapper.get_category(SHELL) is None

        for txn_id in ("a", "b", "c"):
            _seed(db_session, SHELL, txn_id, merchant_pattern=pattern, is_reviewed=True, category_id=fuel.id)
        db_session.commit()
        refresh_rule_for_pattern(db_session, pattern)

        # Still stale until the mapper re-reads the cache.
        assert mapper.get_category(SHELL) is None

        mapper.reload()
        rule = mapper.get_category(SHELL)
        assert rule is not None
        assert rule.category_id == fuel.id
        assert rule.merchant_pattern == pattern

    def test_refresh_pattern_updates_the_mappers_own_cache(self, db_session):
        fuel, _ = _categories(db_session)
        pattern = _pattern_of(SHELL)
        mapper = MerchantMapper(db_session)
        for txn_id in ("a", "b", "c"):
            _seed(db_session, SHELL, txn_id, merchant_pattern=pattern, is_reviewed=True, category_id=fuel.id)
        db_session.commit()

        assert mapper.refresh_pattern(pattern) is True

        rule = mapper.get_category(SHELL)
        assert rule is not None and rule.category_id == fuel.id

    def test_a_new_import_is_categorized_by_a_rule_the_review_just_created(self, db_session):
        """The rule reaches the next import without any retraining."""
        fuel, _ = _categories(db_session)
        pattern = _pattern_of(SHELL)
        mapper = MerchantMapper(db_session)

        for txn_id in ("a", "b", "c"):
            _seed(db_session, SHELL, txn_id, merchant_pattern=pattern, is_reviewed=True, category_id=fuel.id)
        db_session.commit()
        refresh_rule_for_pattern(db_session, pattern)
        mapper.reload()

        incoming = TransactionInput(
            date=date(2026, 9, 1),
            name=SHELL,
            purpose="",
            amount=-55.0,
            currency="EUR",
        )
        rule = mapper.get_category(incoming.name)
        assert rule is not None
        assert rule.merchant_pattern == pattern
        assert rule.category_id == fuel.id
