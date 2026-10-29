# FafyCat

Personal finance categorization: bank transactions are imported from CSV, categorized by an ML model, and confirmed by a human reviewer. The model learns from confirmed reviews.

## Language

**Transaction**:
A single bank transaction imported from a CSV export.
_Avoid_: entry, record, row

**Category**:
A user-defined label a transaction belongs to, optionally carrying a budget.
_Avoid_: class, label, tag

**Prediction**:
A category suggested for a transaction by the Categorizer, with a confidence score.
_Avoid_: guess, classification

**Categorizer**:
The trained model that produces Predictions.
_Avoid_: classifier, model (alone)

**Prediction Pipeline**:
The process that takes transactions through prediction and review-priority assignment, and persists the outcome.
_Avoid_: categorization strategy, hybrid categorization

**Review**:
A human confirming or correcting a transaction's predicted category. Reviewed transactions are training data.
_Avoid_: approval, validation

**Review Priority**:
The bucket the Prediction Pipeline assigns a transaction: `auto_accepted` (at or above the Auto-approve Threshold) or `standard` (needs review). `high` and `quality_check` are legacy values from the retired Strategic Selection step and may still appear on older rows.
_Avoid_: review status, priority level

**Auto-accept**:
Applying a high-confidence Prediction as the transaction's category without human review.
_Avoid_: auto-approve (as a verb; the threshold keeps its historical name)

**Auto-approve Threshold**:
The confidence score at or above which a Prediction is eligible for auto-accept.
_Avoid_: confidence threshold

**Merchant Rule**:
An exact-match mapping from a Merchant Pattern to a category, derived from reviewed transactions on every training run and refreshed for one pattern after each review. In the ensemble a rule is a third weighted voter beside LightGBM and Naive Bayes; its weight is learned on validation and recorded in every Prediction Event.
_Avoid_: merchant mapping (the table name), pattern

**Audit Trail**:
The append-only record of how a transaction got its category: its Prediction Events and Review Events, viewable per transaction.
_Avoid_: history, log

**Prediction Event**:
One Prediction Pipeline run's full output for one transaction: what the Merchant Rule, LightGBM, and Naive Bayes each proposed, the ensemble weights, the model identity, and the decision against the Auto-approve Threshold.
_Avoid_: prediction record, explanation

**Review Event**:
One category assignment on a transaction, with its actor: the reviewer, an auto-accept, a bulk approve, a labelled import, or a propagation from a sibling transaction.
_Avoid_: correction, change log

**Merchant Pattern**:
The cleaned merchant name stored on a transaction. It groups the sibling transactions a correction propagates to and keys the transaction's Merchant Rule.
_Avoid_: merchant, cleaned name

**Propagation**:
Applying a category the reviewer just saved to the unreviewed transactions sharing its Merchant Pattern that the model predicted the same way (like the source, or as the saved category, or not at all). Siblings the model predicted differently stay in the queue. Each affected transaction gets its own Review Event.
_Avoid_: bulk apply, mass update

**Categorization Summary**:
The auto-accepted and needs-review counts reported after one Prediction Pipeline run.
_Avoid_: prediction stats, results
