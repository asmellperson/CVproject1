import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import vm from 'node:vm'
import ts from 'typescript'

const root = new URL('../', import.meta.url)
const hookSource = await readFile(new URL('src/hooks/use-department-catalog.ts', root), 'utf8')
const apiSource = await readFile(new URL('src/lib/aivision.ts', root), 'utf8')
const compile = (source) => ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText
const plain = (value) => JSON.parse(JSON.stringify(value))
const settle = () => new Promise((resolve) => setImmediate(resolve))

function harness() {
  const states = []
  const calls = []
  let cursor = 0
  let dependencies
  let cleanup
  let effect
  const react = {
    useState(initial) {
      const slot = cursor++
      if (!(slot in states)) states[slot] = initial
      return [states[slot], (next) => {
        states[slot] = typeof next === 'function' ? next(states[slot]) : next
      }]
    },
    useMemo(fn) { return fn() },
    useCallback(fn) { return fn },
    useEffect(fn, nextDependencies) {
      if (!dependencies || nextDependencies.some((value, index) => value !== dependencies[index])) {
        dependencies = nextDependencies
        effect = fn
      }
    },
  }
  const context = {
    exports: {}, AbortController,
    require(name) {
      if (name === 'react') return react
      if (name === '@/lib/aivision') return {
        getAiVisionDepartments: (signal) => new Promise((resolve, reject) => {
          calls.push({ signal, resolve, reject })
        }),
      }
      throw new Error(`unexpected import: ${name}`)
    },
  }
  vm.runInNewContext(compile(hookSource), context)
  return {
    calls,
    render(enabled = true) {
      cursor = 0
      const result = context.exports.useDepartmentCatalog(enabled)
      if (effect) {
        cleanup?.()
        cleanup = effect()
        effect = undefined
      }
      return result
    },
    unmount() { cleanup?.() },
  }
}

test('department API preserves list contract and carries authentication and cancellation', async () => {
  const ast = ts.createSourceFile('api.ts', apiSource, ts.ScriptTarget.Latest, true)
  const functions = ast.statements.filter((node) => ts.isFunctionDeclaration(node)
    && ['getAiVisionDepartments', 'readAiVisionError'].includes(node.name?.text))
  const calls = []
  const items = [{ name: 'registered_company', display_name: '代码注册公司' }]
  let ok = true
  const context = {
    exports: {},
    fetch: async (url, options) => {
      calls.push({ url, options })
      return { ok, status: ok ? 200 : 503, json: async () => items, text: async () => '{"detail":"暂不可用"}' }
    },
  }
  vm.runInNewContext(compile(functions.map((node) => node.getText(ast)).join('\n')), context)
  const signal = new AbortController().signal
  assert.deepEqual(await context.exports.getAiVisionDepartments(signal), items)
  assert.equal(calls[0].url, '/api/departments')
  assert.equal(calls[0].options.credentials, 'include')
  assert.equal(calls[0].options.signal, signal)
  ok = false
  await assert.rejects(context.exports.getAiVisionDepartments(signal), /暂不可用/)
})

test('department choices and labels come entirely from the returned catalog', async () => {
  const hook = harness()
  assert.equal(hook.render().loading, true)
  assert.deepEqual(plain(hook.render().options), [])
  hook.calls[0].resolve([{ name: 'registered_company', display_name: '代码注册公司' }])
  await settle()
  const result = hook.render()
  assert.equal(result.loading, false)
  assert.deepEqual(plain(result.options), [{ value: 'registered_company', label: '代码注册公司' }])
  assert.equal(result.labels.registered_company, '代码注册公司')
  assert.equal(result.labels.all, '全部事业部')
  assert.equal(result.options.some((option) => option.value === 'all'), false)
})

test('failure clears choices and reload recovers without a hardcoded fallback', async () => {
  const hook = harness()
  hook.render()
  hook.calls[0].resolve([{ name: 'first', display_name: '原部门' }])
  await settle()
  hook.render().reload()
  hook.render()
  hook.calls[1].reject(new Error('offline'))
  await settle()
  let result = hook.render()
  assert.equal(result.loading, false)
  assert.match(result.error, /事业部列表加载失败.*offline/)
  assert.deepEqual(plain(result.options), [])
  result.reload()
  hook.render()
  hook.calls[2].resolve([{ name: 'second', display_name: '新部门' }])
  await settle()
  result = hook.render()
  assert.equal(result.error, '')
  assert.deepEqual(plain(result.options), [{ value: 'second', label: '新部门' }])
})

test('disabled and obsolete requests cannot load or overwrite department choices', async () => {
  const hook = harness()
  hook.render(false)
  assert.equal(hook.calls.length, 0)
  hook.render(true).reload()
  hook.render(true)
  assert.equal(hook.calls[0].signal.aborted, true)
  hook.calls[1].resolve([{ name: 'current', display_name: '当前部门' }])
  hook.calls[0].resolve([{ name: 'stale', display_name: '过期部门' }])
  await settle()
  assert.equal(hook.render().options[0].value, 'current')
  hook.unmount()
  assert.equal(hook.calls[1].signal.aborted, true)
})
