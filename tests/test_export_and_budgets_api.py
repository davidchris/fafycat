"""Export API: real CSV and Excel files, client errors, and spreadsheet-formula neutralisation."""

import csv
import io
from datetime import date

import openpyxl
import pytest

from fafycat.core.database import CategoryORM, TransactionORM

HOSTILE_NAME = '=HYPERLINK("http://evil.example","click")'


@pytest.fixture
def exported_rows(db_session) -> None:
    groceries = CategoryORM(name="groceries", type="spending")
    db_session.add(groceries)
    db_session.commit()
    db_session.add_all(
        [
            TransactionORM(
                id="t-hostile",
                date=date(2024, 3, 2),
                name=HOSTILE_NAME,
                purpose="@SUM(A1:A9)",
                amount=-42.5,
                category_id=groceries.id,
                is_reviewed=True,
                import_batch="b",
            ),
            TransactionORM(
                id="t-plain",
                date=date(2024, 3, 1),
                name="EDEKA",
                purpose="-weekly shop",
                amount=-10.0,
                category_id=groceries.id,
                is_reviewed=True,
                import_batch="b",
            ),
        ]
    )
    db_session.commit()


def test_csv_export_neutralises_formulas_but_keeps_negative_amounts(test_client, exported_rows):
    response = test_client.post("/api/export/transactions", json={"format": "csv"})

    assert response.status_code == 200
    rows = {row["id"]: row for row in csv.DictReader(io.StringIO(response.text))}
    assert rows["t-hostile"]["name"] == "'" + HOSTILE_NAME
    assert rows["t-hostile"]["purpose"] == "'@SUM(A1:A9)"
    assert rows["t-plain"]["name"] == "EDEKA"
    assert rows["t-plain"]["purpose"] == "'-weekly shop"
    assert float(rows["t-hostile"]["amount"]) == -42.5


def test_excel_export_is_a_workbook_without_formulas(test_client, exported_rows):
    response = test_client.post("/api/export/transactions", json={"format": "excel"})

    assert response.status_code == 200, response.text
    workbook = openpyxl.load_workbook(io.BytesIO(response.content))
    assert workbook.sheetnames == ["Transactions", "Category_Summary", "Monthly_Summary"]
    sheet = workbook["Transactions"]
    header = [cell.value for cell in sheet[1]]
    rows = [dict(zip(header, (cell.value for cell in row), strict=True)) for row in sheet.iter_rows(min_row=2)]
    hostile = next(row for row in rows if row["id"] == "t-hostile")
    assert hostile["name"] == "'" + HOSTILE_NAME
    assert hostile["amount"] == -42.5
    assert all(cell.data_type != "f" for row in sheet.iter_rows() for cell in row)


def test_empty_export_is_404(test_client):
    response = test_client.post("/api/export/transactions", json={"format": "csv"})

    assert response.status_code == 404
    assert response.json()["detail"] == "No transactions found for export"


def test_budget_year_out_of_range_is_400(test_client):
    response = test_client.get("/api/budgets/2019")

    assert response.status_code == 400
    assert response.json()["detail"] == "Year must be between 2020 and 2030"
