"""Transaction import page."""

from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from ...data.csv_processor import CSVProcessor


def show() -> None:
    """Show the import transactions page."""
    st.title("📥 Import Transactions")
    st.markdown("Upload CSV files containing your banking transactions for automatic categorization.")

    db_manager = st.session_state.db_manager

    # Mark current page for state management
    if st.session_state.get("current_page") != "import":
        st.session_state.current_page = "import"

    # File upload section
    st.subheader("Upload CSV File")

    uploaded_file = st.file_uploader(
        "Choose a CSV file",
        type=["csv"],
        help="Upload a CSV file containing your banking transactions. "
        "The system will automatically detect column formats.",
    )

    if uploaded_file is not None:
        # Preview the data
        try:
            df = pd.read_csv(uploaded_file)
            st.subheader("Data Preview")
            st.dataframe(df.head(10))

            st.subheader("Column Detection")
            col1, col2 = st.columns(2)

            with col1:
                st.write("**Detected columns:**")
                for col in df.columns:
                    st.write(f"- {col}")

            with col2:
                st.write("**File info:**")
                st.write(f"- Rows: {len(df)}")
                st.write(f"- Columns: {len(df.columns)}")
                st.write(f"- File size: {uploaded_file.size} bytes")

            # Import options
            st.subheader("Import Options")

            col1, col2 = st.columns(2)

            with col1:
                csv_format = st.selectbox(
                    "CSV Format",
                    ["generic"],
                    help="Select the format of your CSV file. Generic format auto-detects columns.",
                )

            with col2:
                import_batch_name = st.text_input(
                    "Import Batch Name",
                    value=f"import_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    help="Name for this import batch to track transactions.",
                )

            # Import button
            if st.button("Import Transactions", type="primary"):
                with st.spinner("Processing transactions..."):
                    # Save uploaded file temporarily
                    temp_path = Path(f"/tmp/{uploaded_file.name}")
                    with open(temp_path, "wb") as f:
                        f.write(uploaded_file.getbuffer())

                    # Process the CSV
                    with db_manager.get_session() as session:
                        processor = CSVProcessor(session)

                        try:
                            # Import transactions
                            transactions, errors = processor.import_csv(temp_path, csv_format)

                            if errors:
                                st.error("Errors encountered during import:")
                                for error in errors:
                                    st.write(f"- {error}")

                            if transactions:
                                # Save to database
                                new_count, duplicate_count = processor.save_transactions(
                                    transactions, import_batch_name
                                )

                                st.success("Import completed successfully!")

                                col1, col2, col3 = st.columns(3)
                                with col1:
                                    st.metric("New Transactions", new_count)
                                with col2:
                                    st.metric("Duplicates Skipped", duplicate_count)
                                with col3:
                                    st.metric("Total Processed", len(transactions))

                                if new_count > 0:
                                    st.info(
                                        f"✨ {new_count} new transactions imported! "
                                        f"Go to the **Review & Categorize** page to review predictions."
                                    )

                            else:
                                st.warning("No valid transactions found in the file.")

                        except Exception as e:
                            st.error(f"Import failed: {str(e)}")

                        finally:
                            # Clean up temp file
                            if temp_path.exists():
                                temp_path.unlink()

        except Exception as e:
            st.error(f"Error reading CSV file: {str(e)}")

    # Example CSV format section
    st.subheader("📄 Example CSV Format")
    st.markdown(
        "Your CSV file should contain transaction data with columns like these. "
        "Column names are flexible - the system will auto-detect them:"
    )

    example_data = {
        "date": ["2024-01-15", "2024-01-16", "2024-01-20"],
        "name": ["EDEKA Markt 1234", "McDonald's Berlin", "Amazon Marketplace"],
        "purpose": ["Lastschrift", "Kartenzahlung", "Online-Kauf"],
        "amount": [-45.67, -12.50, -89.99],
        "currency": ["EUR", "EUR", "EUR"],
    }

    example_df = pd.DataFrame(example_data)
    st.dataframe(example_df)

    # Column mapping info
    with st.expander("📋 Supported Column Names"):
        col1, col2 = st.columns(2)

        with col1:
            st.markdown("""
            **Required columns:**
            - Date: `date`, `datum`, `transaction_date`, `buchungstag`
            - Amount: `amount`, `betrag`, `value`, `sum`, `summe`
            - Description: `description`, `name`, `merchant`, `empfaenger`, `verwendungszweck`
            """)

        with col2:
            st.markdown("""
            **Optional columns:**
            - Purpose: `purpose`, `verwendungszweck`, `reference`, `memo`
            - Value Date: `value_date`, `valuta`, `wertstellung`
            - Category: `category`, `kategorie`, `type`
            - Account: `account`, `konto`, `account_number`
            - Currency: `currency`, `waehrung`, `ccy`
            """)

    # Recent imports section
    st.subheader("📊 Recent Imports")

    with db_manager.get_session() as session:
        from ...core.database import TransactionORM

        # Get recent import batches
        recent_imports = (
            session.query(TransactionORM.import_batch, TransactionORM.imported_at)
            .distinct()
            .order_by(TransactionORM.imported_at.desc())
            .limit(5)
            .all()
        )

        if recent_imports:
            for batch_name, imported_at in recent_imports:
                # Count transactions in this batch
                count = session.query(TransactionORM).filter(TransactionORM.import_batch == batch_name).count()

                st.write(f"**{batch_name}** - {count} transactions ({imported_at.strftime('%Y-%m-%d %H:%M')})")
        else:
            st.info("No imports yet. Upload a CSV file to get started!")
