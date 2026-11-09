"""CSV import and export functionality."""

import codecs
import csv
import io
import re
import uuid
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal, cast

from sqlalchemy.orm import Session

from ..core.audit_trail import ReviewActor, record_review_event
from ..core.database import CategoryORM, TransactionORM
from ..core.models import TransactionInput
from ..ml.feature_extractor import MerchantCleaner
from .dedup import find_fuzzy_duplicate, keep_preferred_fields, sort_direct_rows_first

DateOrder = Literal["dmy", "mdy"]
"""Day and month order of slash or dash dates such as ``03/04/2025``."""

DATE_ORDERS: tuple[DateOrder, ...] = ("dmy", "mdy")

MAX_REPORTED_ERRORS = 20
"""Row errors listed in an import error message; the rest are counted."""

_DELIMITERS = (";", ",", "\t")
_HEADER_SEARCH_RECORDS = 30
"""Records searched for the header row. DKB exports put account details above it."""

# Candidate header names per field, in priority order, after _normalize_header().
_FIELD_CANDIDATES: dict[str, tuple[str, ...]] = {
    "date": ("date", "datum", "transaction_date", "buchungstag", "buchungsdatum"),
    "amount": ("amount", "betrag", "value", "sum", "summe"),
    "description": ("description", "name", "merchant", "empfaenger", "verwendungszweck", "reference"),
    "name": (
        "name",
        "merchant",
        "empfaenger",
        "zahlungsempfaenger",
        "beguenstigter/zahlungspflichtiger",
        "auftraggeber/beguenstigter",
    ),
    # DKB: separate payer and payee columns; the counterparty depends on the sign.
    "payer": ("zahlungspflichtige*r",),
    "payee": ("zahlungsempfaenger*in",),
    "purpose": ("purpose", "verwendungszweck", "reference", "memo"),
    "value_date": ("value_date", "valuta", "valutadatum", "wertstellung"),
    "category": ("category", "kategorie", "type"),
    "account": ("account", "konto", "account_number"),
    "currency": ("currency", "waehrung", "ccy"),
}
_REQUIRED_FIELDS = ("date", "amount", "description")

_UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})

_ISO_DATE_RE = re.compile(r"(\d{4})([-/])(\d{1,2})\2(\d{1,2})")
_DOTTED_DATE_RE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4}|\d{2})")
_SLASH_DATE_RE = re.compile(r"(\d{1,2})([-/])(\d{1,2})\2(\d{4})")

_AMOUNT_NOISE_RE = re.compile(r"[\s  €]|eur", re.IGNORECASE)
_GROUPING_ONLY_RE = {
    ",": re.compile(r"[+-]?\d{1,3}(?:,\d{3})+-?"),
    ".": re.compile(r"[+-]?\d{1,3}(?:\.\d{3})+-?"),
}
"""Amounts like ``1,234`` that read as either a decimal or a thousands separator."""


class _FileError(ValueError):
    """A problem that rejects the whole file rather than one row."""


def decode_csv_bytes(raw: bytes) -> str:
    """Decode a bank export: UTF-8 (with or without BOM), UTF-16 with BOM, else cp1252.

    German bank exports (e.g. Sparkasse) are often cp1252 / ISO-8859-1. latin-1 is
    the last resort because it decodes any byte string.
    """
    if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return raw.decode("utf-16")
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def format_import_errors(errors: list[str], limit: int = MAX_REPORTED_ERRORS) -> str:
    """Summarize import errors: the count, the first ``limit`` errors, and how many more."""
    if len(errors) == 1:
        return errors[0]
    text = f"{len(errors)} rows have errors, so the file was not imported: {'; '.join(errors[:limit])}"
    if len(errors) > limit:
        text += f"; and {len(errors) - limit} more."
    return text


