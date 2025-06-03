"""Main Streamlit application entry point."""


import streamlit as st

from fafycat.core.config import AppConfig
from fafycat.core.database import DatabaseManager
from fafycat.ui.pages import import_page, review_page, settings_page


def init_app() -> tuple[AppConfig, DatabaseManager]:
    """Initialize application configuration and database."""
    config = AppConfig()
    config.ensure_dirs()

    db_manager = DatabaseManager(config)

    # Ensure database is initialized
    db_manager.create_tables()

    return config, db_manager


def main() -> None:
    """Main application entry point."""
    st.set_page_config(
        page_title="FafyCat - Family Finance Categorizer",
        page_icon="🐱",
        layout="wide",
        initial_sidebar_state="expanded"
    )

    # Initialize app
    config, db_manager = init_app()

    # Store in session state for page access
    if 'config' not in st.session_state:
        st.session_state.config = config
    if 'db_manager' not in st.session_state:
        st.session_state.db_manager = db_manager

    # Sidebar navigation
    st.sidebar.title("🐱 FafyCat")
    st.sidebar.markdown("*Family Finance Categorizer*")
    st.sidebar.markdown("---")

    page = st.sidebar.radio(
        "Navigate to:",
        ["Import Transactions", "Review & Categorize", "Settings & Categories"],
        index=0
    )

    # Route to appropriate page
    if page == "Import Transactions":
        import_page.show()
    elif page == "Review & Categorize":
        review_page.show()
    elif page == "Settings & Categories":
        settings_page.show()

    # Footer
    st.sidebar.markdown("---")
    st.sidebar.markdown(
        "Built with ❤️ using Streamlit<br>"
        "Local-first • Privacy-focused • ML-powered",
        unsafe_allow_html=True
    )


if __name__ == "__main__":
    main()
