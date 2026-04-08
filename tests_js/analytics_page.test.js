const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function createElement(tagName) {
    return {
        tagName: tagName.toUpperCase(),
        children: [],
        className: '',
        textContent: '',
        value: '',
        id: '',
        type: '',
        checked: false,
        dataset: {},
        style: {},
        appendChild(child) {
            this.children.push(child);
            return child;
        },
        append(...children) {
            children.forEach(child => this.appendChild(child));
        },
        replaceChildren(...children) {
            this.children = [...children];
        }
    };
}

function loadAnalyticsPageController({ elements = {}, analyticsPageConfig = {}, now = '2026-04-08T12:00:00Z' } = {}) {
    const scriptPath = path.join(__dirname, '..', 'static', 'js', 'analytics_page.js');
    const source = fs.readFileSync(scriptPath, 'utf8');

    class FakeDate extends Date {
        constructor(...args) {
            super(args.length === 0 ? now : args[0]);
        }

        static now() {
            return new Date(now).valueOf();
        }
    }

    const document = {
        documentElement: {},
        getElementById(id) {
            return elements[id] || null;
        },
        querySelectorAll() {
            return [];
        },
        createElement,
        addEventListener() {}
    };

    const window = {
        location: { origin: 'http://localhost:8000' },
        analyticsPageConfig,
        __ANALYTICS_PAGE_TEST_HOOKS__: {}
    };

    const context = {
        window,
        document,
        console,
        URL,
        Date: FakeDate,
        fetch: async () => {
            throw new Error('fetch not stubbed');
        },
        alert() {}
    };

    vm.runInNewContext(source, context, { filename: scriptPath });

    return window.__ANALYTICS_PAGE_TEST_HOOKS__;
}

test('getYearSelection uses the latest data date for YTD defaults', () => {
    const hooks = loadAnalyticsPageController({
        elements: {
            'global-year-selector': { value: 'ytd' }
        },
        analyticsPageConfig: {
            defaultYear: 2025,
            latestTransactionDate: '2025-08-15'
        }
    });

    const selection = hooks.getYearSelection();

    assert.equal(selection.actualYear, 2025);
    assert.equal(selection.startDate, '2025-01-01');
    assert.equal(selection.endDate, '2025-08-15');
    assert.equal(selection.isYtd, true);
});

test('renderYoyYearCheckboxes preselects the latest three years when more than three exist', () => {
    const yoyYearsContainer = createElement('div');
    const hooks = loadAnalyticsPageController({
        elements: {
            'yoy-years-container': yoyYearsContainer
        }
    });

    hooks.renderYoyYearCheckboxes([2026, 2025, 2024, 2023, 2022]);

    const checkedYears = yoyYearsContainer.children
        .map(row => row.children[0])
        .filter(checkbox => checkbox.checked)
        .map(checkbox => Number(checkbox.value));

    assert.deepEqual(checkedYears, [2026, 2025, 2024]);
});
