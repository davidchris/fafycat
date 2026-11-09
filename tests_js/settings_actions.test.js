// Settings page actions (static/js/settings.js) and the re-predict walk (static/js/repredict.js),
// run against a fake fetch so the server's answers can be scripted.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const JS_DIR = path.join(__dirname, '..', 'src', 'fafycat', 'static', 'js');

function jsonResponse(status, body) {
    return { ok: status >= 200 && status < 300, status, json: async () => body };
}

// Load the scripts into one context. `responses` maps "METHOD url" to a response or a function of the call.
function loadPage(files, { responses = {}, prompts = [] } = {}) {
    const calls = [];
    const alerts = [];
    let reloads = 0;
    const context = {
        console,
        encodeURIComponent,
        prompt: () => prompts.shift() ?? null,
        confirm: () => true,
        alert: message => alerts.push(message),
        location: { reload: () => { reloads += 1; } },
        document: { querySelectorAll: () => [], getElementById: () => null },
        fetch: async (url, options = {}) => {
            const key = (options.method || 'GET') + ' ' + url;
            calls.push({ key, body: options.body });
            const answer = responses[key] ?? responses[(options.method || 'GET') + ' *'];
            if (!answer) {
                return jsonResponse(200, {});
            }
            return typeof answer === 'function' ? answer(url) : answer;
        },
    };
    context.window = context;
    for (const file of files) {
        const scriptPath = path.join(JS_DIR, file);
        vm.runInNewContext(fs.readFileSync(scriptPath, 'utf8'), context, { filename: scriptPath });
    }
    return { context, calls, alerts, reloads: () => reloads };
}

const flush = () => new Promise(resolve => setImmediate(resolve));

test('creating a category posts it and reloads on success', async () => {
    const page = loadPage(['settings.js'], {
        prompts: ['  Groceries ', 'spending'],
        responses: { 'POST /api/categories/': jsonResponse(200, { id: 1 }) },
    });

    page.context.showCreateCategoryModal();
    await flush();

    const post = page.calls.find(call => call.key === 'POST /api/categories/');
    assert.deepEqual(JSON.parse(post.body), { name: 'Groceries', type: 'spending', budget: 0 });
    assert.equal(page.reloads(), 1);
    assert.deepEqual(page.alerts, []);
});

test('a rejected change shows the server error and does not reload', async () => {
    const page = loadPage(['settings.js'], {
        prompts: ['groceries', 'spending'],
        responses: {
            'POST /api/categories/': jsonResponse(409, { detail: "Category 'groceries' already exists" }),
        },
    });

    page.context.showCreateCategoryModal();
    await flush();

    assert.equal(page.reloads(), 0);
    assert.deepEqual(page.alerts, ["Error creating category: Category 'groceries' already exists"]);
});

test('a rejected budget shows the validation message', async () => {
    const page = loadPage(['settings.js'], {
        prompts: ['-5'],
        responses: {
            'PUT /api/categories/3/budget?budget=-5': jsonResponse(422, {
                detail: [{ msg: 'Input should be greater than or equal to 0' }],
            }),
        },
    });

    page.context.editBudget(3, 'groceries', 0);
    await flush();

    assert.equal(page.reloads(), 0);
    assert.deepEqual(page.alerts, ['Error updating budget: Input should be greater than or equal to 0']);
});

test('repredictAll follows next_cursor until the server says it is done', async () => {
    const pages = {
        '': { predictions_made: 1000, auto_accepted: 10, needs_review: 990, remaining_unreviewed: 1500, next_cursor: 'id-1000' },
        'id-1000': { predictions_made: 1000, auto_accepted: 5, needs_review: 995, remaining_unreviewed: 500, next_cursor: 'id-2000' },
        'id-2000': { predictions_made: 500, auto_accepted: 0, needs_review: 500, remaining_unreviewed: 0, next_cursor: null },
    };
    const page = loadPage(['repredict.js'], {
        responses: {
            'POST *': url => jsonResponse(200, pages[new URL(url, 'http://x').searchParams.get('after') ?? '']),
        },
    });
    const progress = [];

    const total = await page.context.repredictAll(remaining => progress.push(remaining));

    assert.deepEqual(page.calls.map(call => call.key), [
        'POST /api/ml/predict/batch-repredict?limit=1000',
        'POST /api/ml/predict/batch-repredict?limit=1000&after=id-1000',
        'POST /api/ml/predict/batch-repredict?limit=1000&after=id-2000',
    ]);
    assert.deepEqual(progress, [1500, 500]);
    assert.deepEqual(
        { ...total },
        { predictions_made: 2500, auto_accepted: 15, needs_review: 2485, remaining: 0 },
    );
});

test('repredictAll stops with the server error', async () => {
    const page = loadPage(['repredict.js'], {
        responses: { 'POST *': jsonResponse(503, { detail: 'No trained ensemble ML model found.' }) },
    });

    await assert.rejects(page.context.repredictAll(), /No trained ensemble ML model found/);
});
