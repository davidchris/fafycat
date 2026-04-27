"""Unified CLI for fafycat."""

import argparse
import json
import logging
import os
import sys
from collections.abc import Callable
from datetime import date
from pathlib import Path


def _apply_data_dir_override(data_dir: Path | None) -> None:
    """Set environment overrides so config derives paths from data_dir."""
    if data_dir is None:
        return

    resolved_data_dir = data_dir.resolve()
    os.environ["FAFYCAT_DATA_DIR"] = str(resolved_data_dir)
    os.environ.setdefault("FAFYCAT_MODEL_DIR", str(resolved_data_dir / "models"))
    os.environ.setdefault("FAFYCAT_EXPORT_DIR", str(resolved_data_dir / "exports"))


def _legacy_database_url(data_dir: Path | None, dev: bool) -> str | None:
    """Return the legacy repo-local database URL when appropriate.

    Backward compatibility only applies to production `serve` with no explicit
    database/data-dir override. Development mode retains the mode-specific DB.
    """
    if dev or data_dir is not None or "FAFYCAT_DB_URL" in os.environ:
        return None

    legacy_db = (Path.cwd() / "data" / "fafycat_prod.db").resolve()
    if legacy_db.exists():
        return f"sqlite:///{legacy_db}"

    return None


def _setup_dev_database() -> None:
    """Seed the dev database with synthetic data if empty."""
    from fafycat.api.services import CategoryService, TransactionService
    from fafycat.core.config import AppConfig
    from fafycat.core.database import DatabaseManager
    from fafycat.data.csv_processor import CSVProcessor, create_synthetic_transactions

    config = AppConfig()
    db_manager = DatabaseManager(config)
    db_manager.create_tables()

    with db_manager.get_session() as session:
        categories = CategoryService.get_categories(session)
        if not categories:
            print("🔄 Initializing default categories...")
            db_manager.init_default_categories()
            print("✅ Created default categories")

        transactions = TransactionService.get_transactions(session, limit=1)
        if not transactions:
            print("🔄 Setting up synthetic test data...")
            processor = CSVProcessor(session)
            synthetic_transactions = create_synthetic_transactions()
            new_count, _ = processor.save_transactions(synthetic_transactions, "synthetic_batch")
            print(f"✅ Created {new_count} synthetic transactions")


def cmd_serve(args: argparse.Namespace) -> None:
    """Start the fafycat web server."""
    _apply_data_dir_override(args.data_dir)

    if args.dev:
        os.environ.setdefault("FAFYCAT_ENV", "development")
        db_name = "fafycat_dev.db"
    else:
        os.environ.setdefault("FAFYCAT_ENV", "production")
        db_name = "fafycat_prod.db"

    if "FAFYCAT_DB_URL" not in os.environ:
        legacy_db_url = _legacy_database_url(args.data_dir, args.dev)
        if legacy_db_url is not None:
            os.environ["FAFYCAT_DB_URL"] = legacy_db_url

    if "FAFYCAT_DB_URL" not in os.environ:
        from platformdirs import user_data_dir

        data_dir = Path(os.getenv("FAFYCAT_DATA_DIR", user_data_dir("fafycat")))
        os.environ["FAFYCAT_DB_URL"] = f"sqlite:///{data_dir / db_name}"

    port = args.port or (8001 if args.dev else 8000)
    host = args.host or "127.0.0.1"

    from fafycat.core.config import AppConfig

    config = AppConfig()
    config.ensure_dirs()

    if args.dev:
        _setup_dev_database()

    env_label = "DEVELOPMENT" if args.dev else "PRODUCTION"
    print(f"🐱 Starting FafyCat in {env_label} mode")
    print(f"📊 Database: {os.environ['FAFYCAT_DB_URL']}")
    print(f"🌐 http://localhost:{port}")
    print(f"📚 API docs: http://localhost:{port}/docs")
    print("-" * 50)

    import uvicorn

    uvicorn.run(
        "fafycat.app:app",
        host=host,
        port=port,
        reload=args.dev,
        log_level="info",
    )


