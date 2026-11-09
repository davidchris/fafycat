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
    const scriptPath = path.join(__dirname, '..', 'src', 'fafycat', 'static', 'js', 'analytics_page.js');
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

test('top transactions defaults to the latest month with data for the selected year', () => {
    const monthSelector = { value: '4' };
    const hooks = loadAnalyticsPageController({
        elements: {
            'global-year-selector': { value: 'ytd' },
            'month-selector': monthSelector
        },
        analyticsPageConfig: {
            defaultYear: 2026,
            latestTransactionDate: '2026-03-31'
        }
    });

    hooks.syncTopTransactionsMonthToYearSelection();

    assert.equal(monthSelector.value, '3');
});

test('withReviewFilter sends include_unreviewed=false only when the exclude toggle is checked', () => {
    const toggle = { checked: false };
    const hooks = loadAnalyticsPageController({ elements: { 'exclude-unreviewed-toggle': toggle } });

    const included = new URL(hooks.withReviewFilter('/api/analytics/summary?year=2026'));
    assert.equal(included.searchParams.get('include_unreviewed'), 'true');
    assert.equal(included.searchParams.get('year'), '2026');

    toggle.checked = true;
    const excluded = new URL(hooks.withReviewFilter('/api/analytics/summary?year=2026'));
    assert.equal(excluded.searchParams.get('include_unreviewed'), 'false');
    assert.equal(excluded.searchParams.get('year'), '2026');
});

test('renderUnreviewedAlert warns with a review link when unreviewed rows are counted', () => {
    const container = createElement('div');
    const hooks = loadAnalyticsPageController({ elements: { 'unreviewed-alert-container': container } });

    hooks.renderUnreviewedAlert({ count: 3, amount: -12.5, included: true });

    assert.equal(container.children.length, 1);
    const [alert] = container.children;
    assert.equal(alert.className, 'alert alert-warning');
    const [text, link] = alert.children;
    assert.match(text.textContent, /^3 unreviewed transactions \(.*\) in this range are counted under their predicted category\./);
    assert.equal(link.href, '/review');
});

test('renderUnreviewedAlert says rows are excluded when the toggle drops them, and clears at zero', () => {
    const container = createElement('div');
    const hooks = loadAnalyticsPageController({ elements: { 'unreviewed-alert-container': container } });

    hooks.renderUnreviewedAlert({ count: 2, amount: 40, included: false });

    assert.equal(container.children.length, 1);
    assert.equal(container.children[0].className, 'text-secondary');
    assert.match(container.children[0].textContent, /^2 unreviewed transactions \(.*\) are excluded from these numbers\.$/);

    hooks.renderUnreviewedAlert({ count: 0, amount: 0, included: true });

    assert.equal(container.children.length, 0);
});
