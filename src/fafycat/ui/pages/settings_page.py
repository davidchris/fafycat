"""Settings and category management page."""

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from ...core.database import CategoryORM, TransactionORM, get_categories
from ...core.models import CategoryType
from ...data.csv_processor import CSVProcessor


def show() -> None:
    """Show the settings and category management page."""
    st.title("⚙️ Settings & Categories")
    st.markdown("Manage categories, budgets, and export data.")

    db_manager = st.session_state.db_manager

    # Mark that we're on the settings page and clear stale widget states
    # This prevents checkbox states from other pages from interfering
    if st.session_state.get("current_page") != "settings":
        st.session_state.current_page = "settings"
        # Clear any widget states that might be stale when coming from other pages
        keys_to_clear = [key for key in st.session_state if key.startswith(("active_", "name_", "budget_"))]
        for key in keys_to_clear:
            del st.session_state[key]

    # Tabs for different sections
    tab1, tab2, tab3, tab4 = st.tabs(["📋 Categories", "📊 Statistics", "📤 Export", "🔧 Advanced"])

    with tab1:
        _show_category_management(db_manager)

    with tab2:
        _show_statistics(db_manager)

    with tab3:
        _show_export_options(db_manager)

    with tab4:
        _show_advanced_settings(db_manager)


def _show_category_management(db_manager) -> None:
    """Show category management interface."""
    st.subheader("📋 Category Management")

    with db_manager.get_session() as session:
        # Force refresh categories from database each time to avoid state inconsistencies
        session.expire_all()  # Expire all cached objects
        categories = get_categories(session, active_only=False)

        # Add new category
        st.markdown("**Add New Category**")

        col1, col2, col3, col4 = st.columns(4)

        with col1:
            new_type = st.selectbox("Type", options=[t.value for t in CategoryType], key="new_category_type")

        with col2:
            new_name = st.text_input("Name", key="new_category_name")

        with col3:
            new_budget = st.number_input("Monthly Budget", min_value=0.0, step=10.0, key="new_category_budget")

        with col4:
            if st.button("➕ Add Category"):
                if new_name:
                    try:
                        category = CategoryORM(type=new_type, name=new_name.lower().strip(), budget=new_budget)
                        session.add(category)
                        session.commit()
                        st.success(f"Added category: {new_name}")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Failed to add category: {e}")
                else:
                    st.error("Please enter a category name")

        st.markdown("---")

        # Existing categories
        st.markdown("**Existing Categories**")

        if categories:
            # Group by type
            spending_cats = [c for c in categories if c.type == "spending"]
            income_cats = [c for c in categories if c.type == "income"]
            saving_cats = [c for c in categories if c.type == "saving"]

            for cat_type, cats in [
                ("💸 Spending", spending_cats),
                ("💰 Income", income_cats),
                ("🏦 Saving", saving_cats),
            ]:
                if cats:
                    st.markdown(f"**{cat_type}**")

                    for cat in cats:
                        col1, col2, col3, col4, col5 = st.columns([2, 1, 1, 1, 1])

                        with col1:
                            new_name = st.text_input(
                                "Name", value=cat.name, key=f"name_{cat.id}", label_visibility="collapsed"
                            )

                        with col2:
                            new_budget = st.number_input(
                                "Budget",
                                value=float(cat.budget),
                                min_value=0.0,
                                step=10.0,
                                key=f"budget_{cat.id}",
                                label_visibility="collapsed",
                            )

                        with col3:
                            new_active = st.checkbox("Active", value=cat.is_active, key=f"active_{cat.id}")

                        with col4:
                            if st.button("💾", key=f"save_{cat.id}", help="Save changes"):
                                cat.name = new_name.lower().strip()
                                cat.budget = new_budget
                                cat.is_active = new_active
                                session.commit()
                                # Clear cached category data to ensure fresh load
                                if "categories_cache" in st.session_state:
                                    del st.session_state.categories_cache
                                st.success("Updated!")
                                st.rerun()

                        with col5:
                            if st.button("🗑️", key=f"delete_{cat.id}", help="Delete category"):
                                # Check if category is used
                                usage_count = (
                                    session.query(TransactionORM)
                                    .filter(
                                        (TransactionORM.category_id == cat.id)
                                        | (TransactionORM.predicted_category_id == cat.id)
                                    )
                                    .count()
                                )

                                if usage_count > 0:
                                    st.error(f"Cannot delete category - used by {usage_count} transactions")
                                else:
                                    session.delete(cat)
                                    session.commit()
                                    st.success("Category deleted!")
                                    st.rerun()
        else:
            st.info("No categories found. Add some categories to get started!")


