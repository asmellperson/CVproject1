import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import vm from 'node:vm'
import ts from 'typescript'

const source = await readFile(new URL('../src/lib/api.ts', import.meta.url), 'utf8')
const ast = ts.createSourceFile('api.ts', source, ts.ScriptTarget.Latest, true)
const names = ['getAlarmDispositions', 'apiGet', 'queryString', 'withQuery']
const selected = ast.statements.filter(node =>
  (ts.isFunctionDeclaration(node) && names.includes(node.name?.text)) ||
  (ts.isVariableStatement(node) && node.declarationList.declarations.some(d => names.includes(d.name.getText(ast)))),
).map(node => node.getText(ast)).join('\n')
const compiled = ts.transpileModule(selected, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText

function harness(response) {
  const calls = []
  const context = { exports: {}, API_PREFIX: '/api', URLSearchParams, notifyUnauthorized() {},
    fetch: async (url, options) => {
      calls.push({ url, options })
      return { ok: true, status: 200, json: async () => response }
    },
  }
  vm.runInNewContext(compiled, context)
  return { context, calls, get: context.exports.getAlarmDispositions }
}

test('disposition helper returns a page and forwards continuation and cancellation', async () => {
  const page = { items: [], next_cursor: 'continue-next', stop_reason: 'scan_limit' }
  const { get, calls } = harness(page)
  const signal = new AbortController().signal
  assert.equal(await get({ limit: 25, cursor: 'opaque+/=' }, signal), page)
  assert.equal(calls.length, 1)
  assert.equal(calls[0].url, '/api/alarm-dispositions?limit=25&cursor=opaque%2B%2F%3D')
  assert.equal(calls[0].options.credentials, 'include')
  assert.equal(calls[0].options.signal, signal)
  // 空的 scan_limit 页必须保留续查信息，不能被扁平化成数组或自动扫描全部页。
  assert.equal(page.next_cursor, 'continue-next')
})

test('first page uses server defaults and preserves the explicit end marker', async () => {
  const page = { items: [{ alarm_id: 'aivision:1' }], next_cursor: null, stop_reason: 'end' }
  const { get, calls } = harness(page)
  assert.equal(await get(), page)
  assert.equal(calls[0].url, '/api/alarm-dispositions')
})

test('upstream and expired cursor errors propagate instead of becoming empty pages', async () => {
  const { get, context } = harness(null)
  for (const status of [409, 410, 502, 503, 504]) {
    context.fetch = async () => ({ ok: false, status, statusText: 'test error' })
    await assert.rejects(get({ cursor: 'retry-same-cursor' }), new RegExp(String(status)))
  }
})
