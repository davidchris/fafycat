"""Tests for fuzzy dedup of card-settlement vs. account-direct duplicate rows (issue #37)."""

from datetime import date

import pytest

from fafycat.core.config import AppConfig
from fafycat.core.database import DatabaseManager, TransactionORM
from fafycat.core.models import TransactionInput
from fafycat.data.csv_processor import CSVProcessor
from fafycat.data.dedup import is_settlement_like, normalize_merchant_tokens


def _direct_row(**overrides) -> TransactionInput:
    """Account-direct booking: real purchase date, verbose purpose."""
    fields = {
        "date": date(2026, 4, 1),
        "name": "Muster Markt Berlin",
        "purpose": "Muster markt BE Rlin Datum 01.04.2026 Zeit 12:01 Kaufumsatz VISA Card EUR 94,05",
        "amount": -94.05,
    }
    fields.update(overrides)
    return TransactionInput(**fields)


def _settlement_row(**overrides) -> TransactionInput:
    """Delayed VISA settlement for the same purchase, 8 days later."""
    fields = {
        "date": date(2026, 4, 9),
        "name": "VISA Muster Markt",
        "purpose": "Nr xxxx 1022 berlin DE Kaufumsatz 01.04 94.05 ARN74477426093000000000000",
        "amount": -94.05,
    }
    fields.update(overrides)
    return TransactionInput(**fields)


class TestNormalizeMerchantTokens:
    def test_strips_visa_prefix_and_boilerplate(self):
        direct = normalize_merchant_tokens("Muster Markt Berlin", "")
        settlement = normalize_merchant_tokens("VISA Muster Markt", "")
        assert direct == {"muster", "markt", "berlin"}
        assert settlement == {"muster", "markt"}

    def test_falls_back_to_purpose_when_name_empty(self):
        tokens = normalize_merchant_tokens("", "Nr xxxx 1022 Edeka Kaufumsatz 01.04")
        assert tokens == {"edeka"}

    def test_empty_inputs(self):
        assert normalize_merchant_tokens("", "") == frozenset()


class TestIsSettlementLike:
    def test_visa_name_prefix(self):
        assert is_settlement_like("VISA Muster Markt", "")

    def test_masked_card_number_in_purpose(self):
        assert is_settlement_like("Muster", "Nr xxxx 1022 berlin DE")

    def test_settlement_date_reference(self):
        assert is_settlement_like("Muster", "Kaufumsatz 01.04 94.05")

    def test_plain_direct_row_is_not_settlement(self):
        assert not is_settlement_like("Muster Markt Berlin", "Lastschrift Einkauf Danke")

    def test_masked_card_number_with_period(self):
        assert is_settlement_like("Muster", "Nr. xxxx 1022 berlin DE")

    def test_full_date_after_kaufumsatz_is_not_settlement(self):
        """Direct bookings may carry 'Kaufumsatz <full date>' — only the DD.MM back-reference counts."""
        assert not is_settlement_like("Muster", "Kaufumsatz 01.04.2026 Einkauf")


