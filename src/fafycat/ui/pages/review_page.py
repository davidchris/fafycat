"""Transaction review and categorization page."""

import streamlit as st

from ...core.database import TransactionORM, get_categories, get_transactions
from ...core.models import TransactionInput
from ...ml.categorizer import TransactionCategorizer


def show() -> None:
    """Show the review and categorization page."""
    st.title("🔍 Review & Categorize")
    st.markdown("Review ML predictions and manually categorize transactions to improve accuracy.")

    config = st.session_state.config
    db_manager = st.session_state.db_manager

    # Mark current page for state management
    if st.session_state.get("current_page") != "review":
        st.session_state.current_page = "review"

    with db_manager.get_session() as session:
        # Load or train model if needed
        model_path = config.ml.model_dir / "categorizer.pkl"
        categorizer = None

        if model_path.exists():
            try:
                categorizer = TransactionCategorizer(session, config.ml)
                categorizer.load_model(model_path)
                st.success("✅ ML model loaded successfully")
            except Exception as e:
                st.error(f"Failed to load model: {e}")
        else:
            st.warning("⚠️ No trained model found. Train a model first or predictions will be unavailable.")

        # Get categories for selection
        categories = get_categories(session)
        category_options = {cat.id: f"{cat.name} ({cat.type})" for cat in categories}

        # Filter options
        st.subheader("🔧 Filter Options")

        col1, col2, col3, col4 = st.columns(4)

        with col1:
            show_unreviewed_only = st.checkbox("Unreviewed Only", value=True)

        with col2:
            max_transactions = st.number_input("Max Transactions", min_value=10, max_value=500, value=50)

        with col3:
            min_confidence = st.slider("Min Confidence", 0.0, 1.0, 0.0, 0.1)

        with col4:
            max_confidence = st.slider("Max Confidence", 0.0, 1.0, 1.0, 0.1)

        # Get transactions
        transactions = get_transactions(session, limit=max_transactions, unreviewed_only=show_unreviewed_only)

        # Filter by confidence if model is available
        if categorizer:
            transactions = [
                txn
                for txn in transactions
                if txn.confidence_score is None or (min_confidence <= (txn.confidence_score or 0) <= max_confidence)
            ]

        if not transactions:
            st.info("No transactions found with the current filters. Try adjusting the filter options.")
            return

        st.subheader(f"📋 Transactions to Review ({len(transactions)})")

        # Generate predictions if model is available and needed
        if categorizer:
            _generate_predictions(session, categorizer, transactions)

        # Display transactions for review
        _display_transaction_review(session, transactions, category_options)

        # Bulk actions
        st.subheader("⚡ Bulk Actions")

        col1, col2, col3 = st.columns(3)

        with col1:
            if st.button("Mark All as Reviewed"):
                _mark_all_reviewed(session, transactions)
                st.rerun()

        with col2:
            if st.button("Accept All High-Confidence"):
                _accept_high_confidence(session, transactions, threshold=0.9)
                st.rerun()

        with col3:
            if st.button("Retrain Model"):
                _retrain_model(session, config)


def _generate_predictions(session, categorizer: TransactionCategorizer, transactions: list[TransactionORM]) -> None:
    """Generate predictions for transactions that don't have them."""
    unpredicted = [txn for txn in transactions if txn.predicted_category_id is None]

    if unpredicted:
        with st.spinner(f"Generating predictions for {len(unpredicted)} transactions..."):
            # Convert to TransactionInput format
            txn_inputs = []
            for txn in unpredicted:
                txn_input = TransactionInput(
                    date=txn.date,
                    value_date=txn.value_date,
                    name=txn.name,
                    purpose=txn.purpose or "",
                    amount=txn.amount,
                    currency=txn.currency,
                )
                txn_inputs.append(txn_input)

            # Get predictions
            predictions = categorizer.predict_with_confidence(txn_inputs)

            # Update database
            for txn, pred in zip(unpredicted, predictions, strict=False):
                txn.predicted_category_id = pred.predicted_category_id
                txn.confidence_score = pred.confidence_score

            session.commit()
            st.success(f"Generated predictions for {len(unpredicted)} transactions")