def number_identical_rows(transactions: list[TransactionInput]) -> None:
    """Number rows with identical content in file order, so each one gets its own id.

    The first row keeps ``occurrence`` 0 and therefore the id it always had. Two bus
    tickets bought on one day at one price are two transactions, not a duplicate.
    """
    seen: Counter[str] = Counter()
    for txn in transactions:
        key = txn.content_key()
        txn.occurrence = seen[key]
        seen[key] += 1


def _normalize_header(header: str) -> str:
    """Lower-case a header, drop ``(...)`` suffixes like ``(€)``, and spell out umlauts."""
    text = header.strip().lstrip("﻿").lower().translate(_UMLAUTS)
    text = re.sub(r"\(.*?\)", "", text)
    text = re.sub(r"\s*/\s*", "/", text)
    return " ".join(text.split())


def _read_records(text: str, delimiter: str, limit: int | None = None) -> list[tuple[int, list[str]]]:
    """Parse CSV text into ``(line number, cells)`` records.

    Strict mode raises ``csv.Error`` on broken quoting (e.g. an unclosed quote)
    instead of folding the following lines into one cell.

    With ``limit`` (the header search) a parse error ends the read and returns
    the records before it; the full read later reports the error.
    """
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
    records: list[tuple[int, list[str]]] = []
    try:
        for cells in reader:
            records.append((reader.line_num, cells))
            if limit is not None and len(records) >= limit:
                break
    except csv.Error:
        if limit is None:
            raise
    return records


def _slash_date_parts(text: str) -> tuple[int, int, int] | None:
    """Split ``A/B/YYYY`` or ``A-B-YYYY`` into ``(A, B, YYYY)``."""
    match = _SLASH_DATE_RE.fullmatch(text)
    if match is None:
        return None
    return int(match[1]), int(match[3]), int(match[4])


def _resolve_date_order(values: list[str], given: DateOrder | None) -> DateOrder | None:
    """Decide the day/month order of a file's slash or dash dates.

    A date with a part above 12 (``25/03/2025``) shows the order. If no date in the
    file shows it and some date could be read both ways, the file is rejected
    unless the caller gives the order.
    """
    if given is not None:
        return given
    day_first = month_first = ambiguous = None
    for value in values:
        parts = _slash_date_parts(value)
        if parts is None:
            continue
        first, second, _ = parts
        if first > 12 >= second:
            day_first = day_first or value
        elif second > 12 >= first:
            month_first = month_first or value
        elif first != second and first <= 12 and second <= 12:
            ambiguous = ambiguous or value
    if day_first and month_first:
        raise _FileError(
            f"The file mixes day-first dates ({day_first}) and month-first dates ({month_first}). "
            "Use one date order for the whole file."
        )
    if day_first:
        return "dmy"
    if month_first:
        return "mdy"
    if ambiguous:
        raise _FileError(
            f"Dates such as {ambiguous} can be read as day/month or as month/day, and no date in the file "
            "shows which. Use YYYY-MM-DD dates, or choose the date order (day first or month first)."
        )
    return None


def _clean_amount(raw: str) -> str:
    return _AMOUNT_NOISE_RE.sub("", raw)


def _resolve_decimal_separator(values: list[str], delimiter: str) -> str:
    """Decide whether a file writes ``1.234,56`` (decimal comma) or ``1,234.56``.

    An amount with both separators, or with a separator not followed by exactly
    three digits, shows the convention. Without such an amount, semicolon files
    are taken as decimal-comma files (the German convention) and others not.
    """
    comma = point = None
    for raw in values:
        text = _clean_amount(raw)
        if "," in text and "." in text:
            if text.rfind(",") > text.rfind("."):
                comma = comma or raw
            else:
                point = point or raw
        elif "," in text and not _GROUPING_ONLY_RE[","].fullmatch(text):
            comma = comma or raw
        elif "." in text and not _GROUPING_ONLY_RE["."].fullmatch(text):
            point = point or raw
    if comma and point:
        raise _FileError(f"Amounts mix decimal commas ({comma}) and decimal points ({point}).")
    if comma:
        return ","
    if point:
        return "."
    return "," if delimiter == ";" else "."


