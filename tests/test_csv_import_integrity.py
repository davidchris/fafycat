"""CSV import integrity: ids, empty fields, dates, bank formats, labels, uploads.

The files under ``tests/fixtures/bank_exports`` are synthetic. They copy the
shape of real Sparkasse (CSV-CAMT V2, cp1252) and DKB (2023+ layout, UTF-8
with BOM, preamble lines) exports, not their data.
"""

import io
import json
import tempfile
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from fafycat.core.database import CategoryORM, TransactionORM
from fafycat.core.models import TransactionInput
from fafycat.data.csv_processor import CSVProcessor, format_import_errors

BANK_EXPORTS = Path(__file__).parent / "fixtures" / "bank_exports"


def _write(tmp_path: Path, content: str | bytes, name: str = "t.csv") -> Path:
    path = tmp_path / name
    if isinstance(content, str):
        path.write_text(content, encoding="utf-8")
    else:
        path.write_bytes(content)
    return path


def _parse(db_session: Session, path: Path, **kwargs) -> tuple[list[TransactionInput], list[str]]:
    return CSVProcessor(db_session).import_csv(path, **kwargs)


def _import(db_session: Session, path: Path, **kwargs) -> tuple[int, int]:
    processor = CSVProcessor(db_session)
    transactions, errors = processor.import_csv(path, **kwargs)
    assert errors == []
    return processor.save_transactions(transactions)


def _add_category(db_session: Session, name: str, cat_type: str) -> CategoryORM:
    category = CategoryORM(name=name, type=cat_type, budget=0.0)
    db_session.add(category)
    db_session.commit()
    return category


TWIN_TICKETS = (
    "date,name,purpose,amount\n2025-03-04,BVG Ticket,Einzelfahrt,-3.50\n2025-03-04,BVG Ticket,Einzelfahrt,-3.50\n"
)


class TestIdenticalRowsInOneFile:
    """B6: two identical same-day purchases are two transactions."""

    def test_both_identical_rows_are_kept(self, db_session, tmp_path):
        new, dup = _import(db_session, _write(tmp_path, TWIN_TICKETS))

        assert (new, dup) == (2, 0)
        assert db_session.query(TransactionORM).count() == 2

    def test_reimporting_the_same_file_adds_nothing(self, db_session, tmp_path):
        path = _write(tmp_path, TWIN_TICKETS)
        _import(db_session, path)

        assert _import(db_session, path) == (0, 2)
        assert db_session.query(TransactionORM).count() == 2

    def test_first_occurrence_keeps_the_pre_fix_id(self, db_session, tmp_path):
        """Ids of already-imported rows must not change, or re-imports would duplicate them."""
        transactions, _ = _parse(db_session, _write(tmp_path, TWIN_TICKETS))

        first, second = (t.generate_id() for t in transactions)
        assert first == "dfc219c3531baee7"  # sha256("2025-03-04|-3.5|BVG Ticket|Einzelfahrt")[:16]
        assert second != first

    def test_twin_lost_by_an_old_import_is_recovered(self, db_session, tmp_path):
        """A database from before the fix holds only the first twin; re-importing adds the second."""
        path = _write(tmp_path, TWIN_TICKETS)
        transactions, _ = _parse(db_session, path)
        CSVProcessor(db_session).save_transactions(transactions[:1])

        assert _import(db_session, path) == (1, 1)


class TestEmptyOptionalText:
    """B7: empty cells are empty strings, never the text "nan"."""

    def test_empty_purpose_is_stored_as_empty_string(self, db_session, tmp_path):
        path = _write(tmp_path, "date,name,purpose,amount,currency\n2025-03-04,Kiosk,,-2.00,\n")
        _import(db_session, path)

        row = db_session.query(TransactionORM).one()
        assert (row.name, row.purpose, row.currency) == ("Kiosk", "", "EUR")

    def test_reimport_matches_a_row_stored_with_purpose_nan(self, db_session, tmp_path):
        """Rows imported before the fix carry purpose "nan" and an id hashed from it."""
        legacy = TransactionInput(date=date(2025, 3, 4), name="Kiosk", purpose="nan", amount=-2.0)
        CSVProcessor(db_session).save_transactions([legacy])

        path = _write(tmp_path, "date,name,purpose,amount\n2025-03-04,Kiosk,,-2.00\n")

        assert _import(db_session, path) == (0, 1)
        row = db_session.query(TransactionORM).one()
        assert (row.id, row.purpose) == (legacy.generate_id(), "")


