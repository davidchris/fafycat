const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function loadEscapeHtml() {
    const source = fs.readFileSync(path.join(__dirname, '..', 'src', 'fafycat', 'static', 'js', 'main.js'), 'utf8');
    const context = { window: {}, document: { addEventListener() {} } };
    vm.runInNewContext(source, context);
    return context.window.escapeHtml;
}

test('escapeHtml output is safe inside a quoted attribute and as text', () => {
    const escapeHtml = loadEscapeHtml();
    const name = `x" onclick="alert(1)' <img src=x>&`;
    assert.equal(escapeHtml(name), 'x&quot; onclick=&quot;alert(1)&#39; &lt;img src=x&gt;&amp;');
    assert.equal(escapeHtml(null), '');
});
