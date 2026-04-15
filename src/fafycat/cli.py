"""Unified CLI for fafycat."""

import argparse
import json
import os
import sys
from pathlib import Path


def _apply_data_dir_override(data_dir: Path | None) -> None:
    """Set environment overrides so config derives paths from data_dir."""
    if data_dir is None:
        return

    resolved_data_dir = data_dir.resolve()
    os.environ["FAFYCAT_DATA_DIR"] = str(resolved_data_dir)
    os.environ.setdefault("FAFYCAT_DB_URL", f"sqlite:///{resolved_data_dir / 'fafycat.db'}")
    os.environ.setdefault("FAFYCAT_MODEL_DIR", str(resolved_data_dir / "models"))
    os.environ.setdefault("FAFYCAT_EXPORT_DIR", str(resolved_data_dir / "exports"))


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


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="fafycat",
        description="FafyCat - Local-first transaction categorization with ML",
    )
    _add_data_dir_argument(parser)

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

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        sys.exit(0)

    commands = {
        "serve": cmd_serve,
        "import": cmd_import,
        "init": cmd_init,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