class TestDateOrder:
    """B8: no silent guess between day-first and month-first."""

    def test_fully_ambiguous_file_is_rejected(self, db_session, tmp_path):
        path = _write(tmp_path, "date,name,amount\n03/04/2025,Shop,-1.00\n05/06/2025,Shop,-2.00\n")

        transactions, errors = _parse(db_session, path)

        assert transactions == []
        assert len(errors) == 1
        assert "03/04/2025" in errors[0]
        assert "YYYY-MM-DD" in errors[0]

    @pytest.mark.parametrize(("order", "expected"), [("dmy", date(2025, 4, 3)), ("mdy", date(2025, 3, 4))])
    def test_given_order_resolves_ambiguous_dates(self, db_session, tmp_path, order, expected):
        path = _write(tmp_path, "date,name,amount\n03/04/2025,Shop,-1.00\n")

        transactions, errors = _parse(db_session, path, date_order=order)

        assert errors == []
        assert transactions[0].date == expected

    def test_order_is_inferred_from_an_unambiguous_row(self, db_session, tmp_path):
        path = _write(tmp_path, "date,name,amount\n03/04/2025,Shop,-1.00\n04/25/2025,Shop,-2.00\n")

        transactions, errors = _parse(db_session, path)

        assert errors == []
        assert [t.date for t in transactions] == [date(2025, 3, 4), date(2025, 4, 25)]

    def test_value_date_column_counts_as_evidence(self, db_session, tmp_path):
        path = _write(tmp_path, "date,value_date,name,amount\n03/04/2025,13/04/2025,Shop,-1.00\n")

        transactions, errors = _parse(db_session, path)

        assert errors == []
        assert (transactions[0].date, transactions[0].value_date) == (date(2025, 4, 3), date(2025, 4, 13))

    def test_file_mixing_both_orders_is_rejected(self, db_session, tmp_path):
        path = _write(tmp_path, "date,name,amount\n25/03/2025,Shop,-1.00\n03/25/2025,Shop,-2.00\n")

        transactions, errors = _parse(db_session, path)

        assert transactions == []
        assert len(errors) == 1
        assert "25/03/2025" in errors[0] and "03/25/2025" in errors[0]

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("2025-03-04", date(2025, 3, 4)), ("04.03.2025", date(2025, 3, 4)), ("04.03.25", date(2025, 3, 4))],
    )
    def test_unambiguous_formats_need_no_order(self, db_session, tmp_path, raw, expected):
        path = _write(tmp_path, f"date,name,amount\n{raw},Shop,-1.00\n")

        transactions, errors = _parse(db_session, path)

        assert errors == []
        assert transactions[0].date == expected


