# Changelog

All notable changes to FafyCat are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- **Analytics bars now render reliably.** The Spending, Income, and Saving
  category charts could appear empty after a recent chart-library upgrade.
  Bars draw correctly again.
- **Year-over-year chart fills are visible in the dark theme.** Filled
  areas no longer disappear when the active theme defines colors using
  the `rgb()` notation.
- **Training no longer crashes when a category has only a few transactions.**
  Model training now adapts its cross-validation to the smallest category
  rather than failing with a fold-count error.
- **The "Top Transactions" list always reflects the latest data you have.**
  It now uses the most recent month with transactions instead of always
  defaulting to the current calendar month, so the list is never empty
  on a fresh import.

### Changed
- **Year-over-year analytics defaults to the latest three years in your
  data.** Previously the default window could land on years with no
  transactions, leaving the page blank.
- **Year-to-date analytics defaults to the latest year that has data.**
  Opening Analytics on a freshly imported dataset no longer shows an
  empty comparison.
- **The aligned year-over-year comparison is explained in the UI.** A
  short note clarifies how the current partial year is matched against
  the same calendar window in earlier years for a fair side-by-side total.
- **Transaction tables wrap long descriptions instead of overflowing.**
  Long merchant names no longer push the category picker off-screen on
  narrower windows; the description column wraps and the action column
  keeps a stable minimum width.

### Less log noise
- Training no longer floods the console with LightGBM "no further splits"
  warnings.
- The training-progress endpoint that the UI polls during training no
  longer fills the access log with one line per poll.