def _show_statistics(db_manager) -> None:
    """Show transaction and category statistics."""
    st.subheader("📊 Statistics")

    with db_manager.get_session() as session:
        # Basic stats
        total_transactions = session.query(TransactionORM).count()
        reviewed_transactions = session.query(TransactionORM).filter(TransactionORM.is_reviewed).count()
        categorized_transactions = session.query(TransactionORM).filter(TransactionORM.category_id.isnot(None)).count()

        col1, col2, col3 = st.columns(3)

        with col1:
            st.metric("Total Transactions", total_transactions)

        with col2:
            st.metric("Reviewed", reviewed_transactions)

        with col3:
            st.metric("Categorized", categorized_transactions)

        # Category breakdown
        if categorized_transactions > 0:
            st.markdown("**Spending by Category (Last 30 Days)**")

            # Get spending data for last 30 days
            thirty_days_ago = date.today() - timedelta(days=30)

            spending_query = (
                session.query(CategoryORM.name, TransactionORM.amount)
                .join(TransactionORM, CategoryORM.id == TransactionORM.category_id)
                .filter(
                    CategoryORM.type == "spending", TransactionORM.date >= thirty_days_ago, TransactionORM.amount < 0
                )
                .all()
            )

            if spending_query:
                spending_data = {}
                for category_name, amount in spending_query:
                    if category_name not in spending_data:
                        spending_data[category_name] = 0
                    spending_data[category_name] += abs(amount)

                # Create chart
                spending_df = pd.DataFrame(list(spending_data.items()), columns=["Category", "Amount"]).sort_values(
                    "Amount", ascending=False
                )

                st.bar_chart(spending_df.set_index("Category"))

                # Top spending categories
                st.markdown("**Top Spending Categories**")
                for i, (category, amount) in enumerate(spending_df.head(5).values):
                    st.write(f"{i + 1}. **{category}**: €{amount:.2f}")

        # Model performance (if available)
        st.markdown("**Model Performance**")

        from ...core.database import ModelMetadataORM

        latest_model = session.query(ModelMetadataORM).filter(ModelMetadataORM.is_active).first()

        if latest_model:
            col1, col2 = st.columns(2)

            with col1:
                st.metric("Model Accuracy", f"{latest_model.accuracy:.1%}" if latest_model.accuracy else "N/A")

            with col2:
                st.write(f"**Last Trained:** {latest_model.training_date.strftime('%Y-%m-%d %H:%M')}")
        else:
            st.info("No model trained yet. Train a model to see performance metrics.")


def _show_export_options(db_manager) -> None:
    """Show data export options."""
    st.subheader("📤 Export Data")

    with db_manager.get_session() as session:
        # Export options
        col1, col2 = st.columns(2)

        with col1:
            start_date = st.date_input("Start Date", value=date.today() - timedelta(days=90))

        with col2:
            end_date = st.date_input("End Date", value=date.today())

        # Category filter
        categories = get_categories(session)
        selected_categories = st.multiselect(
            "Categories (leave empty for all)",
            options=[cat.id for cat in categories],
            format_func=lambda x: next(cat.name for cat in categories if cat.id == x),
        )

        # Export button
        if st.button("📥 Export to CSV"):
            try:
                processor = CSVProcessor(session)
                export_path = st.session_state.config.export_dir / f"export_{date.today().isoformat()}.csv"

                processor.export_transactions(
                    export_path,
                    start_date=start_date,
                    end_date=end_date,
                    category_ids=selected_categories if selected_categories else None,
                )

                st.success(f"Data exported to: {export_path}")

                # Show download link
                with open(export_path, "rb") as f:
                    st.download_button("📥 Download CSV", data=f.read(), file_name=export_path.name, mime="text/csv")

            except Exception as e:
                st.error(f"Export failed: {e}")


def _show_advanced_settings(db_manager) -> None:
    """Show advanced settings and database operations."""
    st.subheader("🔧 Advanced Settings")

    # Database info
    with db_manager.get_session() as session:
        transaction_count = session.query(TransactionORM).count()
        category_count = session.query(CategoryORM).count()

        st.markdown("**Database Information**")
        col1, col2 = st.columns(2)

        with col1:
            st.write(f"Transactions: {transaction_count}")
            st.write(f"Categories: {category_count}")

        with col2:
            db_path = st.session_state.config.database.url.replace("sqlite:///", "")
            st.write(f"Database: {db_path}")

    st.markdown("---")

    # Dangerous operations
    st.markdown("**⚠️ Dangerous Operations**")
    st.warning("These operations cannot be undone!")

    col1, col2 = st.columns(2)

    with col1:
        if st.button("🗑️ Delete All Unreviewed"):
            with db_manager.get_session() as session:
                deleted = session.query(TransactionORM).filter(~TransactionORM.is_reviewed).delete()
                session.commit()
                st.success(f"Deleted {deleted} unreviewed transactions")

    with col2:
        if st.button("🔄 Reset All Reviews"):
            with db_manager.get_session() as session:
                updated = session.query(TransactionORM).update({"is_reviewed": False, "category_id": None})
                session.commit()
                st.success(f"Reset {updated} transaction reviews")

    # Model management
    st.markdown("---")
    st.markdown("**🤖 Model Management**")

    model_path = st.session_state.config.ml.model_dir / "categorizer.pkl"

    if model_path.exists():
        st.success("✅ Trained model available")

        if st.button("🗑️ Delete Model"):
            model_path.unlink()
            st.success("Model deleted")
            st.rerun()
    else:
        st.info("ℹ️ No trained model found")

        if st.button("🎯 Train New Model"):
            try:
                from ...ml.categorizer import TransactionCategorizer

                with st.spinner("Training model..."), db_manager.get_session() as session:
                    categorizer = TransactionCategorizer(session, st.session_state.config.ml)
                    metrics = categorizer.train()
                    categorizer.save_model(model_path)

                    st.success(f"Model trained! Accuracy: {metrics.accuracy:.1%}")

            except Exception as e:
                st.error(f"Training failed: {e}")