class TestGermanAndOtherLayouts:
    """B9: delimiters, decimal commas, encodings, preamble lines."""

    def test_semicolon_and_decimal_comma(self, db_session, tmp_path):
        path = _write(tmp_path, "Datum;Name;Betrag\n04.03.2025;Laden;-1.234,56\n05.03.2025;Laden;12,5\n")

        transactions, errors = _parse(db_session, path)

        assert errors == []
        assert [t.amount for t in transactions] == [-1234.56, 12.5]

    def test_tab_delimiter(self, db_session, tmp_path):
        path = _write(tmp_path, "date\tname\tamount\n2025-03-04\tShop\t-9.99\n")

        transactions, errors = _parse(db_session, path)

        assert errors == []
        assert transactions[0].amount == -9.99

    def test_comma_file_with_thousands_separator(self, db_session, tmp_path):
        path = _write(tmp_path, 'date,name,amount\n2025-03-04,Shop,"-1,234.50"\n2025-03-05,Shop,-3.10\n')

        transactions, errors = _parse(db_session, path)

        assert errors == []
        assert [t.amount for t in transactions] == [-1234.5, -3.1]

    def test_cp1252_file(self, db_session, tmp_path):
        path = _write(tmp_path, "Datum;Name;Betrag\n04.03.2025;Bäckerei Müller;-4,80\n".encode("cp1252"))

        transactions, errors = _parse(db_session, path)

        assert errors == []
        assert transactions[0].name == "Bäckerei Müller"

    def test_utf8_bom_header(self, db_session, tmp_path):
        path = _write(tmp_path, "﻿date,name,amount\n2025-03-04,Shop,-1.00\n".encode())

        transactions, errors = _parse(db_session, path)

        assert errors == []
        assert len(transactions) == 1

    def test_sparkasse_export(self, db_session):
        transactions, errors = _parse(db_session, BANK_EXPORTS / "sparkasse_camt_v2.csv")

        assert errors == []
        assert [(t.date, t.name, t.purpose, t.amount) for t in transactions] == [
            (date(2025, 2, 28), "Beispiel GmbH", "Gehalt Februar 2025", 3250.0),
            (date(2025, 3, 3), "Bäckerei Müller", "Einkauf Filiale 12", -4.8),
            (date(2025, 3, 3), "Verkehrsbetriebe Musterstadt", "Einzelfahrschein AB", -3.5),
            (date(2025, 3, 3), "Verkehrsbetriebe Musterstadt", "Einzelfahrschein AB", -3.5),
            (date(2025, 3, 4), "Hausverwaltung Schröder", "Miete März", -1150.0),
            (date(2025, 3, 31), "", "", -6.95),
        ]
        assert all(t.value_date == t.date and t.currency == "EUR" for t in transactions)

    def test_sparkasse_export_saves_every_row_once(self, db_session):
        path = BANK_EXPORTS / "sparkasse_camt_v2.csv"

        assert _import(db_session, path) == (6, 0)
        assert _import(db_session, path) == (0, 6)

    def test_dkb_export_picks_counterparty_by_sign(self, db_session):
        transactions, errors = _parse(db_session, BANK_EXPORTS / "dkb_giro_2025.csv")

        assert errors == []
        assert [(t.date, t.name, t.purpose, t.amount) for t in transactions] == [
            (date(2025, 3, 31), "Supermarkt Beispiel GmbH", "Einkauf vom 30.03.", -23.45),
            (date(2025, 3, 28), "Beispiel AG", "Lohn März 2025", 2800.0),
            (date(2025, 3, 27), "Stadtwerke Musterstadt", "Abschlag Strom", -1234.56),
        ]

    def test_invalid_amount_is_a_row_error(self, db_session, tmp_path):
        path = _write(tmp_path, "date,name,amount\n2025-03-04,Shop,12abc\n")

        _, errors = _parse(db_session, path)

        assert errors == ["Line 2: Invalid amount: '12abc'"]


class TestRowErrors:
    """U10: every bad row is counted, not only the first three."""

    def test_all_bad_rows_are_reported_with_line_numbers(self, db_session, tmp_path):
        body = "".join(f"2025-03-{day:02d},Shop,oops\n" for day in range(1, 13))
        path = _write(tmp_path, "date,name,amount\n" + body)

        _, errors = _parse(db_session, path)

        assert len(errors) == 12
        assert errors[0].startswith("Line 2:")
        assert errors[-1].startswith("Line 13:")

    def test_summary_names_the_count_and_the_rest(self):
        errors = [f"Line {n}: Invalid amount: 'x'" for n in range(2, 27)]

        summary = format_import_errors(errors, limit=20)

        assert summary.startswith("25 rows have errors, so the file was not imported: Line 2:")
        assert "Line 21:" in summary
        assert "Line 22:" not in summary
        assert summary.endswith("and 5 more.")


class TestLabelledRows:
    """B5 and B14: a CSV category label never leaves a reviewed row without a category."""

    def test_unknown_category_is_imported_unreviewed_and_reported(self, db_session, tmp_path):
        path = _write(tmp_path, "date,name,amount,category\n2025-03-04,Shop,-1.00,no_such_category\n")
        processor = CSVProcessor(db_session)
        transactions, _ = processor.import_csv(path)

        processor.save_transactions(transactions)

        row = db_session.query(TransactionORM).one()
        assert (row.is_reviewed, row.category_id) == (False, None)
        assert processor.unknown_categories == {"no_such_category": 1}

    def test_known_category_is_reviewed(self, db_session, tmp_path):
        groceries = _add_category(db_session, "groceries", "spending")
        path = _write(tmp_path, "date,name,amount,category\n2025-03-04,Shop,-1.00,Groceries\n")

        _import(db_session, path)

        row = db_session.query(TransactionORM).one()
        assert (row.is_reviewed, row.category_id) == (True, groceries.id)

    def test_same_name_categories_resolve_by_amount_sign(self, db_session, tmp_path):
        spending_other = _add_category(db_session, "other", "spending")
        income_other = _add_category(db_session, "other", "income")
        path = _write(
            tmp_path, "date,name,amount,category\n2025-03-04,Shop,-1.00,other\n2025-03-05,Refund,5.00,other\n"
        )

        _import(db_session, path)

        rows = {row.name: row.category_id for row in db_session.query(TransactionORM)}
        assert rows == {"Shop": spending_other.id, "Refund": income_other.id}

    def test_same_name_categories_without_a_sign_match_are_reported(self, db_session, tmp_path):
        _add_category(db_session, "investment", "spending")
        _add_category(db_session, "investment", "saving")
        path = _write(tmp_path, "date,name,amount,category\n2025-03-04,Broker,-100.00,investment\n")
        processor = CSVProcessor(db_session)
        transactions, _ = processor.import_csv(path)

        processor.save_transactions(transactions)

        row = db_session.query(TransactionORM).one()
        assert (row.is_reviewed, row.category_id) == (False, None)
        assert processor.ambiguous_categories == {"investment": 1}