def cmd_import(args: argparse.Namespace) -> None:
    """Import a CSV file."""
    _apply_data_dir_override(args.data_dir)

    csv_path = Path(args.file)
    if not csv_path.exists():
        print(json.dumps({"error": f"File not found: {csv_path}"}))
        sys.exit(1)

    from fafycat.api.upload import predict_transaction_categories
    from fafycat.core.config import AppConfig
    from fafycat.core.database import DatabaseManager
    from fafycat.data.csv_processor import CSVProcessor

    config = AppConfig()
    config.ensure_dirs()
    db_manager = DatabaseManager(config)
    db_manager.create_tables()

    with db_manager.get_session() as session:
        processor = CSVProcessor(session)
        transactions, errors = processor.import_csv(csv_path)

        if errors:
            print(json.dumps({"error": f"CSV processing errors: {'; '.join(errors[:5])}"}))
            sys.exit(1)

        if not transactions:
            print(json.dumps({"error": "No valid transactions found in CSV"}))
            sys.exit(1)

        new_count, duplicate_count = processor.save_transactions(transactions)
        cat_summary = predict_transaction_categories(session, transactions, new_count)

        result = {
            "filename": csv_path.name,
            "rows_processed": len(transactions),
            "transactions_imported": new_count,
            "duplicates_skipped": duplicate_count,
            **cat_summary,
        }
        print(json.dumps(result, indent=2))


def cmd_cat_list(args: argparse.Namespace) -> None:
    """List categories as JSON."""
    _apply_data_dir_override(args.data_dir)

    logging.disable(logging.WARNING)

    from fafycat.api.services import CategoryService
    from fafycat.cli_query.output import emit_success
    from fafycat.core.config import AppConfig
    from fafycat.core.database import DatabaseManager

    config = AppConfig()
    db_manager = DatabaseManager(config)
    db_manager.create_tables()

    with db_manager.get_session() as session:
        categories = CategoryService.get_categories(session, include_inactive=args.include_inactive)

    emit_success([c.model_dump() for c in categories])


def cmd_tx_list(args: argparse.Namespace) -> None:
    """List transactions as a paginated JSON envelope."""
    _apply_data_dir_override(args.data_dir)

    logging.disable(logging.WARNING)

    from fafycat.api.services import TransactionService
    from fafycat.cli_query.date_range import resolve_date_range
    from fafycat.cli_query.output import emit_error, emit_success
    from fafycat.core.config import AppConfig
    from fafycat.core.database import DatabaseManager

    _has_date_arg = (
        args.start is not None
        or args.end is not None
        or args.month is not None
        or args.year is not None
        or args.this_month
        or args.last_month
        or args.ytd
        or args.last_n_months is not None
    )
    start_date: date | None = None
    end_date: date | None = None
    if _has_date_arg:
        try:
            start_date, end_date = resolve_date_range(args)
        except ValueError as exc:
            emit_error(str(exc))

    limit = min(args.limit, 500)

    is_reviewed: bool | None = None
    if args.reviewed:
        is_reviewed = True
    elif args.unreviewed:
        is_reviewed = False

    config = AppConfig()
    db_manager = DatabaseManager(config)
    db_manager.create_tables()

    with db_manager.get_session() as session:
        result = TransactionService.get_transactions_with_pagination(
            session,
            skip=args.skip,
            limit=limit,
            is_reviewed=is_reviewed,
            category=args.category or None,
            search=args.search or "",
            start_date=start_date,
            end_date=end_date,
        )

    transactions = [t.model_dump(mode="json") for t in result["transactions"]]
    pagination = result["pagination_info"]
    emit_success(
        {
            "transactions": transactions,
            "total_count": pagination["total_count"],
            "has_next": pagination["has_next"],
            "skip": args.skip,
            "limit": limit,
        }
    )


def cmd_budget_show(args: argparse.Namespace) -> None:
    """Return per-category budgets for a year as JSON."""
    _apply_data_dir_override(args.data_dir)

    logging.disable(logging.WARNING)

    from fafycat.api.services import BudgetService
    from fafycat.cli_query.output import emit_success
    from fafycat.core.config import AppConfig
    from fafycat.core.database import DatabaseManager

    config = AppConfig()
    db_manager = DatabaseManager(config)
    db_manager.create_tables()

    with db_manager.get_session() as session:
        result = BudgetService.get_budgets_for_year(session, args.year)

    emit_success(result)


