// Re-predict every unreviewed transaction, one page at a time.
//
// POST /api/ml/predict/batch-repredict returns one page and a next_cursor.
// Rows below the auto-approve threshold stay unreviewed, so the walk follows
// the cursor rather than re-running the same filter until it is empty.

const REPREDICT_PAGE_SIZE = 1000;
const MAX_REPREDICT_PAGES = 1000; // safety stop; the server ends the walk with next_cursor = null

/**
 * Re-predict all pages and return the summed counts.
 *
 * @param {function(number): void} [onPage] called with the rows still to do after each page
 * @returns {Promise<{predictions_made: number, auto_accepted: number, needs_review: number, remaining: number}>}
 *   remaining is 0 unless the safety stop was hit
 */
async function repredictAll(onPage) {
    const total = { predictions_made: 0, auto_accepted: 0, needs_review: 0, remaining: 0 };
    let cursor = null;
    for (let page = 0; page < MAX_REPREDICT_PAGES; page++) {
        const url = '/api/ml/predict/batch-repredict?limit=' + REPREDICT_PAGE_SIZE +
            (cursor ? '&after=' + encodeURIComponent(cursor) : '');
        const response = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            const detail = typeof data.detail === 'string' ? data.detail : 'Re-prediction failed.';
            throw new Error(detail);
        }
        total.predictions_made += data.predictions_made || 0;
        total.auto_accepted += data.auto_accepted || 0;
        total.needs_review += data.needs_review || 0;
        total.remaining = data.remaining_unreviewed || 0;
        cursor = data.next_cursor;
        if (!cursor) {
            return total;
        }
        if (onPage) {
            onPage(total.remaining);
        }
    }
    return total;
}
