// Settings page: category management and ML actions.
//
// Loaded by both the empty state and the category management view, after
// repredict.js. Every change reports the server's error instead of reloading.

window._autoApproveThreshold = window._autoApproveThreshold || 0.90;
fetch('/api/ml/settings')
    .then(r => (r.ok ? r.json() : Promise.reject()))
    .then(d => { window._autoApproveThreshold = parseFloat(d.auto_approve_threshold); })
    .catch(() => {});

// Fetch JSON and throw an Error with the server's message when the response is not OK.
async function sendJson(url, options) {
    const response = await fetch(url, options);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
        const detail = data.detail;
        const message = typeof detail === 'string'
            ? detail
            : Array.isArray(detail) && detail.length && detail[0].msg
                ? detail[0].msg
                : 'Request failed (' + response.status + ')';
        throw new Error(message);
    }
    return data;
}

// Run a settings change; reload on success, show the server's error otherwise.
function applyChange(url, options, errorPrefix) {
    return sendJson(url, options)
        .then(() => location.reload())
        .catch(error => alert(errorPrefix + ': ' + error.message));
}

function editBudget(categoryId, categoryName, currentBudget) {
    const newBudget = prompt(`Set monthly budget for "${categoryName}":`, currentBudget);
    if (newBudget !== null && newBudget.trim() !== '' && !isNaN(newBudget)) {
        applyChange(
            `/api/categories/${categoryId}/budget?budget=${parseFloat(newBudget)}`,
            { method: 'PUT' },
            'Error updating budget'
        );
    }
}

function editCategoryType(categoryId, categoryName, currentType) {
    const newType = prompt(`Change type for "${categoryName}" (spending/income/saving):`, currentType);
    if (newType && ['spending', 'income', 'saving'].includes(newType)) {
        applyChange(
            `/api/categories/${categoryId}/type?type=${newType}`,
            { method: 'PUT' },
            'Error updating category type'
        );
    }
}

function deactivateCategory(categoryId, categoryName) {
    if (confirm(`Deactivate category "${categoryName}"? It will be hidden but historical data preserved.`)) {
        applyChange(`/api/categories/${categoryId}`, { method: 'DELETE' }, 'Error deactivating category');
    }
}

function reactivateCategory(categoryId, categoryName) {
    if (confirm(`Reactivate category "${categoryName}"?`)) {
        applyChange(
            `/api/categories/${categoryId}`,
            {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ is_active: true })
            },
            'Error reactivating category'
        );
    }
}

function showCreateCategoryModal() {
    const name = prompt('Category name:');
    if (name && name.trim()) {
        const type = prompt('Category type (spending/income/saving):', 'spending');
        if (type && ['spending', 'income', 'saving'].includes(type)) {
            applyChange(
                '/api/categories/',
                {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name: name.trim(), type: type, budget: 0.0 })
                },
                'Error creating category'
            );
        }
    }
}

function toggleInactiveCategories(button) {
    const hidden = document.querySelectorAll('[data-inactive-overflow]');
    const expand = button.getAttribute('aria-expanded') !== 'true';
    hidden.forEach(row => { row.hidden = !expand; });
    button.setAttribute('aria-expanded', String(expand));
    button.textContent = expand ? 'Show fewer' : button.dataset.collapsedLabel;
}

// Training job polling state
let trainingJobId = null;
let pollInterval = 2000;
let pollCount = 0;

function trainModel() {
    const trainButton = document.getElementById('trainButton');
    if (trainButton) {
        trainButton.disabled = true;
        trainButton.innerHTML = '<svg class="animate-spin mr-2 h-4 w-4" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>Starting...';
    }

    // Start training job
    fetch('/api/ml/retrain', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
    })
    .then(response => {
        if (response.status === 409) {
            return response.json().then(data => {
                // Training already in progress - start polling existing job
                return { job_id: data.detail.job_id, status: 'running' };
            });
        }
        return response.json();
    })
    .then(data => {
        if (data.job_id) {
            trainingJobId = data.job_id;
            showTrainingProgress();
            pollTrainingStatus(data.job_id);
        } else {
            throw new Error(data.detail || 'Failed to start training');
        }
    })
    .catch(error => {
        alert('Training failed: ' + error.message);
        resetTrainButton();
    });
}

