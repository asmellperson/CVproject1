import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import vm from 'node:vm'
import ts from 'typescript'

const source = readFileSync(new URL('../src/components/face_recognition/api.ts', import.meta.url), 'utf8')
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText

function apiFixture() {
  const calls = []
  const context = {
    exports: {}, URLSearchParams,
    require: (name) => {
      assert.equal(name, '@/lib/api')
      return { apiUrl: (path) => `http://test/api/${path}` }
    },
    fetch: async (url, options) => {
      calls.push({ url: new URL(url), options })
      return { ok: true, status: 200, json: async () => ({}) }
    },
  }
  vm.runInNewContext(compiled, context)
  return { api: context.exports, calls }
}

test('人员权限查询携带当前事业部，允许状态筛选不丢失归属', async () => {
  const { api, calls } = apiFixture()
  for (const department of ['general_electric', 'electronics_electrician', 'electrical_components']) {
    await api.getFacePersons(department, { page: 1, page_size: 20, is_allowed: true })
    const { url, options } = calls.at(-1)
    assert.equal(url.pathname, '/api/face-recognition/persons')
    assert.equal(url.searchParams.get('department'), department)
    assert.equal(url.searchParams.get('is_allowed'), 'true')
    assert.equal(options.cache, 'no-store')
  }
})

test('添加和取消同一人的权限均明确指定事业部，并传递取消请求信号', async () => {
  const { api, calls } = apiFixture()
  const controller = new AbortController()
  await api.updateFacePerson('general_electric', 7, true, controller.signal)
  await api.updateFacePerson('electronics_electrician', 7, false, controller.signal)
  assert.equal(calls[0].url.searchParams.get('department'), 'general_electric')
  assert.equal(calls[1].url.searchParams.get('department'), 'electronics_electrician')
  for (const [index, { url, options }] of calls.entries()) {
    assert.equal(url.pathname, '/api/face-recognition/persons/7')
    assert.equal(options.method, 'PATCH')
    assert.equal(options.signal, controller.signal)
    assert.equal(JSON.parse(options.body).is_allowed, index === 0)
  }
})
