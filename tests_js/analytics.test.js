const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function loadAnalyticsHooks() {
    const scriptPath = path.join(__dirname, '..', 'src', 'fafycat', 'static', 'js', 'analytics.js');
    const source = fs.readFileSync(scriptPath, 'utf8');

    const context = {
        window: {
            __ANALYTICS_TEST_HOOKS__: {}
        },
        document: {
            documentElement: {}
        },
        getComputedStyle() {
            return {
                getPropertyValue() {
                    return '';
                }
            };
        },
        Chart: {
            defaults: {
                plugins: {
                    title: {},
                    tooltip: {}
                }
            }
        },
        console
    };

    vm.runInNewContext(source, context, { filename: scriptPath });
    return context.window.__ANALYTICS_TEST_HOOKS__;
}

test('toRgba supports rgb() CSS color strings from custom properties', () => {
    const hooks = loadAnalyticsHooks();

    assert.equal(hooks.toRgba('rgb(30, 95, 175)', 0.7), 'rgba(30, 95, 175, 0.7)');
    assert.equal(hooks.toRgba('rgba(230, 59, 46, 1)', 0.8), 'rgba(230, 59, 46, 0.8)');
});

test('savingsRate is net saved over income, negative when de-saving', () => {
    const hooks = loadAnalyticsHooks();

    // Monthly summary saving is a signed cash flow: money moved to savings is negative.
    assert.equal(hooks.savingsRate({ income: 3000, saving: -600 }), 20);
    assert.equal(hooks.savingsRate({ income: 2000, saving: 100 }), -5);
    assert.equal(hooks.savingsRate({ income: 0, saving: -600 }), 0);
});

test('savingsTrackingSeries keeps a de-saving month below zero', () => {
    const hooks = loadAnalyticsHooks();

    const series = hooks.savingsTrackingSeries([
        { month: '2025-03', amount: 300, cumulative_amount: 300 },
        { month: '2025-04', amount: -400, cumulative_amount: -100 },
    ]);

    assert.deepEqual([...series.monthly], [300, -400]);
    assert.deepEqual([...series.cumulative], [300, -100]);
});

test('netSavedByCategory sorts saving categories by net saved', () => {
    const hooks = loadAnalyticsHooks();

    const rows = hooks.netSavedByCategory([
        { category_name: 'rainy_day', category_type: 'saving', amount: 250 },
        { category_name: 'groceries', category_type: 'spending', amount: -900 },
        { category_name: 'pension', category_type: 'saving', amount: -700 },
    ]);

    assert.deepEqual(rows.map(r => [r.category.category_name, r.netSaved]), [['pension', 700], ['rainy_day', -250]]);
});
