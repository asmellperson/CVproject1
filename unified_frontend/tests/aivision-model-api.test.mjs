import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import vm from 'node:vm'
import ts from 'typescript'

const root = new URL('../', import.meta.url)
const apiSource = await readFile(new URL('src/lib/aivision.ts', root), 'utf8')
const componentSource = await readFile(new URL('src/components/AiVisionModelConfig.tsx', root), 'utf8')
const compile = (source) => ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
}).outputText

test('fixed model API lists status and saves only a local path by model name', async () => {
  const ast = ts.createSourceFile('api.ts', apiSource, ts.ScriptTarget.Latest, true)
  const source = ast.statements.filter((node) =>
    ts.isFunctionDeclaration(node)
    && ['getAiVisionModels', 'updateAiVisionModelPath'].includes(node.name?.text),
  ).map((node) => node.getText(ast)).join('\n')
  const calls = []
  const context = {
    exports: {},
    fetch: async (url, options) => {
      calls.push({ url, options })
      return { ok: true, json: async () => ({ configuration_saved: true, load_status: 'loading' }) }
    },
  }
  vm.runInNewContext(compile(source), context)
  const signal = new AbortController().signal
  await context.exports.getAiVisionModels(signal)
  const result = await context.exports.updateAiVisionModelPath('yolo_phone', '/local/model.pt')
  assert.equal(calls[0].url, '/api/models')
  assert.equal(calls[0].options.signal, signal)
  assert.equal(calls[1].url, '/api/models/yolo_phone/path')
  assert.equal(calls[1].options.method, 'PATCH')
  assert.deepEqual(JSON.parse(calls[1].options.body), { path: '/local/model.pt' })
  assert.equal(result.configuration_saved, true)
  assert.equal(result.load_status, 'loading')
  assert.doesNotMatch(apiSource, /createAiVisionModel|CreateAiVisionModelPayload/)
})

function model(overrides = {}) {
  return {
    name: 'yolo_human', type: 'yolo', path: '/local/old.pt',
    runtime: {
      status: 'failed', running: false, alive: false, loaded_path: '',
      last_failure: 'bad weights', shared_models: ['yolo_human'],
    },
    reload: { status: 'idle', error: '' },
    ...overrides,
  }
}

function harness({ isAdmin = true, requiredModels = ['yolo_human'] } = {}) {
  const states = []
  let cursor = 0
  let poll
  let items = [model()]
  const saves = []
  const react = {
    useState(initial) {
      const slot = cursor++
      if (!(slot in states)) states[slot] = initial
      return [states[slot], (next) => {
        states[slot] = typeof next === 'function' ? next(states[slot]) : next
      }]
    },
    useMemo(fn) { return fn() },
  }
  const context = {
    exports: {},
    require(name) {
      if (name === 'react') return react
      if (name === 'react/jsx-runtime') return {
        jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }),
      }
      if (name === '@/auth/useAuth') return { useAuth: () => ({ isAdmin }) }
      if (name === '@/hooks/use-serial-poll') return { useSerialPoll: (fn) => { poll = fn } }
      if (name === '@/lib/aivision') return {
        getAiVisionModels: async () => items,
        updateAiVisionModelPath: async (name, path) => {
          saves.push({ name, path })
          return { configuration_saved: true, name, path, load_status: 'loading' }
        },
      }
      return new Proxy({}, { get: (_, key) => String(key) })
    },
  }
  vm.runInNewContext(compile(componentSource), context)
  return {
    saves,
    setItems(next) { items = next },
    poll: () => poll(),
    render() {
      cursor = 0
      return context.exports.AiVisionModelConfig({ requiredModels })
    },
  }
}

function nodes(tree) {
  if (tree === null || tree === undefined || typeof tree === 'boolean') return []
  if (Array.isArray(tree)) return tree.flatMap(nodes)
  if (typeof tree !== 'object') return [tree]
  return [tree, ...nodes(tree.props?.children), ...nodes(tree.props?.actions)]
}

const textOf = (tree) => nodes(tree).filter((node) => typeof node === 'string').join(' ')
const find = (tree, type) => nodes(tree).find((node) => node?.type === type)

test('pure face detector shows its ONNX path and saves under the independent logical model', async () => {
  const page = harness({ requiredModels: ['insightface_detection'] })
  page.setItems([model({ name: 'insightface_detection', type: 'insightface_detection', path: '/models/det_10g.onnx' })])
  page.render(); await page.poll()
  let tree = page.render()
  assert.match(textOf(tree), /det_10g.onnx/)
  assert.equal(find(tree, 'Input').props.value, '/models/det_10g.onnx')
  find(tree, 'Input').props.onChange({ target: { value: '/new/det_10g.onnx' } })
  tree = page.render()
  await nodes(tree).find((node) => node?.type === 'Button' && textOf(node).includes('保存路径')).props.onClick()
  assert.deepEqual(page.saves, [{ name: 'insightface_detection', path: '/new/det_10g.onnx' }])
})

test('model page shows runtime failure, has no create or enable controls, and protects viewers', async () => {
  const page = harness({ isAdmin: false })
  page.render()
  await page.poll()
  const tree = page.render()
  assert.match(textOf(tree), /加载失败/)
  assert.doesNotMatch(textOf(tree), /创建模型|已启用|停用/)
  assert.equal(find(tree, 'Input').props.disabled, true)
  const save = nodes(tree).find((node) => node?.type === 'Button' && textOf(node).includes('保存路径'))
  assert.equal(save.props.disabled, true)
  await save.props.onClick()
  assert.equal(page.saves.length, 0)
})

test('polling preserves unsaved path edits and save reports loading before the final failure', async () => {
  const page = harness()
  page.render()
  await page.poll()
  let tree = page.render()
  find(tree, 'Input').props.onChange({ target: { value: '/local/new.pt' } })
  page.render()
  await page.poll()
  tree = page.render()
  assert.equal(find(tree, 'Input').props.value, '/local/new.pt')
  const save = nodes(tree).find((node) => node?.type === 'Button' && textOf(node).includes('保存路径'))
  await save.props.onClick()
  tree = page.render()
  assert.equal(page.saves[0].name, 'yolo_human')
  assert.equal(page.saves[0].path, '/local/new.pt')
  assert.match(textOf(tree), /配置保存成功，正在重载模型/)
  assert.doesNotMatch(textOf(tree), /模型加载成功/)
  page.setItems([model({ path: '/local/new.pt', reload: { status: 'failed', error: 'invalid model' } })])
  await page.poll()
  tree = page.render()
  assert.match(textOf(tree), /配置已保存.*模型加载失败/)
  assert.match(textOf(tree), /invalid model/)
})

test('successful worker reload is shown separately from the saved configuration', async () => {
  const page = harness()
  page.render()
  await page.poll()
  let tree = page.render()
  await nodes(tree).find((node) => node?.type === 'Button' && textOf(node).includes('保存路径')).props.onClick()
  page.render()
  page.setItems([model({
    runtime: { ...model().runtime, status: 'running', running: true, loaded_path: '/local/old.pt', last_failure: '' },
    reload: { status: 'succeeded', error: '' },
  })])
  await page.poll()
  tree = page.render()
  assert.match(textOf(tree), /配置保存成功.*模型加载成功/)
  assert.match(textOf(tree), /运行中/)
})
