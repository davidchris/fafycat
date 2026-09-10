// Review page: retrain the model and re-predict the queue in one click.
//
// The retrain endpoint hands back a job id and does the work in a background
// thread, so this script starts the job, polls it to completion, re-predicts
// the unreviewed transactions with the fresh model, and reloads the table.

const POLL_INTERVAL_MS = 2000;
const MAX_POLLS = 600; // 20 minutes at the poll interval above
const QUEUE_TABLE_URL =
    '/api/transactions/table?status=pending&sort_by=confidence_score&sort_order=asc';
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

document.addEventListener('DOMContentLoaded', function () {
    const button = document.getElementById('retrain-repredict-btn');
    if (button) {
        button.addEventListener('click', runRetrainAndRepredict);
    }

    document.querySelectorAll('[data-dismiss-alert]').forEach(function (dismiss) {
        dismiss.addEventListener('click', function () {
            const alert = dismiss.closest('.alert');
            if (alert) {
                alert.style.display = 'none';
            }
        });
    });
});

async function runRetrainAndRepredict() {
    const button = document.getElementById('retrain-repredict-btn');
    const idleLabel = button.textContent;

    button.disabled = true;
    hideRetrainAlert();

    try {
        setButtonLabel('Starting training…');
        const jobId = await startTraining();
        await pollUntilFinished(jobId);

        setButtonLabel('Re-predicting the queue…');
        const summary = await repredictQueue();

        setButtonLabel('Refreshing…');
        await refreshQueueTable();
        await refreshRecencyCounter();

        showRetrainAlert(describeRepredictSummary(summary), 'alert-success');
    } catch (error) {
        showRetrainAlert(error.message, 'alert-error');
    } finally {
        button.textContent = idleLabel;
        button.disabled = false;
    }
}

// --- steps -----------------------------------------------------------------

async function startTraining() {
    const response = await fetch('/api/ml/retrain', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
    });
    const data = await response.json().catch(() => ({}));

    // 409 means a job is already running; join it instead of starting a second.
    if (response.status === 409) {
        const jobId = data.detail && data.detail.job_id;
        if (!jobId) {
            throw new Error('Training is already running, but the server did not name the job.');
        }
        return jobId;
    }
    if (!response.ok || !data.job_id) {
        throw new Error(errorMessage(data, 'Could not start training.'));
    }
    return data.job_id;
}

async function pollUntilFinished(jobId) {
    for (let poll = 0; poll < MAX_POLLS; poll++) {
        await sleep(POLL_INTERVAL_MS);

        const response = await fetch('/api/ml/training-status/' + encodeURIComponent(jobId));
        if (!response.ok) {
            continue; // transient; the job keeps running without us
        }

        const job = await response.json();
        if (job.phase_description) {
            setButtonLabel(job.phase_description + ' (' + job.progress + '%)');
        }
        if (job.status === 'completed') {
            return;
        }
        if (job.status === 'failed') {
            throw new Error(job.error || 'Training failed.');
        }
    }
    throw new Error('Training is taking longer than expected. Check the settings page.');
}

async function repredictQueue() {
    const response = await fetch('/api/ml/predict/batch-repredict', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
        throw new Error(errorMessage(data, 'Re-prediction failed.'));
    }
    return data;
}

function refreshQueueTable() {
    if (typeof htmx === 'undefined') {
        return Promise.resolve();
    }
    return htmx.ajax('GET', QUEUE_TABLE_URL, '#transaction-table');
}

async function refreshRecencyCounter() {
    const element = document.getElementById('training-recency-text');
    if (!element) {
        return;
    }
    const response = await fetch('/api/ml/status');
    if (!response.ok) {
        return;
    }
    element.textContent = recencyText(await response.json());
}

// --- text ------------------------------------------------------------------

function recencyText(status) {
    const count = status.reviews_since_training || 0;
    const noun = count === 1 ? 'review' : 'reviews';

    if (!status.last_trained_at) {
        return count + ' ' + noun + ' recorded. The model has never been trained.';
    }
    return count + ' ' + noun + ' since the model was last trained (' + formatDate(status.last_trained_at) + ')';
}

function formatDate(isoString) {
    const parsed = new Date(isoString);
    if (isNaN(parsed.getTime())) {
        return 'unknown date';
    }
    const day = String(parsed.getUTCDate()).padStart(2, '0');
    return day + ' ' + MONTHS[parsed.getUTCMonth()] + ' ' + parsed.getUTCFullYear();
}

function describeRepredictSummary(summary) {
    const made = summary.predictions_made || 0;
    if (!made) {
        return 'Model retrained. No transactions needed a new prediction.';
    }
    const autoAccepted = summary.auto_accepted || 0;
    return (
        'Model retrained and ' + made + ' transactions re-predicted — ' +
        autoAccepted + ' auto-accepted, ' + (made - autoAccepted) + ' left to review.'
    );
}

function errorMessage(data, fallback) {
    if (typeof data.detail === 'string') {
        return data.detail;
    }
    if (data.detail && data.detail.message) {
        return data.detail.message;
    }
    return fallback;
}

// --- small helpers ---------------------------------------------------------

function setButtonLabel(text) {
    const button = document.getElementById('retrain-repredict-btn');
    if (button) {
        button.textContent = text;
    }
}

function showRetrainAlert(message, variant) {
    const alert = document.getElementById('retrain-alert');
    if (!alert) {
        return;
    }
    alert.className = 'alert ' + variant + ' mt-3';
    alert.textContent = message;
    alert.hidden = false;
}

function hideRetrainAlert() {
    const alert = document.getElementById('retrain-alert');
    if (alert) {
        alert.hidden = true;
        alert.textContent = '';
    }
}

function sleep(ms) {
    return new Promise(function (resolve) {
        setTimeout(resolve, ms);
    });
}
