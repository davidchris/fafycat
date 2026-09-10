# Changelog

All notable changes to FafyCat are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-09-10

### Added
- **One review queue, least confident first.** Every prediction below the
  auto-approve threshold lands in a single queue sorted by confidence. The
  20-item cap, the hidden standard/high priority split, and the confidence
  slider on the review page are gone.
- **"Retrain and re-predict" on the review page.** The page tells you how
  many of your reviews the model has not seen yet and offers one button
  that retrains, re-predicts the queue with the fresh model, and reloads
  the table.
- **Corrections reach sibling transactions.** After you save a category,
  the row offers to apply it to the other unreviewed transactions from the
  same merchant that the model predicted the same way.
- **Audit trail per transaction.** A trail page, linked from the review
  table, shows what the merchant rule, LightGBM, and Naive Bayes each
  proposed, the ensemble weights, the decision taken, and every category
  change with who made it.
- **Merchant rules page.** `/rules` lists every rule with the reviews it
  is based on.
- **Calibration table in Settings.** Next to the auto-approve threshold you
  now see, per confidence band, how often you kept or overrode the
  prediction and how many auto-accepted transactions you later corrected.
- **Unreviewed share in analytics.** Analytics warns when unreviewed
  transactions are counted and offers an "Exclude unreviewed" toggle; the
  year-over-year table shows the unreviewed share per year. The home page
  shows how many transactions of the current month are still unreviewed.
- **`--exclude-unreviewed`** on every `fafycat analytics` subcommand. JSON
  output carries the unreviewed summary either way.

### Changed
- **Merchant rules vote instead of overriding.** A matching rule is a third
  voter blended with the two models, so the models can outvote a stale
  rule. Rules refresh after every review instead of waiting for a retrain
  and are rebuilt from scratch on each training run.
- **PayPal and SumUp merchants are told apart.** Everything after `*` used
  to be stripped, collapsing every PayPal and SumUp purchase into one rule.
- **Default auto-approve threshold is 0.90** (was 0.95) for new installs.
  A threshold you saved in Settings still wins.
- **Labelled imports and earlier reviews keep their category** when the
  model re-predicts. The prediction is recorded for the trail only.
- **Bulk approve without filters** approves pending predictions at or above
  the auto-approve threshold.

### Fixed
- **Transactions stuck as reviewed without a category come back.** Between
  June 2025 and July 2026 auto-accepted transactions were flagged reviewed
  without their category being saved, which hid them from the queue and
  from training. On startup they return to the queue; the next re-predict
  auto-accepts the confident ones.
- **Labelled CSV imports no longer sit in the review queue.** Categories
  imported from a labelled CSV before June 2025 were never flagged as
  reviewed. They are now.
- **Propagation no longer overwrites transfers the model told apart.**
  Applying a category to siblings skips rows the model predicted
  differently, such as pocket money and savings plan transfers to the same
  payee.
- **Calibration ignores rows without a category** instead of counting each
  one as an override.
- **Older databases gain new columns on startup.** No manual migration
  step after an upgrade.

## [0.1.1] - 2026-07-06

### Fixed
- **Pagination no longer drops your filters.** Clicking First/Prev/Next/Last
  in the transaction table used to silently reset sorting, the category
  filter, and the date range. All active filters now carry through
  pagination.
- **Duplicate transactions from card settlements are now caught.** Some
  banks export the same card purchase twice — once as the direct account
  booking, once as a delayed VISA settlement line days later. Import now
  recognizes and collapses these as one transaction.
- **Reviewed transactions keep their checkmark after a page reload.** The
  checkmark used to only show right after saving, then disappear again.
- **Transaction amounts consistently show in EUR** across all transaction
  views.
- **`tx list` and `analytics top` reject invalid `--limit` values** instead
  of silently clamping or accepting out-of-range numbers.

### Security
- Patched further Dependabot alerts: `starlette` (form-parsing DoS),
  `python-multipart` (parsing DoS/smuggling), `bleach` (XSS), and
  `jupyter-server`/`jupyterlab` (stored XSS).

## [0.1.0] - 2026-06-13

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

### Security
- Patched Dependabot vulnerability alerts and refreshed locked
  dependencies, including an `urllib3` security update.

### Changed (packaging & docs)
- The repository was prepared for wider public sharing with updated
  documentation.

[Unreleased]: https://github.com/davidchris/fafycat/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/davidchris/fafycat/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/davidchris/fafycat/releases/tag/v0.1.0