function showTrainingProgress() {
    // Create progress container if it doesn't exist
    let container = document.getElementById('training-progress');
    if (!container) {
        container = document.createElement('div');
        container.id = 'training-progress';
        const trainButton = document.getElementById('trainButton');
        if (trainButton && trainButton.parentNode) {
            trainButton.parentNode.insertBefore(container, trainButton.nextSibling);
        }
    }
    container.innerHTML = `
        <div class="alert alert-info mt-4">
            <div class="flex items-center justify-between mb-2">
                <span id="training-phase" class="text-sm font-medium">
                    Preparing...
                </span>
                <span id="training-progress-pct" class="text-sm">0%</span>
            </div>
            <div class="w-full rounded-full h-2" style="background: var(--border-default)">
                <div id="training-progress-bar"
                     class="h-2 rounded-full transition-all duration-300"
                     style="width: 0%; background: var(--color-saving)"></div>
            </div>
        </div>
    `;
}

function pollTrainingStatus(jobId) {
    fetch(`/api/ml/training-status/${jobId}`)
    .then(response => response.json())
    .then(data => {
        updateTrainingProgress(data);

        if (data.status === 'completed') {
            handleTrainingComplete(data.result);
        } else if (data.status === 'failed') {
            handleTrainingFailed(data.error);
        } else {
            // Continue polling
            pollCount++;
            // Adaptive polling: slow down after 30 seconds
            if (pollCount > 15) {
                pollInterval = 3000;
            }
            setTimeout(() => pollTrainingStatus(jobId), pollInterval);
        }
    })
    .catch(error => {
        console.error('Error polling status:', error);
        // Retry on error
        setTimeout(() => pollTrainingStatus(jobId), pollInterval);
    });
}

function updateTrainingProgress(data) {
    const phaseEl = document.getElementById('training-phase');
    const pctEl = document.getElementById('training-progress-pct');
    const barEl = document.getElementById('training-progress-bar');

    if (phaseEl) phaseEl.textContent = data.phase_description;
    if (pctEl) pctEl.textContent = `${data.progress}%`;
    if (barEl) barEl.style.width = `${data.progress}%`;
}

function formatAutoApprove(result) {
    if (result.auto_rate === undefined) return '';
    const pct = (value) => `${(value * 100).toFixed(1)}%`;
    return `\n- Auto-approve at ${pct(result.auto_threshold)}: ${pct(result.auto_rate)} of rows, ${pct(result.auto_error_rate)} of those wrong (out-of-fold)`;
}

function formatPredictions(result) {
    if (result.prediction_error) {
        return `\n\nAuto-prediction failed: ${result.prediction_error}\nYou can predict manually from this page.`;
    }
    if (!result.predictions_made) return '\n\nAll transactions already have predictions.';
    const kept = result.already_reviewed ? `\n- ${result.already_reviewed} already reviewed (kept their category)` : '';
    return `\n\nPredicted ${result.predictions_made} transactions without a prediction:\n- ${result.auto_accepted} auto-accepted\n- ${result.needs_review} need your review${kept}`;
}

function handleTrainingComplete(result) {
    const accuracy = (result.accuracy * 100).toFixed(1);
    const samples = result.training_samples;
    const autoApprove = formatAutoApprove(result);
    alert(`Model training completed!\n\nAccuracy: ${accuracy}%\nTraining samples: ${samples}${autoApprove}${formatPredictions(result)}`);
    location.reload();
}

function handleTrainingFailed(error) {
    alert('Training failed: ' + error);
    resetTrainButton();
    hideTrainingProgress();
}

function resetTrainButton() {
    const trainButton = document.getElementById('trainButton');
    if (trainButton) {
        trainButton.disabled = false;
        trainButton.innerHTML = '<svg class="mr-2 h-4 w-4" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M11.3 1.046A1 1 0 0112 2v5h4a1 1 0 01.82 1.573l-7 10A1 1 0 018 18v-5H4a1 1 0 01-.82-1.573l7-10a1 1 0 011.12-.38z" clip-rule="evenodd" /></svg>Train ML Model Now';
    }
    pollCount = 0;
    pollInterval = 2000;
}