def cmd_analytics_monthly(args: argparse.Namespace) -> None:
    """Return monthly income/spending/saving totals as JSON."""
    _apply_data_dir_override(args.data_dir)
    logging.disable(logging.WARNING)

    from fafycat.api.services import AnalyticsService
    from fafycat.cli_query.date_range import resolve_date_range
    from fafycat.cli_query.output import emit_error, emit_success
    from fafycat.core.config import AppConfig
    from fafycat.core.database import DatabaseManager

    year: int | None = None
    start_date: date | None = None
    end_date: date | None = None

    _has_date_sugar = (
        args.month is not None
        or args.this_month
        or args.last_month
        or args.ytd
        or args.last_n_months is not None
        or args.start is not None
        or args.end is not None
    )
    if args.year is not None:
        year = args.year
    elif _has_date_sugar:
        try:
            start_date, end_date = resolve_date_range(args)
        except ValueError as exc:
            emit_error(str(exc))

    config = AppConfig()
    db_manager = DatabaseManager(config)
    db_manager.create_tables()

    with db_manager.get_session() as session:
        result = AnalyticsService.get_monthly_summary(session, year=year, start_date=start_date, end_date=end_date)

    emit_success(result)


def cmd_analytics_breakdown(args: argparse.Namespace) -> None:
    """Return per-category spending totals for a date range as JSON."""
    _apply_data_dir_override(args.data_dir)
    logging.disable(logging.WARNING)

    from fafycat.api.services import AnalyticsService
    from fafycat.cli_query.date_range import resolve_date_range
    from fafycat.cli_query.output import emit_error, emit_success
    from fafycat.core.config import AppConfig
    from fafycat.core.database import DatabaseManager

    start_date: date | None = None
    end_date: date | None = None

    _has_date_arg = (
        args.start is not None
        or args.end is not None
        or args.month is not None
        or args.year is not None
        or args.this_month
        or args.last_month
        or args.ytd
        or args.last_n_months is not None
    )
    if _has_date_arg:
        try:
            start_date, end_date = resolve_date_range(args)
        except ValueError as exc:
            emit_error(str(exc))

    config = AppConfig()
    db_manager = DatabaseManager(config)
    db_manager.create_tables()

    with db_manager.get_session() as session:
        result = AnalyticsService.get_category_breakdown(
            session,
            start_date=start_date,
            end_date=end_date,
            category_type=args.type or None,
        )

    emit_success(result)


def cmd_analytics_variance(args: argparse.Namespace) -> None:
    """Return budget-vs-actual variance per category for a date range as JSON."""
    _apply_data_dir_override(args.data_dir)
    logging.disable(logging.WARNING)

    from fafycat.api.services import AnalyticsService
    from fafycat.cli_query.date_range import resolve_date_range
    from fafycat.cli_query.output import emit_error, emit_success
    from fafycat.core.config import AppConfig
    from fafycat.core.database import DatabaseManager

    start_date: date | None = None
    end_date: date | None = None

    _has_date_arg = (
        args.start is not None
        or args.end is not None
        or args.month is not None
        or args.year is not None
        or args.this_month
        or args.last_month
        or args.ytd
        or args.last_n_months is not None
    )
    if _has_date_arg:
        try:
            start_date, end_date = resolve_date_range(args)
        except ValueError as exc:
            emit_error(str(exc))

    config = AppConfig()
    db_manager = DatabaseManager(config)
    db_manager.create_tables()

    with db_manager.get_session() as session:
        result = AnalyticsService.get_budget_variance(
            session,
            start_date=start_date,
            end_date=end_date,
        )

    emit_success(result)