def _display_transaction_review(session, transactions: list[TransactionORM], category_options: dict) -> None:
    """Display transactions for review with category selection."""

    for i, txn in enumerate(transactions):
        with st.container():
            st.markdown(f"**Transaction {i + 1}**")

            col1, col2, col3, col4 = st.columns([3, 2, 2, 1])

            with col1:
                st.write(f"**{txn.name}**")
                st.write(f"*{txn.purpose or 'No purpose'}*")
                st.write(f"📅 {txn.date} | 💰 {txn.amount:.2f} {txn.currency}")

            with col2:
                # Show prediction if available
                if txn.predicted_category_id:
                    pred_category = category_options.get(txn.predicted_category_id, "Unknown")
                    confidence = txn.confidence_score or 0
                    confidence_color = "green" if confidence > 0.8 else "orange" if confidence > 0.5 else "red"

                    st.write("🤖 **ML Prediction:**")
                    st.write(f"{pred_category}")
                    st.markdown(
                        f"<span style='color: {confidence_color}'>Confidence: {confidence:.1%}</span>",
                        unsafe_allow_html=True,
                    )
                else:
                    st.write("🤖 **ML Prediction:**")
                    st.write("*No prediction available*")

            with col3:
                # Category selection
                current_category = txn.category_id

                selected_category = st.selectbox(
                    "Select Category",
                    options=[None] + list(category_options.keys()),
                    format_func=lambda x: "-- Select Category --" if x is None else category_options[x],
                    index=0 if current_category is None else list(category_options.keys()).index(current_category) + 1,
                    key=f"category_{txn.id}",
                )

                # Accept prediction button
                if (
                    txn.predicted_category_id
                    and selected_category != txn.predicted_category_id
                    and st.button("✅ Accept Prediction", key=f"accept_{txn.id}")
                ):
                    selected_category = txn.predicted_category_id

            with col4:
                # Review status
                if txn.is_reviewed:
                    st.write("✅ Reviewed")
                else:
                    st.write("⏳ Pending")

                # Update button
                if st.button("💾 Update", key=f"update_{txn.id}") and selected_category:
                    txn.category_id = selected_category
                    txn.is_reviewed = True
                    session.commit()
                    st.success("Updated!")
                    st.rerun()

            st.markdown("---")


def _mark_all_reviewed(session, transactions: list[TransactionORM]) -> None:
    """Mark all transactions as reviewed."""
    count = 0
    for txn in transactions:
        if not txn.is_reviewed:
            txn.is_reviewed = True
            count += 1

    session.commit()
    st.success(f"Marked {count} transactions as reviewed")


def _accept_high_confidence(session, transactions: list[TransactionORM], threshold: float = 0.9) -> None:
    """Accept all high-confidence predictions."""
    count = 0
    for txn in transactions:
        if (
            txn.predicted_category_id
            and txn.confidence_score
            and txn.confidence_score >= threshold
            and not txn.category_id
        ):
            txn.category_id = txn.predicted_category_id
            txn.is_reviewed = True
            count += 1

    session.commit()
    st.success(f"Accepted {count} high-confidence predictions")


def _retrain_model(session, config) -> None:
    """Retrain the ML model with latest data."""
    try:
        with st.spinner("Retraining model..."):
            categorizer = TransactionCategorizer(session, config.ml)
            metrics = categorizer.train()

            # Save model
            model_path = config.ml.model_dir / "categorizer.pkl"
            categorizer.save_model(model_path)

            st.success(f"Model retrained successfully! New accuracy: {metrics.accuracy:.1%}")

    except Exception as e:
        st.error(f"Failed to retrain model: {e}")
