import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'

const frontendRoot = new URL('../', import.meta.url)
const read = (path) => readFile(new URL(path, frontendRoot), 'utf8').catch(() => '')

async function importTypeScript(value) {
  const output = ts.transpileModule(value, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  }).outputText
  return import(`data:text/javascript;base64,${Buffer.from(output).toString('base64')}`)
}

test('first status sample establishes a baseline without a synthetic event', async () => {
  const source = await read('src/components/logistics_single_person/monitorPresentation.ts')
  const { appendLogisticsStatusEvent } = await importTypeScript(source)

  assert.deepEqual(appendLogisticsStatusEvent([], null, { reason: 'normal' }), [])
  assert.deepEqual(appendLogisticsStatusEvent([], null, { reason: 'empty' }), [])
})

test('a real logistics reason transition appends an event', async () => {
  const source = await read('src/components/logistics_single_person/monitorPresentation.ts')
  const { appendLogisticsStatusEvent } = await importTypeScript(source)

  const next = appendLogisticsStatusEvent([], 'normal', { reason: 'multiple' })
  assert.equal(next.length, 1)
  assert.equal(next[0].reason, 'multiple')
  assert.match(next[0].id, /-multiple$/)
})

test('a retained frame with a new request error is stale rather than online', async () => {
  const source = await read('src/components/logistics_single_person/monitorPresentation.ts')
  const { getLogisticsFramePresentation } = await importTypeScript(source)

  assert.deepEqual(getLogisticsFramePresentation('blob:recent', '帧请求超时'), {
    state: 'stale',
    label: '画面异常 / 最近帧',
    showFrame: true,
    errorMessage: '帧请求超时',
  })
  assert.equal(getLogisticsFramePresentation('blob:live', null).state, 'live')
  assert.equal(getLogisticsFramePresentation(null, '连接失败').state, 'error')
  assert.equal(getLogisticsFramePresentation(null, null).state, 'waiting')
})