def cmd_analytics_savings(args: argparse.Namespace) -> None:
    """Return monthly and cumulative savings for a date range as JSON."""
    _apply_data_dir_override(args.data_dir)
    logging.disable(logging.WARNING)

    from fafycat.api.services import AnalyticsService
    from fafycat.cli_query.date_range import resolve_date_range
    from fafycat.cli_query.output import emit_error, emit_success
    from fafycat.core.config import AppConfig
    from fafycat.core.database import DatabaseManager

    start_date: date | None = None
    end_date: date | None = None
    year: int | None = getattr(args, "year", None)

    _has_date_arg = (
        args.start is not None
        or args.end is not None
        or args.month is not None
        or args.year is not None
        or args.this_month
        or args.last_month
        or args.ytd
        or args.last_n_months is not None
    )
    if _has_date_arg and year is None:
        try:
            start_date, end_date = resolve_date_range(args)
        except ValueError as exc:
            emit_error(str(exc))

    config = AppConfig()
    db_manager = DatabaseManager(config)
    db_manager.create_tables()

    with db_manager.get_session() as session:
        result = AnalyticsService.get_savings_tracking(
            session,
            year=year,
            start_date=start_date,
            end_date=end_date,
        )

    emit_success(result)


def cmd_analytics_yoy(args: argparse.Namespace) -> None:
    """Return year-over-year comparison data as JSON."""
    _apply_data_dir_override(args.data_dir)
    logging.disable(logging.WARNING)

    from fafycat.api.services import AnalyticsService
    from fafycat.cli_query.output import emit_success
    from fafycat.core.config import AppConfig
    from fafycat.core.database import DatabaseManager

    years: list[int] | None = None
    if args.years:
        years = [int(y.strip()) for y in args.years.split(",")]

    config = AppConfig()
    db_manager = DatabaseManager(config)
    db_manager.create_tables()

    with db_manager.get_session() as session:
        result = AnalyticsService.get_year_over_year_comparison(
            session,
            category_type=args.type or None,
            years=years,
        )

    emit_success(result)


def cmd_analytics_top(args: argparse.Namespace) -> None:
    """Return top spending transactions for a given month as JSON."""
    _apply_data_dir_override(args.data_dir)
    logging.disable(logging.WARNING)

    from fafycat.api.services import AnalyticsService
    from fafycat.cli_query.output import emit_success
    from fafycat.core.config import AppConfig
    from fafycat.core.database import DatabaseManager

    config = AppConfig()
    db_manager = DatabaseManager(config)
    db_manager.create_tables()

    with db_manager.get_session() as session:
        result = AnalyticsService.get_top_transactions_by_month(
            session,
            year=args.year,
            month=args.month,
            limit=args.limit,
        )

    emit_success(result)


def cmd_init(args: argparse.Namespace) -> None:
    """Initialize fafycat data directory and default categories."""
    _apply_data_dir_override(args.data_dir)

    from fafycat.core.config import AppConfig
    from fafycat.core.database import DatabaseManager

    config = AppConfig()
    config.ensure_dirs()

    print(f"📁 Data directory: {config.data_dir}")
    print(f"📁 Models: {config.ml.model_dir}")
    print(f"📁 Exports: {config.export_dir}")

    db_manager = DatabaseManager(config)
    db_manager.create_tables()
    db_manager.init_default_categories()
    print(f"📊 Database: {config.database.url}")
    print("✅ FafyCat initialized successfully")


def _add_data_dir_argument(parser: argparse.ArgumentParser) -> None:
    """Add the shared --data-dir argument."""
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Override data directory (default: platform user data dir)",
    )