class TestFuzzySettlementDedup:
    @pytest.fixture
    def session(self):
        config = AppConfig()
        config.database.url = "sqlite:///:memory:"
        db_manager = DatabaseManager(config)
        db_manager.create_tables()
        with db_manager.get_session() as session:
            yield session

    def test_settlement_pair_in_same_batch_collapses(self, session):
        processor = CSVProcessor(session)
        new, dup = processor.save_transactions([_settlement_row(), _direct_row()])

        assert (new, dup) == (1, 1)
        survivor = session.query(TransactionORM).one()
        # The account-direct row (real purchase date) is the one kept.
        assert survivor.date == date(2026, 4, 1)
        assert survivor.name == "Muster Markt Berlin"

    def test_settlement_in_later_batch_collapses(self, session):
        processor = CSVProcessor(session)
        processor.save_transactions([_direct_row()])
        new, dup = processor.save_transactions([_settlement_row()])

        assert (new, dup) == (0, 1)
        survivor = session.query(TransactionORM).one()
        assert survivor.date == date(2026, 4, 1)
        assert survivor.name == "Muster Markt Berlin"

    def test_direct_row_in_later_batch_upgrades_stored_settlement(self, session):
        """Card CSV imported before account CSV: direct row's date and name must win."""
        processor = CSVProcessor(session)
        processor.save_transactions([_settlement_row()])
        new, dup = processor.save_transactions([_direct_row()])

        assert (new, dup) == (0, 1)
        survivor = session.query(TransactionORM).one()
        assert survivor.date == date(2026, 4, 1)
        assert survivor.name == "Muster Markt Berlin"

    def test_reimport_direct_row_after_upgrade_is_duplicate(self, session):
        """After a field upgrade the stored id still hashes the settlement fields."""
        processor = CSVProcessor(session)
        processor.save_transactions([_settlement_row()])
        processor.save_transactions([_direct_row()])
        new, dup = processor.save_transactions([_direct_row(), _settlement_row()])

        assert (new, dup) == (0, 2)
        assert session.query(TransactionORM).count() == 1

    def test_exact_reimport_still_deduplicates(self, session):
        processor = CSVProcessor(session)
        batch = [_direct_row(), _settlement_row()]
        processor.save_transactions(batch)
        new, dup = processor.save_transactions(batch)

        assert new == 0
        assert dup == 2
        assert session.query(TransactionORM).count() == 1

    def test_different_amount_not_collapsed(self, session):
        processor = CSVProcessor(session)
        new, dup = processor.save_transactions([_direct_row(), _settlement_row(amount=-95.05)])
        assert (new, dup) == (2, 0)

    def test_outside_date_window_not_collapsed(self, session):
        processor = CSVProcessor(session)
        new, dup = processor.save_transactions([_direct_row(), _settlement_row(date=date(2026, 4, 15))])
        assert (new, dup) == (2, 0)

    def test_different_merchant_same_amount_not_collapsed(self, session):
        processor = CSVProcessor(session)
        other = _settlement_row(
            name="VISA Anderer Laden",
            purpose="Nr xxxx 1022 hamburg DE Kaufumsatz 02.04 94.05 ARN74477426093000000000001",
        )
        new, dup = processor.save_transactions([_direct_row(), other])
        assert (new, dup) == (2, 0)

    def test_two_legit_identical_direct_purchases_not_collapsed(self, session):
        """Same merchant, same amount, a few days apart — no settlement row involved."""
        processor = CSVProcessor(session)
        first = _direct_row(purpose="Lastschrift Einkauf Danke")
        second = _direct_row(date=date(2026, 4, 5), purpose="Lastschrift Einkauf Danke vielmals")
        new, dup = processor.save_transactions([first, second])
        assert (new, dup) == (2, 0)

    def test_two_settlement_rows_are_both_real_purchases(self, session):
        """Two card purchases at the same merchant/amount days apart — both settlement lines, both kept."""
        processor = CSVProcessor(session)
        first = _settlement_row(
            date=date(2026, 4, 1),
            amount=-20.00,
            purpose="Nr xxxx 1022 berlin DE Kaufumsatz 27.03 20.00 ARN74477426093000000000002",
        )
        second = _settlement_row(
            date=date(2026, 4, 6),
            amount=-20.00,
            purpose="Nr xxxx 1022 berlin DE Kaufumsatz 02.04 20.00 ARN74477426093000000000003",
        )
        new, dup = processor.save_transactions([first, second])
        assert (new, dup) == (2, 0)

    def test_single_token_merchant_pair_collapses(self, session):
        """One-word merchant plus city token: settlement tokens are a subset of direct tokens."""
        processor = CSVProcessor(session)
        direct = _direct_row(
            name="IKEA Berlin",
            purpose="Ikea BE Rlin Datum 01.04.2026 Kaufumsatz VISA Card EUR 94,05",
        )
        settlement = _settlement_row(
            name="VISA IKEA",
            purpose="Nr xxxx 1022 berlin DE Kaufumsatz 01.04 94.05 ARN74477426093000000000004",
        )
        new, dup = processor.save_transactions([settlement, direct])
        assert (new, dup) == (1, 1)
        assert session.query(TransactionORM).one().name == "IKEA Berlin"

    def test_different_currency_not_collapsed(self, session):
        processor = CSVProcessor(session)
        new, dup = processor.save_transactions([_direct_row(), _settlement_row(currency="USD")])
        assert (new, dup) == (2, 0)