def _parse_amount(raw: str, decimal: str = ".") -> float:
    """Parse an amount such as ``-1.234,56``, ``1,234.56``, ``12,50-`` or ``-3.50 €``."""
    text = _clean_amount(raw)
    if not text:
        raise ValueError("Amount is missing")
    negative = text.endswith("-") and text[:1] not in "+-"
    if negative:
        text = text[:-1]
    thousands = "." if decimal == "," else ","
    match = re.fullmatch(
        rf"([+-]?)(\d{{1,3}}(?:{re.escape(thousands)}\d{{3}})+|\d+)(?:{re.escape(decimal)}(\d+))?", text
    )
    if match is None:
        raise ValueError(f"Invalid amount: {raw!r}")
    value = float(f"{match[2].replace(thousands, '')}.{match[3] or '0'}")
    return -value if negative or match[1] == "-" else value


def _drop_legacy_nan_text(existing: TransactionORM, txn: TransactionInput, cleaner: MerchantCleaner) -> None:
    """Replace the ``"nan"`` an older import stored for an empty cell with ``""``."""
    if existing.purpose == "nan" and txn.purpose == "":
        existing.purpose = ""
    if existing.name == "nan" and txn.name == "":
        existing.name = ""
        existing.merchant_pattern = cleaner.clean("")


