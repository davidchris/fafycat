const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function loadAnalyticsHooks() {
    const scriptPath = path.join(__dirname, '..', 'static', 'js', 'analytics.js');
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
