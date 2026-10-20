import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import vm from 'node:vm'
import ts from 'typescript'

const source = readFileSync(new URL('../src/components/AiVisionMonitor.frame.ts', import.meta.url), 'utf8')
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText

function deferred() {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

function fixture(decode = async () => {}) {
  const revoked = []
  const created = []
  const frameCalls = []
  const images = []
  const imageDecode = deferred()
  const context = {
    exports: {}, DOMException, setTimeout,
    URL: {
      createObjectURL: () => { const src = `blob:frame-${created.length}`; created.push(src); return src },
      revokeObjectURL: (src) => revoked.push(src),
    },
    Image: class {
      constructor() { images.push(this) }
      decode() { return imageDecode.promise }
    },
    require: (name) => {
      assert.equal(name, '../lib/aivision')
      return { aiVisionFrameUrl: (...args) => { frameCalls.push(args); return '/frame.jpg' } }
    },
  }
  vm.runInNewContext(compiled, context)
  const buffer = context.exports.createPreviewFrameBuffer(decode === null ? {} : { decode })
  return { buffer, created, revoked, images, imageDecode, frameCalls, api: context.exports }
}

test('新图解码并在页面显示前，上一帧保持有效', async () => {
  const next = deferred()
  let count = 0
  const { buffer, revoked } = fixture(() => ++count === 1 ? Promise.resolve() : next.promise)
  const first = await buffer.prepare({}, new AbortController().signal)
  buffer.displayed(first)
  const preparing = buffer.prepare({}, new AbortController().signal)
  assert.deepEqual(revoked, [])
  next.resolve()
  const second = await preparing
  assert.deepEqual(revoked, [])
  buffer.displayed(second)
  assert.deepEqual(revoked, [first])
  buffer.dispose()
  assert.deepEqual(revoked, [first, second])
})

test('坏帧只释放自身，保留上一帧，并允许下一轮恢复', async () => {
  let count = 0
  const { buffer, revoked } = fixture(async () => { if (++count === 2) throw new Error('invalid jpeg') })
  const first = await buffer.prepare({}, new AbortController().signal)
  buffer.displayed(first)
  await assert.rejects(buffer.prepare({}, new AbortController().signal), /invalid jpeg/)
  assert.deepEqual(revoked, ['blob:frame-1'])
  const recovered = await buffer.prepare({}, new AbortController().signal)
  buffer.displayed(recovered)
  assert.deepEqual(revoked, ['blob:frame-1', first])
  buffer.dispose()
})

test('切换摄像头时取消旧帧，迟到的解码结果不能发布或泄漏 URL', async () => {
  const decoding = deferred()
  const { buffer, created, revoked } = fixture(() => decoding.promise)
  const controller = new AbortController()
  const preparing = buffer.prepare({}, controller.signal)
  controller.abort()
  buffer.dispose()
  decoding.resolve()
  await assert.rejects(preparing, { name: 'AbortError' })
  await assert.rejects(buffer.prepare({}, new AbortController().signal), { name: 'AbortError' })
  assert.deepEqual(revoked, created)
})

test('上一张图的 load 事件不能释放正在解码的下一帧', async () => {
  const decoding = deferred()
  let count = 0
  const { buffer, revoked } = fixture(() => ++count === 1 ? Promise.resolve() : decoding.promise)
  const first = await buffer.prepare({}, new AbortController().signal)
  const preparing = buffer.prepare({}, new AbortController().signal)
  buffer.displayed(first)
  assert.deepEqual(revoked, [])
  decoding.resolve()
  const second = await preparing
  buffer.displayed(second)
  assert.deepEqual(revoked, [first])
  buffer.dispose()
})

test('权限失效清理全部图片，旧图 load 事件不影响恢复后的画面', async () => {
  const { buffer, revoked } = fixture()
  const first = await buffer.prepare({}, new AbortController().signal)
  buffer.displayed(first)
  buffer.clear()
  const next = await buffer.prepare({}, new AbortController().signal)
  buffer.displayed(first)
  assert.deepEqual(revoked, [first])
  buffer.displayed(next)
  buffer.dispose()
  assert.deepEqual(revoked, [first, next])
})

test('连续换帧及时释放旧图，退出监控后不存在残留对象 URL', async () => {
  const { buffer, created, revoked } = fixture()
  for (let i = 0; i < 100; i += 1) {
    const src = await buffer.prepare({}, new AbortController().signal)
    buffer.displayed(src)
    assert.equal(created.length - revoked.length, 1)
  }
  buffer.dispose()
  assert.equal(new Set(revoked).size, 100)
  assert.equal(revoked.length, 100)
})

test('浏览器图片解码未结束时，请求超时可以中止并释放资源', async () => {
  const { buffer, images, revoked, imageDecode } = fixture(null)
  const controller = new AbortController()
  const preparing = buffer.prepare({}, controller.signal)
  assert.equal(images[0].src, 'blob:frame-0')
  controller.abort()
  await assert.rejects(preparing, { name: 'AbortError' })
  assert.equal(images[0].src, '')
  assert.deepEqual(revoked, ['blob:frame-0'])
  imageDecode.resolve()
  buffer.dispose()
})

test('预览保留轻量 JPEG 参数及指定功能，原始预览不添加检测功能', () => {
  const { api, frameCalls } = fixture()
  api.buildAiVisionPreviewFrameUrl('camera_80', 'security_fence', 123)
  api.buildAiVisionPreviewFrameUrl('camera_80', '', 124)
  assert.equal(frameCalls[0][1], 'security_fence')
  assert.equal(frameCalls[0][3].maxWidth, 960)
  assert.equal(frameCalls[0][3].quality, 72)
  assert.equal(frameCalls[1][1], '')
})