def _dispatch_group(
    group_parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    handlers: dict[str, Callable[[argparse.Namespace], None]],
) -> None:
    """Dispatch to a named subcommand handler, or print group help if none given."""
    subcommand = getattr(args, "subcommand", None)
    if subcommand is None:
        group_parser.print_help()
        sys.exit(0)
    handler = handlers.get(subcommand)
    if handler is not None:
        handler(args)


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="fafycat",
        description="FafyCat - Local-first transaction categorization with ML",
    )
    subparsers = parser.add_subparsers(dest="command")

    serve_parser = subparsers.add_parser("serve", help="Start the web server")
    serve_parser.add_argument(
        "--dev",
        action="store_true",
        help="Development mode (hot reload, synthetic data, port 8001)",
    )
    serve_parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Port number (default: 8001 for dev, 8000 for prod)",
    )
    serve_parser.add_argument("--host", default=None, help="Host to bind to (default: 127.0.0.1)")
    _add_data_dir_argument(serve_parser)

    import_parser = subparsers.add_parser("import", help="Import transactions from a CSV file")
    import_parser.add_argument("file", type=Path, help="Path to the CSV file")
    _add_data_dir_argument(import_parser)

    init_parser = subparsers.add_parser("init", help="Initialize data directory and default categories")
    _add_data_dir_argument(init_parser)

    # tx subcommand group
    tx_parser = subparsers.add_parser("tx", help="Transaction queries")
    _add_data_dir_argument(tx_parser)
    tx_subparsers = tx_parser.add_subparsers(dest="subcommand")
    tx_list_parser = tx_subparsers.add_parser(
        "list",
        help="List transactions with optional filters",
        description=(
            "List transactions as a paginated JSON envelope. "
            "Examples: fafycat tx list --month 2025-01  |  fafycat tx list --ytd --category Groceries"
        ),
    )
    tx_list_parser.add_argument("--skip", type=int, default=0, help="Number of rows to skip (default: 0)")
    tx_list_parser.add_argument(
        "--limit", type=int, default=20, help="Maximum rows to return, capped at 500 (default: 20)"
    )
    tx_list_parser.add_argument("--category", default=None, help="Filter by category name")
    tx_list_parser.add_argument("--search", default="", help="Full-text search in description")
    tx_reviewed_group = tx_list_parser.add_mutually_exclusive_group()
    tx_reviewed_group.add_argument("--reviewed", action="store_true", default=False, help="Only reviewed transactions")
    tx_reviewed_group.add_argument(
        "--unreviewed", action="store_true", default=False, help="Only unreviewed transactions"
    )
    tx_list_parser.add_argument("--start", type=date.fromisoformat, default=None, help="Start date (YYYY-MM-DD)")
    tx_list_parser.add_argument("--end", type=date.fromisoformat, default=None, help="End date (YYYY-MM-DD)")
    tx_date_group = tx_list_parser.add_mutually_exclusive_group()
    tx_date_group.add_argument("--month", default=None, metavar="YYYY-MM", help="Filter to a calendar month")
    tx_date_group.add_argument("--year", type=int, default=None, metavar="YYYY", help="Filter to a calendar year")
    tx_date_group.add_argument("--this-month", action="store_true", default=False, help="Filter to the current month")
    tx_date_group.add_argument("--last-month", action="store_true", default=False, help="Filter to the previous month")
    tx_date_group.add_argument("--ytd", action="store_true", default=False, help="Filter to year-to-date")
    tx_date_group.add_argument(
        "--last-n-months", type=int, default=None, metavar="N", help="Filter to the last N months"
    )

    # cat subcommand group
    cat_parser = subparsers.add_parser("cat", help="Category queries")
    _add_data_dir_argument(cat_parser)
    cat_subparsers = cat_parser.add_subparsers(dest="subcommand")
    cat_list_parser = cat_subparsers.add_parser(
        "list",
        help="List categories with budgets and types",
        description="List all categories. Examples: fafycat cat list  |  fafycat cat list --include-inactive",
    )
    cat_list_parser.add_argument(
        "--include-inactive",
        action="store_true",
        default=False,
        help="Include inactive categories (default: active only)",
    )

    # budget subcommand group
    budget_parser = subparsers.add_parser("budget", help="Budget queries")
    _add_data_dir_argument(budget_parser)
    budget_subparsers = budget_parser.add_subparsers(dest="subcommand")
    budget_show_parser = budget_subparsers.add_parser(
        "show",
        help="Show per-category budgets for a year",
        description=(
            "Return per-category budgets for a year as JSON. "
            "Examples: fafycat budget show 2025  |  fafycat budget show 2024"
        ),
    )
    budget_show_parser.add_argument("year", type=int, help="Year (YYYY)")

    # analytics subcommand group
    analytics_parser = subparsers.add_parser("analytics", help="Analytics queries")
    _add_data_dir_argument(analytics_parser)
    analytics_subparsers = analytics_parser.add_subparsers(dest="subcommand")
    analytics_monthly_parser = analytics_subparsers.add_parser(
        "monthly",
        help="Monthly income/spending/saving totals for a year",
        description=(
            "Return monthly income/spending/saving totals as JSON. "
            "Examples: fafycat analytics monthly --year 2025  |  fafycat analytics monthly --ytd"
        ),
    )
    analytics_monthly_parser.add_argument(
        "--start", type=date.fromisoformat, default=None, help="Start date (YYYY-MM-DD)"
    )
    analytics_monthly_parser.add_argument("--end", type=date.fromisoformat, default=None, help="End date (YYYY-MM-DD)")
    analytics_monthly_date_group = analytics_monthly_parser.add_mutually_exclusive_group()
    analytics_monthly_date_group.add_argument(
        "--month", default=None, metavar="YYYY-MM", help="Filter to a calendar month"
    )
    analytics_monthly_date_group.add_argument(
        "--year", type=int, default=None, metavar="YYYY", help="Summarise a calendar year"
    )
    analytics_monthly_date_group.add_argument(
        "--this-month", action="store_true", default=False, help="Filter to the current month"
    )
    analytics_monthly_date_group.add_argument(
        "--last-month", action="store_true", default=False, help="Filter to the previous month"
    )
    analytics_monthly_date_group.add_argument(
        "--ytd", action="store_true", default=False, help="Filter to year-to-date"
    )
    analytics_monthly_date_group.add_argument(
        "--last-n-months", type=int, default=None, metavar="N", help="Filter to the last N months"
    )

    analytics_breakdown_parser = analytics_subparsers.add_parser(
        "breakdown",
        help="Per-category spending totals for a date range",
        description=(
            "Return per-category totals as JSON, optionally filtered by category type. "
            "Examples: fafycat analytics breakdown --year 2025  |  fafycat analytics breakdown --ytd --type spending"
        ),
    )
    analytics_breakdown_parser.add_argument(
        "--type", default=None, help="Filter by category type (e.g. spending, income)"
    )
    analytics_breakdown_parser.add_argument(
        "--start", type=date.fromisoformat, default=None, help="Start date (YYYY-MM-DD)"
    )
    analytics_breakdown_parser.add_argument(
        "--end", type=date.fromisoformat, default=None, help="End date (YYYY-MM-DD)"
    )
    analytics_breakdown_date_group = analytics_breakdown_parser.add_mutually_exclusive_group()
    analytics_breakdown_date_group.add_argument(
        "--month", default=None, metavar="YYYY-MM", help="Filter to a calendar month"
    )
    analytics_breakdown_date_group.add_argument(
        "--year", type=int, default=None, metavar="YYYY", help="Filter to a calendar year"
    )
    analytics_breakdown_date_group.add_argument(
        "--this-month", action="store_true", default=False, help="Filter to the current month"
    )
    analytics_breakdown_date_group.add_argument(
        "--last-month", action="store_true", default=False, help="Filter to the previous month"
    )
    analytics_breakdown_date_group.add_argument(
        "--ytd", action="store_true", default=False, help="Filter to year-to-date"
    )
    analytics_breakdown_date_group.add_argument(
        "--last-n-months", type=int, default=None, metavar="N", help="Filter to the last N months"
    )

    analytics_variance_parser = analytics_subparsers.add_parser(
        "variance",
        help="Budget-vs-actual variance per category for a date range",
        description=(
            "Return budget-vs-actual variance per category as JSON. "
            "Examples: fafycat analytics variance --year 2025  |  fafycat analytics variance --ytd"
        ),
    )
    analytics_variance_parser.add_argument(
        "--start", type=date.fromisoformat, default=None, help="Start date (YYYY-MM-DD)"
    )
    analytics_variance_parser.add_argument("--end", type=date.fromisoformat, default=None, help="End date (YYYY-MM-DD)")
    analytics_variance_date_group = analytics_variance_parser.add_mutually_exclusive_group()
    analytics_variance_date_group.add_argument(
        "--month", default=None, metavar="YYYY-MM", help="Filter to a calendar month"
    )
    analytics_variance_date_group.add_argument(
        "--year", type=int, default=None, metavar="YYYY", help="Filter to a calendar year"
    )
    analytics_variance_date_group.add_argument(
        "--this-month", action="store_true", default=False, help="Filter to the current month"
    )
    analytics_variance_date_group.add_argument(
        "--last-month", action="store_true", default=False, help="Filter to the previous month"
    )
    analytics_variance_date_group.add_argument(
        "--ytd", action="store_true", default=False, help="Filter to year-to-date"
    )
    analytics_variance_date_group.add_argument(
        "--last-n-months", type=int, default=None, metavar="N", help="Filter to the last N months"
    )

    analytics_savings_parser = analytics_subparsers.add_parser(
        "savings",
        help="Monthly and cumulative savings for a date range",
        description=(
            "Return monthly and cumulative savings as JSON. "
            "Examples: fafycat analytics savings --year 2025  |  fafycat analytics savings --ytd"
        ),
    )
    analytics_savings_parser.add_argument(
        "--start", type=date.fromisoformat, default=None, help="Start date (YYYY-MM-DD)"
    )
    analytics_savings_parser.add_argument("--end", type=date.fromisoformat, default=None, help="End date (YYYY-MM-DD)")
    analytics_savings_date_group = analytics_savings_parser.add_mutually_exclusive_group()
    analytics_savings_date_group.add_argument(
        "--month", default=None, metavar="YYYY-MM", help="Filter to a calendar month"
    )
    analytics_savings_date_group.add_argument(
        "--year", type=int, default=None, metavar="YYYY", help="Filter to a calendar year"
    )
    analytics_savings_date_group.add_argument(
        "--this-month", action="store_true", default=False, help="Filter to the current month"
    )
    analytics_savings_date_group.add_argument(
        "--last-month", action="store_true", default=False, help="Filter to the previous month"
    )
    analytics_savings_date_group.add_argument(
        "--ytd", action="store_true", default=False, help="Filter to year-to-date"
    )
    analytics_savings_date_group.add_argument(
        "--last-n-months", type=int, default=None, metavar="N", help="Filter to the last N months"
    )

    analytics_yoy_parser = analytics_subparsers.add_parser(
        "yoy",
        help="Year-over-year comparison by category",
        description=(
            "Return year-over-year comparison data as JSON, optionally filtered by category type or year list. "
            "Examples: fafycat analytics yoy  |  fafycat analytics yoy --type spending --years 2023,2024,2025"
        ),
    )
    analytics_yoy_parser.add_argument("--type", default=None, help="Filter by category type (e.g. spending, income)")
    analytics_yoy_parser.add_argument(
        "--years",
        default=None,
        metavar="YYYY,YYYY,...",
        help="Comma-separated list of years to compare (default: all available years)",
    )

    analytics_top_parser = analytics_subparsers.add_parser(
        "top",
        help="Top spending transactions for a given month",
        description=(
            "Return the largest spending transactions for a given month as JSON. "
            "Examples: fafycat analytics top --year 2025 --month 3  |  fafycat analytics top --limit 10"
        ),
    )
    analytics_top_parser.add_argument("--year", type=int, default=None, help="Year (default: current year)")
    analytics_top_parser.add_argument("--month", type=int, default=None, help="Month 1-12 (default: current month)")
    analytics_top_parser.add_argument(
        "--limit", type=int, default=5, help="Number of transactions to return (default: 5)"
    )

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        sys.exit(0)

    group_commands: dict[str, tuple[argparse.ArgumentParser, dict[str, Callable[[argparse.Namespace], None]]]] = {
        "tx": (tx_parser, {"list": cmd_tx_list}),
        "cat": (cat_parser, {"list": cmd_cat_list}),
        "budget": (budget_parser, {"show": cmd_budget_show}),
        "analytics": (
            analytics_parser,
            {
                "monthly": cmd_analytics_monthly,
                "breakdown": cmd_analytics_breakdown,
                "variance": cmd_analytics_variance,
                "savings": cmd_analytics_savings,
                "yoy": cmd_analytics_yoy,
                "top": cmd_analytics_top,
            },
        ),
    }
    if args.command in group_commands:
        group_parser, handlers = group_commands[args.command]
        _dispatch_group(group_parser, args, handlers)
        return

    leaf_commands: dict[str, Callable[[argparse.Namespace], None]] = {
        "serve": cmd_serve,
        "import": cmd_import,
        "init": cmd_init,
    }
    leaf_commands[args.command](args)


if __name__ == "__main__":
    main()
