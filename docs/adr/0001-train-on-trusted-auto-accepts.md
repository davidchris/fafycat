# Train on Trusted Auto-accepts, grade on Human Labels only

v0.4.0 (#62) trained only on Human Labels, so an auto-accept could not teach the model its own guesses. On real data that dropped 54% of the labels: recurring merchants (salary, Kindergeld, DSL, electricity) are auto-accepted every month, so a human never labels them again. Those categories fell below the training minimum, the model forgot them, and held-out accuracy fell from 0.89 to 0.77. We now train on Human Labels plus Trusted Auto-accepts at half weight, but grade the model (training metrics, calibration table) on Human Labels only. Spot Checks give an unbiased error rate for auto-accepts.

## Considered Options

- **Human Labels only (v0.4.0).** Rejected: the model forgets exactly the merchants it is surest about.
- **Every auto-accept, at full weight (before v0.4.0).** Rejected: a wrong auto-accept reinforces itself on every retrain, and the top calibration band agrees with itself by construction.
- **A separate judge model that vets the auto-accepts.** Rejected: a judge trained on the same labels repeats the same errors. The stack already combines three independent voters (LightGBM, Naive Bayes, Merchant Rules). Independent evidence comes only from a human, so we use Spot Checks.

## Consequences

- An auto-accept trains only after 14 days without a correction, so the reviewer can catch it first. Bulk approves never train, because they can copy Predictions below the Auto-approve Threshold.
- Merchant Rules are derived from the same training labels. A rule can therefore rest on Trusted Auto-accepts, which is where most of the recurring merchants come from.
- The training metrics and the calibration table describe the human-labelled rows, which are harder than average. They understate accuracy on auto-accepted traffic; the Spot Check error rate measures that traffic.
- Bulk approve skips Spot Checks unless they are requested by Review Priority, because a bulk approve would void the check.