class CSVProcessor:
    """Handle CSV import and export operations.

    After :meth:`save_transactions`, ``unknown_categories`` and
    ``ambiguous_categories`` count the CSV category labels that matched no
    category or more than one. Those rows are imported unreviewed.
    """

    def __init__(self, session: Session):
        self.session = session
        self.merchant_cleaner = MerchantCleaner()
        self.unknown_categories: Counter[str] = Counter()
        self.ambiguous_categories: Counter[str] = Counter()

    def import_csv(
        self, file_path: Path, csv_format: str = "generic", date_order: DateOrder | None = None
    ) -> tuple[list[TransactionInput], list[str]]:
        """Read transactions from a CSV file.

        Detects the encoding, the delimiter (``;``, ``,`` or tab), the header row,
        the decimal separator, and the day/month order of the file.

        Args:
            file_path: The CSV file.
            csv_format: Only ``"generic"`` is supported.
            date_order: Day/month order for dates like ``03/04/2025``. When None it
                is inferred from the file, and a file that does not show it is rejected.

        Returns:
            Tuple of (transactions, error messages). Row errors start with ``Line N:``,
            the line number in the file.
        """
        if csv_format != "generic":
            return [], [f"Unknown CSV format: {csv_format}"]
        try:
            text = decode_csv_bytes(file_path.read_bytes())
        except OSError as e:
            return [], [f"Failed to read CSV file: {e}"]

        table = self._locate_header(text)
        if table is None:
            return [], ["Could not detect required columns (date, amount, description)"]
        delimiter, header_index, mapping = table
        try:
            records = _read_records(text, delimiter)
            return self._parse_records(
                records[header_index], records[header_index + 1 :], mapping, delimiter, date_order
            )
        except csv.Error as e:
            return [], [f"Failed to read CSV file: {e}"]
        except _FileError as e:
            return [], [str(e)]

    def _locate_header(self, text: str) -> tuple[str, int, dict[str, str]] | None:
        """Find the delimiter and the first record that holds the required headers."""
        best: tuple[str, int, dict[str, str]] | None = None
        for delimiter in _DELIMITERS:
            records = _read_records(text, delimiter, limit=_HEADER_SEARCH_RECORDS)
            for index, (_, cells) in enumerate(records):
                mapping = self._detect_column_mapping(cells)
                if mapping is not None:
                    if best is None or index < best[1]:
                        best = (delimiter, index, mapping)
                    break
        return best

    def _parse_records(
        self,
        header_record: tuple[int, list[str]],
        records: list[tuple[int, list[str]]],
        mapping: dict[str, str],
        delimiter: str,
        date_order: DateOrder | None,
    ) -> tuple[list[TransactionInput], list[str]]:
        """Turn data records into transactions; collect one error per bad row."""
        header = header_record[1]
        columns = {field: header.index(name) for field, name in mapping.items()}
        rows = [(line, cells) for line, cells in records if any(cell.strip() for cell in cells)]

        def cell(cells: list[str], field: str) -> str:
            index = columns.get(field)
            return cells[index].strip() if index is not None and index < len(cells) else ""

        def counterparty(cells: list[str], amount: float) -> str:
            """The name column; else payee (money out) or payer (money in); else the description."""
            if "name" in columns:
                return cell(cells, "name")
            if "payee" in columns and "payer" in columns:
                return cell(cells, "payee") if amount < 0 else cell(cells, "payer")
            return cell(cells, "description")

        order = _resolve_date_order([cell(c, f) for _, c in rows for f in ("date", "value_date")], date_order)
        decimal = _resolve_decimal_separator([cell(c, "amount") for _, c in rows], delimiter)

        transactions: list[TransactionInput] = []
        errors: list[str] = []
        for line, cells in rows:
            try:
                if any(extra.strip() for extra in cells[len(header) :]):
                    raise ValueError(f"expected {len(header)} cells, found {len(cells)}")
                txn_date = self._parse_date(cell(cells, "date"), order)
                amount = _parse_amount(cell(cells, "amount"), decimal)
                raw_value_date = cell(cells, "value_date")
                transactions.append(
                    TransactionInput(
                        date=txn_date,
                        value_date=self._parse_date(raw_value_date, order) if raw_value_date else None,
                        category=cell(cells, "category") or None,
                        name=counterparty(cells, amount),
                        purpose=cell(cells, "purpose"),
                        account=cell(cells, "account") or None,
                        amount=amount,
                        currency=cell(cells, "currency") or "EUR",
                    )
                )
            except ValueError as e:
                errors.append(f"Line {line}: {e}")

        number_identical_rows(transactions)
        return transactions, errors

    def _detect_column_mapping(self, columns: list[str]) -> dict[str, str] | None:
        """Map fields to CSV headers; None when a required field has no column."""
        normalized = [_normalize_header(col) for col in columns]
        mapping: dict[str, str] = {}
        for field, candidates in _FIELD_CANDIDATES.items():
            for candidate in candidates:
                if candidate in normalized:
                    mapping[field] = columns[normalized.index(candidate)]
                    break
        if not all(key in mapping for key in _REQUIRED_FIELDS):
            return None
        return mapping

    @staticmethod
    def _parse_date(date_str: Any, date_order: DateOrder | None = None) -> date:
        """Parse ``YYYY-MM-DD``, ``YYYY/MM/DD``, ``DD.MM.YYYY``, ``DD.MM.YY`` or ``A/B/YYYY``.

        ``A/B/YYYY`` (also with ``-``) is read in ``date_order``. Without an order
        it is read only when a part above 12 shows the order.
        """
        text = "" if date_str is None else str(date_str).strip()
        if not text:
            raise ValueError("Date is missing")
        if match := _ISO_DATE_RE.fullmatch(text):
            year, month, day = int(match[1]), int(match[3]), int(match[4])
        elif match := _DOTTED_DATE_RE.fullmatch(text):
            day, month, year = int(match[1]), int(match[2]), int(match[3])
            if len(match[3]) == 2:
                year += 2000
        elif parts := _slash_date_parts(text):
            first, second, year = parts
            order = date_order
            if order is None:
                if first > 12 or first == second:
                    order = "dmy"
                elif second > 12:
                    order = "mdy"
                else:
                    raise ValueError(f"Ambiguous date: {text} (day/month order unknown)")
            day, month = (first, second) if order == "dmy" else (second, first)
        else:
            raise ValueError(f"Could not parse date: {text}")
        try:
            return date(year, month, day)
        except ValueError:
            raise ValueError(f"Invalid date: {text}") from None

    def save_transactions(
        self, transactions: list[TransactionInput], import_batch: str | None = None
    ) -> tuple[int, int]:
        """Save transactions to database with deduplication.

        A row whose CSV category matches no category, or matches categories of
        several types that its amount sign cannot tell apart, is imported
        unreviewed and counted in ``unknown_categories`` / ``ambiguous_categories``.

        Returns:
            Tuple of (new_count, duplicate_count)
        """
        if not import_batch:
            import_batch = str(uuid.uuid4())

        number_identical_rows(transactions)
        self.unknown_categories.clear()
        self.ambiguous_categories.clear()
        new_count = 0
        duplicate_count = 0

        # Insert account-direct rows before card-settlement rows so the row
        # with the real purchase date survives fuzzy dedup.
        for txn in sort_direct_rows_first(transactions):
            txn_id = txn.generate_id()

            existing = self._find_existing(txn, txn_id)
            if existing is not None:
                _drop_legacy_nan_text(existing, txn, self.merchant_cleaner)
                duplicate_count += 1
                continue

            # Fuzzy check: delayed card-settlement row for an already-imported purchase
            fuzzy_duplicate = find_fuzzy_duplicate(self.session, txn)
            if fuzzy_duplicate is not None:
                keep_preferred_fields(fuzzy_duplicate, txn, self.merchant_cleaner.clean(txn.name))
                duplicate_count += 1
                continue

            category = self._resolve_category(txn)
            db_txn = TransactionORM(
                id=txn_id,
                date=txn.date,
                value_date=txn.value_date,
                name=txn.name,
                purpose=txn.purpose,
                amount=txn.amount,
                currency=txn.currency,
                imported_at=datetime.now(UTC),
                import_batch=import_batch,
                # A row is reviewed only with a category: never is_reviewed=True with category_id NULL.
                is_reviewed=category is not None,
                category_id=category.id if category is not None else None,
                merchant_pattern=self.merchant_cleaner.clean(txn.name),
            )
            self.session.add(db_txn)
            if category is not None:
                record_review_event(
                    self.session,
                    db_txn,
                    actor=ReviewActor.IMPORT_LABEL,
                    from_category_id=None,
                    to_category_id=int(cast(int, category.id)),
                )
            # Session runs with autoflush=False: flush so later rows in this
            # batch can dedup (exact and fuzzy) against this one.
            self.session.flush()
            new_count += 1

        self.session.commit()
        return new_count, duplicate_count

    def _find_existing(self, txn: TransactionInput, txn_id: str) -> TransactionORM | None:
        """Find the stored row with this id, or with the id an older import gave it.

        Imports before empty cells were read as ``""`` stored them as ``"nan"`` and
        hashed that into the id.
        """
        ids = [txn_id]
        if txn.occurrence == 0:
            names = {txn.name, txn.name or "nan"}
            purposes = {txn.purpose, txn.purpose or "nan"}
            ids += [
                txn.model_copy(update={"name": name, "purpose": purpose}).generate_id()
                for name in names
                for purpose in purposes
                if (name, purpose) != (txn.name, txn.purpose)
            ]
        return self.session.query(TransactionORM).filter(TransactionORM.id.in_(ids)).first()

    def _resolve_category(self, txn: TransactionInput) -> CategoryORM | None:
        """Find the category a CSV label names, or None (counted) when there is not exactly one.

        Names are unique only per type: ``other`` can be both a spending and an
        income category. The amount sign then decides: income for money in,
        spending or saving for money out.
        """
        if not txn.category or not txn.category.strip():
            return None
        label = txn.category.strip().lower()
        matches = self.session.query(CategoryORM).filter(CategoryORM.name == label).all()
        if len(matches) > 1:
            wanted = {"income"} if txn.amount > 0 else {"spending", "saving"}
            matches = [category for category in matches if category.type in wanted]
            if len(matches) != 1:
                self.ambiguous_categories[label] += 1
                return None
        if not matches:
            self.unknown_categories[label] += 1
            return None
        return matches[0]

    def export_transactions(
        self,
        output_path: Path,
        start_date: date | None = None,
        end_date: date | None = None,
        category_ids: list[int] | None = None,
    ) -> None:
        """Export transactions to CSV."""
        query = self.session.query(TransactionORM)

        if start_date:
            query = query.filter(TransactionORM.date >= start_date)
        if end_date:
            query = query.filter(TransactionORM.date <= end_date)
        if category_ids:
            query = query.filter(TransactionORM.category_id.in_(category_ids))

        transactions = query.order_by(TransactionORM.date.desc()).all()

        # Get categories for lookup
        categories = {cat.id: cat.name for cat in self.session.query(CategoryORM).all()}

        with open(output_path, "w", newline="", encoding="utf-8") as csvfile:
            writer = csv.writer(csvfile)

            # Header
            writer.writerow(
                [
                    "id",
                    "date",
                    "value_date",
                    "name",
                    "purpose",
                    "amount",
                    "currency",
                    "category",
                    "predicted_category",
                    "confidence_score",
                    "is_reviewed",
                ]
            )

            # Data
            for txn in transactions:
                category_name = categories.get(txn.category_id, "") if txn.category_id else ""
                predicted_category_name = (
                    categories.get(txn.predicted_category_id, "") if txn.predicted_category_id else ""
                )

                writer.writerow(
                    [
                        txn.id,
                        txn.date.isoformat(),
                        txn.value_date.isoformat() if txn.value_date else "",
                        txn.name,
                        txn.purpose,
                        txn.amount,
                        txn.currency,
                        category_name,
                        predicted_category_name,
                        txn.confidence_score or "",
                        txn.is_reviewed,
                    ]
                )