function hideTrainingProgress() {
    const container = document.getElementById('training-progress');
    if (container) {
        container.innerHTML = '';
    }
}

function retrainModel() {
    if (confirm('Retrain the ML model with current data? This will replace the existing model and automatically predict unpredicted transactions.')) {
        trainModel();
    }
}

function confirmAndPredictUnpredicted(count, button) {
    const pct = (window._autoApproveThreshold * 100).toFixed(0);
    const confirmMessage = `Run ML predictions on ${count} transactions?\n\n` +
        `This will:\n` +
        `- Apply ML predictions to all transactions without predictions\n` +
        `- Auto-accept high-confidence predictions (${pct}%+)\n` +
        `- Add uncertain predictions to your Review Queue\n` +
        `- You may need to review some transactions manually\n\n` +
        `Use this when you've imported transactions before training a model, ` +
        `or after retraining to apply the updated model.\n\n` +
        `Continue?`;

    if (confirm(confirmMessage)) {
        predictUnpredicted(button);
    }
}

function confirmAndRepredict(count, button) {
    const pct = (window._autoApproveThreshold * 100).toFixed(0);
    const confirmMessage = `Re-predict ${count} unreviewed transactions?\n\n` +
        `This will:\n` +
        `- Re-run predictions using the current model on transactions you haven't reviewed yet\n` +
        `- Useful after retraining to apply the improved model\n` +
        `- Auto-accept high-confidence predictions (${pct}%+)\n` +
        `- Add uncertain predictions to your Review Queue\n\n` +
        `Continue?`;

    if (confirm(confirmMessage)) {
        repredictUnreviewed(button);
    }
}

function repredictUnreviewed(button) {
    const originalText = button.innerHTML;
    button.disabled = true;
    button.innerHTML = '<svg class="animate-spin mr-2 h-4 w-4" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>Re-predicting...';

    repredictAll(remaining => {
        button.innerHTML = `Re-predicting... ${remaining} remaining`;
    })
    .then(data => {
        let message = `Re-predicted ${data.predictions_made} transactions!\n\n`;
        message += `- ${data.auto_accepted} auto-accepted (at or above the auto-approve threshold)\n`;
        message += `- ${data.needs_review} need your review\n\n`;
        if (data.remaining) {
            message += `${data.remaining} transactions were not reached; run it again.\n\n`;
        }
        message += `Open the Review page to work through them, lowest confidence first.`;

        alert(message);
        location.reload();
    })
    .catch(error => {
        alert('Re-prediction failed: ' + error.message);
        button.disabled = false;
        button.innerHTML = originalText;
    });
}

function predictUnpredicted(button) {
    const originalText = button.innerHTML;
    button.disabled = true;
    button.innerHTML = '<svg class="animate-spin mr-2 h-4 w-4" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg>Predicting...';

    fetch('/api/ml/predict/batch-unpredicted', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
    })
    .then(response => response.json().catch(() => ({})).then(data => {
        if (!response.ok) {
            throw new Error(typeof data.detail === 'string' ? data.detail : 'Prediction failed');
        }
        return data;
    }))
    .then(data => {
        if (data.status === 'success') {
            const autoAccepted = data.auto_accepted || 0;
            const needsReview = data.needs_review || 0;

            let message = `Predicted ${data.predictions_made} transactions!\n\n`;
            message += `- ${autoAccepted} auto-accepted (at or above the auto-approve threshold)\n`;
            message += `- ${needsReview} need your review\n\n`;
            if (data.remaining_unpredicted) {
                message += `${data.remaining_unpredicted} transactions are still unpredicted; run it again.\n\n`;
            }
            message += `Open the Review page to work through them, lowest confidence first.`;

            alert(message);
            location.reload();
        } else {
            throw new Error(data.detail || 'Prediction failed');
        }
    })
    .catch(error => {
        alert('Prediction failed: ' + error.message);
        button.disabled = false;
        button.innerHTML = originalText;
    });
}
