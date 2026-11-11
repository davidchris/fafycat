# Changelog

All notable changes to FafyCat are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- scikit-learn 1.9.1 (was 1.7.0). Training results are unchanged, and
  saved models do not need a retrain.

## [0.4.0] - 2026-11-11

### Changed
- **The model learns from people only.** Training, Merchant Rules, the
  calibration table, and the training-readiness counts use Human Labels:
  transactions whose latest Review Event is a user review, a propagation,
  or a labelled CSV import. Auto-accepts and bulk approves no longer feed
  the model its own guesses. Models trained before this change
  (`2.1-stack`) must be retrained. (#62)
- **Merchant names survive cleaning.** Only a trailing city or `DE` is
  stripped ("Cafe de Paris" stays whole). Partial Merchant Rules,
  keyword features, and category-type guesses match whole words, so
  "Amazing Thai Restaurant" no longer hits the AMAZON rule. Stored
  Merchant Patterns are recomputed once on upgrade. (#62)
- **Savings are net saved.** A transfer to savings counts as saving, a
  transfer back counts as de-saving. Savings tracking reports net saved
  per month (negative for a de-saving month), counts only saving months
  in averages, and adds `months_with_desaving`. The `amount`,
  `cumulative_amount`, `unreviewed_amount`, and `total_savings` fields
  change sign. Budget variance stays spending-only. (#67)
- **Category names are unique, ignoring case.** New defaults use
  `investment_income` and `other_income`. A duplicate name returns 409,
  names are limited to 50 characters, and a name an old database holds
  twice is resolved to the active one or written as `name (type)`. The
  review forms send the category id, and `PUT /api/transactions/{id}/category`
  accepts `category_id` as well as a name. (#65)

### Fixed
- `/api/ml/predict` and `/api/ml/predict/bulk` work with the default
  ensemble. (#65)
- `batch-repredict` pages with a cursor and reports an accurate
  `remaining`; the review and settings pages re-predict the whole queue.
  (#65)
- Excel export works (`openpyxl` is now a dependency). CSV and Excel
  exports neutralise spreadsheet formulas in text cells. (#65)
- Client errors stay client errors: an out-of-range budget year is 400, an
  empty export is 404, an unknown `sort_by` is 400, and an unknown
  category is 400 "Category not found". (#65)
- Settings: "Create Your First Category" works, failed changes show the
  server's error, every inactive category is reachable, and "model ready"
  means the model actually loaded. (#65)
- `analytics top` accepts `--this-month`/`--last-month`; `--category`
  ignores case and an unknown name exits 1 with a JSON error. Confidence
  0.0 shows as 0 %, a missing one as N/A. (#65)

## [0.3.1] - 2026-11-11

### Fixed
- **One database for every command.** `fafycat serve`, `import`, `init`,
  all query commands, and the scripts now open the same file:
  `<data dir>/fafycat_prod.db`, or `fafycat_dev.db` with `--dev` (now
  accepted by every command). `--data-dir`/`--dev` take precedence over
  `FAFYCAT_DB_URL`, which takes precedence over `db_url` in the config
  file. Another database file with transactions (for example the
  `fafycat.db` that the 0.3.0 CLI wrote to) is reported, never merged,
  moved, or deleted. (#66)
- **Query commands never write.** `tx`, `cat`, `budget`, `analytics`, and
  `status` open the database read-only and no longer run schema upgrades.
  Run `fafycat init` or `fafycat serve` once to upgrade an old database.
  (#66)
- **Budget numbers are right.** Variance is budget minus money spent
  (2,700 budget, 1,300 spent is 1,400 under budget, not 4,000). A spending
  category without a budget is overspent by everything it spent. Budgets
  are prorated by day. The category breakdown reports each category's
  share of its type and reads the yearly budget plan. Year-over-year no
  longer crashes on 29 February. JSON fields changed meaning:
  `summary.total_actual` is positive money spent, variance percentages are
  `null` without a budget, and the breakdown `budget` is prorated. (#60)
- **CSV import keeps every transaction.** Identical rows in one file are
  all kept (the first keeps its old id, so re-imports still deduplicate).
  Empty purposes are stored empty, not as `"nan"`, and digit-only text
  keeps its leading zeros. Rows an older import stored as `"nan"` or as a
  number (`123` for `00123`) still match on re-import. Day and month order is
  inferred per file and an ambiguous file is rejected (`--date-order`
  overrides). Semicolon-separated files, decimal commas, and cp1252
  encoding import, so Sparkasse- and DKB-style exports work. `.CSV` is
  accepted, every bad row is listed, and fuzzy dedup keeps the Merchant
  Pattern in step with the name. Re-importing an old file adds the
  same-day duplicates that earlier imports dropped. (#63)
- **Browser hardening.** Requests with a foreign `Host` header get 400 and
  cross-origin writes get 403, which closes CSRF and DNS rebinding. Allow
  more host names with `FAFYCAT_ALLOWED_HOSTS` (`serve --host` adds its
  address). JSON inside inline scripts is escaped. `python -m fafycat.app`
  binds to 127.0.0.1, and `serve --host` on a non-loopback address warns
  that there is no authentication. (#64)

### Added
- `fafycat status` (database path and source, row counts, model state,
  stray database files) and `fafycat --version`. (#66, #70)

### Removed
- The `.env` instructions and the `FAFYCAT_*_PORT`, `FAFYCAT_HOST`, and
  `FAFYCAT_ENV` variables from the docs: nothing read them. (#66)
- Unbacked performance claims from the README, and three manual tests
  that asserted nothing. (#61)

## [0.3.0] - 2026-10-29

### Changed
- **Honest confidence.** LightGBM and Naive Bayes are calibrated with a
  temperature fitted on out-of-fold predictions instead of an in-sample
  Platt fit that pushed everything past 0.95. LightGBM now uses 80 trees
  (down from 1000, which was 13x past its early-stopping point).
- **Stacked ensemble replaces voter weights.** A logistic regression over
  the three voters' probabilities plus meta features (agreement, rule
  match, how often the merchant was seen, amount) decides, fitted on
  out-of-fold outputs with merchant rules derived per fold. Training
  reports out-of-fold accuracy and the auto-approve rate and error at the
  threshold. Models trained before this change must be retrained.
- **Merchant rule after one review.** A rule forms after the first review
  and grows more confident with each agreeing one: capped at 90%, 95%,
  and 98% for one, two, and three or more reviews.
- **Review queue ordered by review impact.** Pending rows are sorted by
  pending siblings times uncertainty, so one review resolves the most.
  Each row shows how many other pending transactions share its merchant.
  Sorting by confidence is still available.
- **Audit trail shows what the stack read.** The trail page lists the
  meta features beside the three votes.

### Removed
- The simplex weight grid, `MIN_MODEL_WEIGHT`, and the unused k-fold
  validator module.

### Fixed
- **Incompatible model is reported, not hidden.** When the saved model was
  written in another format (for example a `1.0-ensemble` model after the
  stacked ensemble), loading fails with a clear "retrain the model" message
  instead of the import page saying no model exists. The import still
  succeeds; the upload result, the `/api/upload/csv` response
  (`prediction_error`), the CLI import, and the ML status all name the
  problem.
- **Retraining predicts pending transactions.** After a successful retrain
  the training job predicts every transaction that has no prediction yet
  and reports how many were auto-accepted or need review. Transactions that
  already have a prediction are not re-predicted. A prediction failure is
  reported in the result and does not fail the training.

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
  differently, such as transfers to the same account that serve different
  purposes.
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

[Unreleased]: https://github.com/davidchris/fafycat/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/davidchris/fafycat/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/davidchris/fafycat/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/davidchris/fafycat/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/davidchris/fafycat/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/davidchris/fafycat/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/davidchris/fafycat/releases/tag/v0.1.0