def create_synthetic_transactions() -> list[TransactionInput]:
    """Create synthetic transaction data for testing."""
    import random
    from datetime import timedelta

    base_date = date(2024, 1, 1)
    transactions = []

    # Grocery transactions
    grocery_merchants = ["EDEKA", "REWE", "ALDI", "LIDL", "Kaufland"]
    for i in range(30):
        txn_date = base_date + timedelta(days=random.randint(0, 330))
        merchant = random.choice(grocery_merchants)
        amount = -round(random.uniform(15.50, 89.99), 2)
        transactions.append(
            TransactionInput(
                date=txn_date,
                name=f"{merchant} Markt {random.randint(1001, 9999)}",
                purpose="Lastschrift",
                amount=amount,
                category="groceries",
            )
        )

    # Restaurant transactions
    restaurants = ["McDonald's", "Burger King", "Pizza Express", "Vapiano", "Subway"]
    for i in range(15):
        txn_date = base_date + timedelta(days=random.randint(0, 330))
        restaurant = random.choice(restaurants)
        amount = -round(random.uniform(8.50, 45.90), 2)
        transactions.append(
            TransactionInput(
                date=txn_date,
                name=f"{restaurant} Berlin",
                purpose="Kartenzahlung",
                amount=amount,
                category="restaurants",
            )
        )

    # Salary
    for month in range(12):
        txn_date = date(2024, month + 1, 25)
        transactions.append(
            TransactionInput(
                date=txn_date, name="TECH COMPANY GMBH", purpose="Gehalt Januar 2024", amount=3500.00, category="salary"
            )
        )

    # Rent
    for month in range(12):
        txn_date = date(2024, month + 1, 1)
        transactions.append(
            TransactionInput(
                date=txn_date, name="IMMOBILIEN AG", purpose="Miete Wohnung", amount=-1200.00, category="rent"
            )
        )

    # Utilities
    utility_companies = ["Vattenfall", "GASAG", "BWB", "Telekom"]
    for company in utility_companies:
        for quarter in range(4):
            txn_date = base_date + timedelta(days=quarter * 90 + random.randint(1, 30))
            amount = -round(random.uniform(45.00, 120.00), 2)
            transactions.append(
                TransactionInput(
                    date=txn_date, name=company, purpose="Lastschrift Rechnung", amount=amount, category="utilities"
                )
            )

    return transactions