class TestUploadEndpoints:
    """B16, B24, S6: all three upload routes share one checked path."""

    ROUTES = ["/api/upload/csv", "/api/upload/csv-htmx", "/upload-csv"]
    CP1252_CSV = "Datum;Name;Betrag\n04.03.2025;Bäckerei Müller;-4,80\n".encode("cp1252")

    @pytest.mark.parametrize("route", ROUTES)
    def test_upper_case_extension_is_accepted(self, test_client, db_session, route):
        files = {"file": ("statement.CSV", io.BytesIO(b"date,name,amount\n2025-03-04,Shop,-1.00\n"), "text/csv")}

        response = test_client.post(route, files=files)

        assert response.status_code == 200
        assert db_session.query(TransactionORM).count() == 1

    @pytest.mark.parametrize("route", ROUTES)
    def test_cp1252_upload_is_decoded(self, test_client, db_session, route):
        files = {"file": ("bank.csv", io.BytesIO(self.CP1252_CSV), "text/csv")}

        response = test_client.post(route, files=files)

        assert response.status_code == 200
        assert db_session.query(TransactionORM.name).scalar() == "Bäckerei Müller"

    @pytest.mark.parametrize("route", ROUTES)
    def test_size_limit_is_enforced_while_reading(self, test_client, db_session, monkeypatch, route):
        monkeypatch.setattr("fafycat.api.upload.MAX_UPLOAD_BYTES", 64)
        body = b"date,name,amount\n" + b"2025-03-04,Shop,-1.00\n" * 10
        files = {"file": ("big.csv", io.BytesIO(body), "text/csv")}

        response = test_client.post(route, files=files)

        assert "File too large" in response.text
        assert db_session.query(TransactionORM).count() == 0

    @pytest.mark.parametrize("route", ROUTES)
    def test_temp_file_is_removed_when_import_fails(self, test_client, monkeypatch, tmp_path, route):
        spool = tmp_path / "spool"
        spool.mkdir()
        monkeypatch.setattr(tempfile, "tempdir", str(spool))
        files = {"file": ("bad.csv", io.BytesIO(b"date,name,amount\n2025-03-04,Shop,oops\n"), "text/csv")}

        response = test_client.post(route, files=files)

        assert "Line 2: Invalid amount" in response.text
        assert list(spool.iterdir()) == []

    def test_htmx_upload_accepts_a_date_order(self, test_client, db_session):
        files = {"file": ("us.csv", io.BytesIO(b"date,name,amount\n03/04/2025,Shop,-1.00\n"), "text/csv")}

        response = test_client.post("/api/upload/csv-htmx", files=files, data={"date_order": "mdy"})

        assert "Successfully imported" in response.text
        assert db_session.query(TransactionORM.date).scalar() == date(2025, 3, 4)

    def test_htmx_upload_reports_unknown_categories(self, test_client):
        csv_bytes = b"date,name,amount,category\n2025-03-04,Shop,-1.00,mystery\n"
        files = {"file": ("labelled.csv", io.BytesIO(csv_bytes), "text/csv")}

        response = test_client.post("/api/upload/csv-htmx", files=files)

        assert "Successfully imported" in response.text
        assert "mystery" in response.text


class TestCliImport:
    """The CLI import reports ambiguous dates and takes ``--date-order``."""

    AMBIGUOUS = "date,name,amount\n03/04/2025,Shop,-1.00\n"

    def test_ambiguous_dates_fail_without_order(self, cli_runner, tmp_path):
        path = _write(tmp_path, self.AMBIGUOUS)

        result = cli_runner("import", str(path))

        assert result.returncode == 1
        assert "03/04/2025" in json.loads(result.stdout)["error"]

    def test_date_order_flag_imports(self, cli_runner, tmp_path):
        path = _write(tmp_path, self.AMBIGUOUS)

        result = cli_runner("import", str(path), "--date-order", "mdy")

        assert result.returncode == 0, result.stdout + result.stderr
        assert json.loads(result.stdout)["transactions_imported"] == 1
