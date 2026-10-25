import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { test } from 'node:test'
import ts from 'typescript'

// 模块在内存中编译，正式回归不向源码目录写入临时编译产物。
async function compile(name) {
  const source = await readFile(new URL(`../src/components/${name}.ts`, import.meta.url), 'utf8')
  return ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  }).outputText
}
const performanceUrl = `data:text/javascript;base64,${Buffer.from(await compile('AiVisionVideoPreview.performance')).toString('base64')}`
const mseCode = (await compile('AiVisionVideoPreview.mse')).replace(
  "'./AiVisionVideoPreview.performance'", JSON.stringify(performanceUrl),
)
const { createVideoPreviewPerformanceRecorder, createVideoPreviewPerformanceGroup } = await import(performanceUrl)
const {
  createMsePreviewSession, createMseAppendQueue, parseMseControlMessage,
  supportedPreviewCodecs, previewWebSocketUrl, MSE_MAX_PENDING_BYTES,
} = await import(`data:text/javascript;base64,${Buffer.from(mseCode).toString('base64')}`)

const mime = 'video/mp4; codecs="avc1.640029"'
function ranges(values = []) {
  return { length: values.length, start: (index) => values[index][0], end: (index) => values[index][1] }
}
function event(target, name, extra = {}) { target.dispatchEvent(Object.assign(new Event(name), extra)) }

class FakeBuffer extends EventTarget {
  updating = false
  buffered = ranges()
  operations = []
  appendBuffer(bytes) {
    assert.equal(this.updating, false, '不能并发追加或删除 SourceBuffer')
    this.operations.push({ append: bytes.byteLength })
    this.updating = true
  }
  remove(start, end) {
    assert.equal(this.updating, false)
    this.operations.push({ remove: [start, end] })
    this.updating = true
  }
  abort() { this.updating = false }
  finish(values) {
    if (values) this.buffered = ranges(values)
    this.updating = false
    event(this, 'updateend')
  }
}
class FakeVideo extends EventTarget {
  src = ''
  srcObject = null
  currentTime = 0
  playbackRate = 1
  videoWidth = 1920
  videoHeight = 1080
  buffered = ranges()
  frames = 0
  dropped = 0
  pauses = 0
  play() { return Promise.resolve() }
  pause() { this.pauses++ }
  removeAttribute(name) { if (name === 'src') this.src = '' }
  load() { this.currentTime = 0 }
  getVideoPlaybackQuality() { return { totalVideoFrames: this.frames, droppedVideoFrames: this.dropped } }
}

function setup(visible = true, isTypeSupported = (type) => type.includes('avc1'), context = {}) {
  let clock = 0
  let sequence = 0
  const timers = new Map()
  const mediaSources = []
  const sockets = []
  const revoked = []
  const states = []
  const reports = []
  const video = new FakeVideo()
  let fallbacks = 0
  let denied = 0
  class FakeMediaSource extends EventTarget {
    readyState = 'closed'
    sourceBuffers = []
    constructor() { super(); mediaSources.push(this) }
    open() { this.readyState = 'open'; event(this, 'sourceopen') }
    addSourceBuffer(type) {
      assert.equal(type, mime)
      const buffer = new FakeBuffer()
      this.sourceBuffers.push(buffer)
      return buffer
    }
    endOfStream() { this.readyState = 'ended' }
  }
  class FakeSocket extends EventTarget {
    readyState = 0
    sent = []
    constructor(url) { super(); this.url = url; sockets.push(this) }
    open() { this.readyState = 1; event(this, 'open') }
    send(text) { this.sent.push(JSON.parse(text)) }
    close() { this.readyState = 3 }
    remoteClose(code) { this.readyState = 3; event(this, 'close', { code }) }
    message(data) { event(this, 'message', { data }) }
  }
  const session = createMsePreviewSession({
    video, visible, url: '/api/cameras/camera_1/preview/ws?feature=tailgating',
    cameraKey: 'camera_1', feature: 'tailgating', department: 'general_electric', ...context,
    onState: (state) => states.push(state), onReport: (report) => reports.push(report),
    onFallback: () => fallbacks++, onAccessDenied: () => denied++,
    environment: {
      origin: 'https://preview.invalid', now: () => clock,
      createMediaSource: () => new FakeMediaSource(),
      createWebSocket: (url) => new FakeSocket(url),
      isTypeSupported,
      createObjectURL: () => `blob:preview-${mediaSources.length}`,
      revokeObjectURL: (url) => revoked.push(url),
      setTimeoutFn(callback, delay) {
        const id = ++sequence
        timers.set(id, { callback, at: clock + delay })
        return id
      },
      clearTimeoutFn: (id) => timers.delete(id),
    },
  })
  return {
    session, video, timers, states, reports, sockets, mediaSources, revoked,
    fallbacks: () => fallbacks, denied: () => denied,
    advance(to) {
      while (true) {
        const next = [...timers].sort(([, a], [, b]) => a.at - b.at)[0]
        if (!next || next[1].at > to) break
        const [id, timer] = next
        timers.delete(id)
        clock = timer.at
        timer.callback()
      }
      clock = to
    },
    negotiate() {
      const media = mediaSources.at(-1)
      const socket = sockets.at(-1)
      media.open()
      socket.open()
      socket.message(JSON.stringify({ type: 'mse', value: mime }))
      return { media, socket, buffer: media.sourceBuffers[0] }
    },
  }
}

test('只协商浏览器支持的视频编码，媒体 WebSocket 限制同源且拒绝 URL 凭据', () => {
  const codecs = supportedPreviewCodecs((value) => value.includes('hvc1'))
  assert.equal(codecs, 'hvc1.1.6.L153.B0')
  assert.equal(supportedPreviewCodecs(() => false), '')
  assert.equal(previewWebSocketUrl('/api/preview/ws', 'https://preview.invalid'), 'wss://preview.invalid/api/preview/ws')
  for (const path of ['https://other.invalid/api', 'wss://user:password@preview.invalid/api', 'ws://preview.invalid/api']) {
    assert.throws(() => previewWebSocketUrl(path, 'https://preview.invalid'))
  }
})

test('协商解析拒绝无效 JSON、未知类型和非视频 MIME，不把 error 文本当视频格式', () => {
  assert.deepEqual(parseMseControlMessage(JSON.stringify({ type: 'mse', value: mime })), { type: 'mse', value: mime })
  assert.equal(parseMseControlMessage('{"type":"error","value":"无权访问"}').type, 'error')
  for (const message of ['{', '{}', 'null', '{"type":"mse","value":"text/html"}', '{"type":"mse","value":5}']) {
    assert.throws(() => parseMseControlMessage(message))
  }
})

test('追加与清理缓冲串行执行，追到直播边缘并保留约五秒窗口', () => {
  const buffer = new FakeBuffer()
  const video = new FakeVideo()
  buffer.buffered = ranges([[0, 10]])
  const queue = createMseAppendQueue({ buffer, video, onFailure() { assert.fail('有效缓冲不应失败') } })
  queue.append(new ArrayBuffer(3))
  queue.append(new ArrayBuffer(4))
  assert.deepEqual(buffer.operations, [{ remove: [0, 5] }])
  assert.equal(video.currentTime, 9.85)
  buffer.finish([[5, 10]])
  assert.deepEqual(buffer.operations.at(-1), { append: 3 })
  buffer.finish()
  assert.deepEqual(buffer.operations.at(-1), { append: 4 })
  queue.dispose()
  buffer.finish()
  assert.equal(buffer.operations.length, 3)
})

test('待追加字节包含正在追加的数据，溢出时报告失败且不丢片段继续播放', () => {
  const buffer = new FakeBuffer()
  let failed = 0
  const queue = createMseAppendQueue({ buffer, video: new FakeVideo(), maxPendingBytes: 5, onFailure() { failed++ } })
  queue.append(new ArrayBuffer(3))
  queue.append(new ArrayBuffer(3))
  queue.append(new ArrayBuffer(1))
  buffer.finish()
  assert.equal(failed, 1)
  assert.deepEqual(buffer.operations, [{ append: 3 }])
  queue.dispose()
})

test('SourceBuffer 拒绝追加或异常时间轴时失败，不能永远积压等待', () => {
  for (const invalid of ['quota', 'timeline']) {
    const buffer = new FakeBuffer()
    if (invalid === 'quota') buffer.appendBuffer = () => { throw new DOMException('full', 'QuotaExceededError') }
    else buffer.buffered = ranges([[10, 5]])
    let failed = 0
    const queue = createMseAppendQueue({ buffer, video: new FakeVideo(), onFailure() { failed++ } })
    queue.append(new ArrayBuffer(1))
    assert.equal(failed, 1)
    queue.dispose()
  }
})

test('等待 WebSocket 和 MediaSource 同时可用才发送唯一 mse 握手，播放前不宣称成功', () => {
  const state = setup()
  state.sockets[0].open()
  assert.equal(state.sockets[0].sent.length, 0)
  state.mediaSources[0].open()
  state.mediaSources[0].open()
  assert.equal(state.sockets[0].sent.length, 1)
  assert.equal(state.sockets[0].sent[0].type, 'mse')
  state.sockets[0].message(JSON.stringify({ type: 'mse', value: mime }))
  state.sockets[0].message(new ArrayBuffer(5))
  assert.equal(state.states.at(-1), 'connecting')
  event(state.video, 'playing')
  assert.equal(state.states.at(-1), 'playing')
  state.session.dispose()
  assert.equal(state.video.src, '')
  assert.equal(state.sockets[0].readyState, 3)
  assert.equal(state.timers.size, 0)
  assert.deepEqual(state.revoked, ['blob:preview-1'])
})

test('九秒收到数据但没有可播放画面时回退 JPEG，不能用收到字节冒充试播成功', () => {
  const state = setup()
  const { socket } = state.negotiate()
  socket.message(new ArrayBuffer(5))
  state.advance(8500)
  assert.equal(state.fallbacks(), 0)
  state.advance(9000)
  assert.equal(state.fallbacks(), 1)
  assert.equal(state.states.at(-1), 'fallback')
  assert.equal(state.video.src, '')
  assert.equal(state.timers.size, 0)
})

test('浏览器没有可用 MSE 视频编码时直接回退，不创建无法播放的连接', () => {
  const state = setup(true, () => false)
  assert.equal(state.fallbacks(), 1)
  assert.equal(state.sockets.length, 0)
  assert.equal(state.video.src, '')
  assert.equal(state.states.at(-1), 'fallback')
  assert.equal(state.timers.size, 0)
  state.session.dispose()
})

test('权限失效 1008 清空画面并终止，error 后的 1008 也不能先触发 JPEG 回退', () => {
  for (const withError of [false, true]) {
    const state = setup()
    const { socket } = state.negotiate()
    event(state.video, 'playing')
    if (withError) {
      for (const at of [5000, 10000]) {
        state.video.currentTime = at / 1000
        state.advance(at)
      }
      socket.message('{"type":"error","value":"当前账号无权查看"}')
      state.advance(10500)
    }
    assert.equal(state.fallbacks(), 0)
    socket.remoteClose(1008)
    assert.equal(state.denied(), 1)
    assert.equal(state.fallbacks(), 0)
    assert.equal(state.video.src, '')
    assert.equal(state.states.at(-1), 'access-denied')
    state.advance(20000)
    assert.equal(state.sockets.length, 1)
  }
})

test('普通断线和缓冲溢出重建初始化协商，旧连接的迟到事件不影响新画面', () => {
  for (const failure of ['disconnect', 'overflow']) {
    const state = setup()
    const { socket } = state.negotiate()
    event(state.video, 'playing')
    if (failure === 'disconnect') socket.remoteClose(1006)
    else socket.message(new ArrayBuffer(MSE_MAX_PENDING_BYTES + 1))
    assert.equal(state.states.at(-1), 'reconnecting')
    assert.equal(state.video.src, '')
    state.advance(500)
    assert.equal(state.sockets.length, 2)
    const current = state.negotiate()
    socket.message(new ArrayBuffer(3))
    socket.remoteClose(1008)
    assert.equal(state.denied(), 0)
    assert.equal(current.buffer.operations.length, 0)
    current.socket.message(new ArrayBuffer(2))
    assert.deepEqual(current.buffer.operations, [{ append: 2 }])
    state.session.dispose()
  }
})

test('页面隐藏或卸载清理连接和所有定时器，恢复后重新协商且旧 playing 无效', () => {
  const state = setup(false)
  assert.equal(state.sockets.length, 0)
  state.session.setVisible(true)
  state.negotiate()
  state.session.setVisible(false)
  assert.equal(state.states.at(-1), 'paused')
  assert.equal(state.timers.size, 0)
  assert.equal(state.video.src, '')
  event(state.video, 'playing')
  assert.equal(state.states.at(-1), 'paused')
  state.advance(20000)
  state.session.setVisible(true)
  assert.equal(state.sockets.length, 2)
  state.session.dispose()
  state.session.dispose()
  assert.equal(state.timers.size, 0)
  assert.equal(state.revoked.length, 2)
})

test('播放停滞会重连，恢复窗口不被最初九秒启动期限误截断', () => {
  const state = setup()
  state.negotiate()
  event(state.video, 'playing')
  state.video.currentTime = 1
  state.advance(500)
  state.video.currentTime = 2
  state.advance(5000)
  state.advance(14000)
  assert.equal(state.fallbacks(), 0)
  assert.equal(state.states.at(-1), 'reconnecting')
  state.advance(14500)
  assert.equal(state.sockets.length, 2)
  state.session.dispose()
})

test('视频性能扣除浏览器丢弃帧，隐藏后不累计暂停时长', () => {
  const state = setup()
  const { socket } = state.negotiate()
  event(state.video, 'playing')
  socket.message(new ArrayBuffer(2048))
  state.video.frames = 125
  state.video.dropped = 3
  state.video.buffered = ranges([[0, 5]])
  state.video.currentTime = 4
  state.advance(5000)
  const report = state.reports[0]
  assert.equal(report.mode, 'mse')
  assert.equal(report.videoFps, 24.4)
  assert.equal(report.droppedVideoFrames, 3)
  assert.equal(report.receivedKiB, 2)
  assert.equal(report.bufferedSeconds, 1)
  assert.equal(report.videoWidth, 1920)
  assert.equal(report.state, 'playing')
  state.session.setVisible(false)
  state.advance(20000)
  state.session.setVisible(true)
  state.video.frames += 25
  state.advance(25000)
  assert.equal(state.reports.at(-1).windowMs, 5000)
  assert.equal(state.reports.at(-1).videoFps, 5)
  state.session.dispose()
})

test('浏览器没有帧计数或媒体源重置计数时帧率为空，不能输出负数或伪造零帧率', () => {
  let at = 0
  const video = new FakeVideo()
  video.frames = 100
  const reports = []
  const recorder = createVideoPreviewPerformanceRecorder({
    video, cameraKey: 'camera_1', feature: 'tailgating', department: 'general_electric',
    now: () => at, onReport: (report) => reports.push(report),
  })
  video.frames = 1
  at = 5000
  recorder.sample('connecting')
  assert.equal(reports[0].videoFps, null)
  video.getVideoPlaybackQuality = undefined
  at = 10000
  recorder.sample('connecting')
  assert.equal(reports[1].videoFps, null)
  assert.equal(reports[1].droppedVideoFrames, null)
})

test('三路视频同时统计时逐路保留报告，不互相覆盖且尚未采样的成员为空', () => {
  const reports = []
  const group = createVideoPreviewPerformanceGroup({
    siteId: 1, department: 'general_electric', onReport: (report) => reports.push(report),
  })
  const keys = ['camera_63', 'camera_64', 'camera_65']
  group.publish()
  group.setCameras(keys)
  assert.deepEqual(reports.at(-1).cameras, { camera_63: null, camera_64: null, camera_65: null })
  for (const cameraKey of keys) {
    const state = setup(true, undefined, { cameraKey, feature: 'guard_behavior' })
    const { socket } = state.negotiate()
    event(state.video, 'playing')
    socket.message(new ArrayBuffer(1024))
    state.video.frames = 125
    state.video.currentTime = 4.9
    state.advance(5000)
    group.update(state.reports[0])
    state.session.dispose()
  }
  assert.equal(reports.at(-1).scope, 'guard_behavior')
  assert.equal(reports.at(-1).siteId, 1)
  assert.deepEqual(Object.keys(reports.at(-1).cameras), keys)
  for (const cameraKey of keys) {
    assert.equal(reports.at(-1).cameras[cameraKey].cameraKey, cameraKey)
    assert.equal(reports.at(-1).cameras[cameraKey].videoFps, 25)
    assert.equal(reports.at(-1).cameras[cameraKey].receivedKiB, 1)
  }
  group.dispose()
})

test('视频分组拒绝其他事业部、功能、已移除成员和超过三路的报告', () => {
  const state = setup(true, undefined, { cameraKey: 'camera_63', feature: 'guard_behavior' })
  state.negotiate()
  event(state.video, 'playing')
  state.video.frames = 125
  state.video.currentTime = 4.9
  state.advance(5000)
  const report = state.reports[0]
  const reports = []
  const group = createVideoPreviewPerformanceGroup({
    siteId: 1, department: 'general_electric', onReport: (value) => reports.push(value),
  })
  group.setCameras(['camera_63', 'camera_64', 'camera_63', 'camera_65', 'camera_66'])
  const baseline = reports.length
  group.update({ ...report, department: 'electrical_components' })
  group.update({ ...report, feature: 'security_fence' })
  group.update({ ...report, cameraKey: 'camera_66' })
  assert.equal(reports.length, baseline)
  group.update(report)
  const prior = reports.at(-1)
  group.setCameras(['camera_64', 'camera_65'])
  group.update(report)
  assert.deepEqual(reports.at(-1).cameras, { camera_64: null, camera_65: null })
  assert.equal(prior.cameras.camera_63, report)
  group.dispose()
  state.session.dispose()
})

test('视频组重置采样后恢复为空，已结束的站点会话不能再发布迟到结果', () => {
  const reports = []
  const group = createVideoPreviewPerformanceGroup({
    siteId: 1, department: 'general_electric', onReport: (report) => reports.push(report),
  })
  group.setCameras(['camera_63'])
  group.update({ cameraKey: 'camera_63', feature: 'guard_behavior', department: 'general_electric' })
  assert.notEqual(reports.at(-1).cameras.camera_63, null)
  group.reset()
  assert.equal(reports.at(-1).cameras.camera_63, null)
  const count = reports.length
  group.dispose()
  group.publish()
  group.setCameras(['camera_64'])
  group.update({ cameraKey: 'camera_63', feature: 'guard_behavior', department: 'general_electric' })
  group.reset()
  assert.equal(reports.length, count)
})

test('离线或停用成员保留空键，别路刷新和该路迟到结果不能恢复旧播放帧率', () => {
  const reports = []
  const group = createVideoPreviewPerformanceGroup({
    siteId: 1, department: 'general_electric', onReport: (report) => reports.push(report),
  })
  const report = (cameraKey) => ({ cameraKey, feature: 'guard_behavior', department: 'general_electric', state: 'playing', videoFps: 25 })
  const keys = ['camera_63', 'camera_64', 'camera_65']
  group.setCameras(keys)
  for (const key of keys) group.update(report(key))
  group.setCameras(keys, ['camera_64'])
  assert.deepEqual(Object.keys(reports.at(-1).cameras), keys)
  assert.equal(reports.at(-1).cameras.camera_63, null)
  assert.equal(reports.at(-1).cameras.camera_65, null)
  group.update(report('camera_64'))
  group.update(report('camera_63'))
  group.update(report('camera_65'))
  assert.equal(reports.at(-1).cameras.camera_63, null)
  assert.equal(reports.at(-1).cameras.camera_65, null)
  assert.equal(reports.at(-1).cameras.camera_64.videoFps, 25)
  group.setCameras(keys)
  assert.equal(reports.at(-1).cameras.camera_63, null)
  group.update(report('camera_63'))
  assert.equal(reports.at(-1).cameras.camera_63.videoFps, 25)
  group.setCameras(['camera_64'])
  assert.deepEqual(Object.keys(reports.at(-1).cameras), ['camera_64'])
  group.dispose()
})

test('多路播放器只通过父回调上报，不覆盖或清理聚合的全局报告', async (t) => {
  const previous = { window: globalThis.window, document: globalThis.document }
  const group = { scope: 'guard_behavior', cameras: { camera_63: null, camera_64: null, camera_65: null } }
  globalThis.window = { aivisionVideoPreviewDiagnostics: group }
  const document = Object.assign(new EventTarget(), { hidden: false })
  globalThis.document = document
  const symbol = Symbol.for('aivision.video-component-test')
  const oldRuntime = globalThis[symbol]
  const effects = []
  const got = []
  let call = 0
  let sessionOptions
  globalThis[symbol] = {
    useRef(initial) { return { current: call++ === 0 ? new FakeVideo() : initial } },
    useState() { return [null, () => undefined] },
    useEffect(effect) { effects.push(effect) },
    createMsePreviewSession(options) { sessionOptions = options; return { setVisible() {}, dispose() {} } },
  }
  t.after(() => {
    globalThis.window = previous.window
    globalThis.document = previous.document
    if (oldRuntime === undefined) delete globalThis[symbol]
    else globalThis[symbol] = oldRuntime
  })
  const data = (source) => `data:text/javascript;base64,${Buffer.from(source).toString('base64')}`
  const react = data(`const runtime=()=>globalThis[Symbol.for('aivision.video-component-test')];
    export const useRef=(...args)=>runtime().useRef(...args);
    export const useState=(...args)=>runtime().useState(...args);
    export const useEffect=(...args)=>runtime().useEffect(...args);`)
  const jsx = data('export const jsx=(type,props)=>({type,props});export const jsxs=jsx;')
  const mse = data(`export const createMsePreviewSession=(options)=>globalThis[Symbol.for('aivision.video-component-test')].createMsePreviewSession(options);`)
  const source = await readFile(new URL('../src/components/AiVisionVideoPreview.tsx', import.meta.url), 'utf8')
  const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  }).outputText.replace('"react/jsx-runtime"', JSON.stringify(jsx))
    .replace("'react'", JSON.stringify(react)).replace("'./AiVisionVideoPreview.mse'", JSON.stringify(mse))
  const { AiVisionVideoPreview } = await import(data(compiled))
  AiVisionVideoPreview({
    url: '/ws/cameras/camera_63/preview?feature=guard_behavior', cameraKey: 'camera_63',
    feature: 'guard_behavior', department: 'general_electric', onPerformanceReport: (report) => got.push(report),
  })
  const cleanups = effects.map((effect) => effect()).filter(Boolean)
  const report = { cameraKey: 'camera_63', mode: 'mse', videoFps: 25 }
  sessionOptions.onReport(report)
  assert.deepEqual(got, [report])
  assert.equal(window.aivisionVideoPreviewDiagnostics, group)
  document.hidden = true
  event(document, 'visibilitychange')
  assert.equal(window.aivisionVideoPreviewDiagnostics, group)
  for (const cleanup of cleanups.reverse()) cleanup()
  assert.equal(window.aivisionVideoPreviewDiagnostics, group)
  sessionOptions.onReport({ ...report, videoFps: 20 })
  assert.equal(got.length, 1)
})

test('Guard 卡片按能力门控 MSE 与 JPEG，拒绝访问及隐藏时不再取图', async (t) => {
  const symbol = Symbol.for('aivision.guard-video-test')
  const previous = { document: globalThis.document, fetch: globalThis.fetch, runtime: globalThis[symbol] }
  const document = Object.assign(new EventTarget(), { hidden: false, visibilityState: 'visible' })
  globalThis.document = document
  let fetches = 0
  globalThis.fetch = async () => { fetches++; return new Response(new Blob(['jpeg'])) }
  const slots = []
  const pending = new Map()
  let cursor = 0
  let mode = 'mse'
  let fallbackReason = ''
  let poll
  let bufferDisposals = 0
  let capabilityEnabled
  const different = (left, right) => !left || left.length !== right.length || left.some((value, index) => !Object.is(value, right[index]))
  const runtime = {
    useState(initial) {
      const index = cursor++
      slots[index] ??= { value: typeof initial === 'function' ? initial() : initial }
      return [slots[index].value, (value) => { slots[index].value = typeof value === 'function' ? value(slots[index].value) : value }]
    },
    useRef(initial) { const index = cursor++; return slots[index] ??= { current: initial } },
    useMemo(factory, dependencies) {
      const index = cursor++
      if (!slots[index] || different(slots[index].dependencies, dependencies)) slots[index] = { value: factory(), dependencies }
      return slots[index].value
    },
    useEffect(effect, dependencies) {
      const index = cursor++
      const slot = slots[index] ??= {}
      if (different(slot.dependencies, dependencies)) { slot.dependencies = dependencies; pending.set(index, effect) }
    },
    useCameraVideoPreview(options) {
      capabilityEnabled = options.enabled
      return { mode: options.enabled ? mode : 'jpeg', url: '/ws/cameras/camera_63/preview?feature=guard_behavior', fallbackReason,
        onFallback() { mode = 'jpeg'; fallbackReason = '视频试播未连接，显示 JPEG 画面' },
        onAccessDenied() { mode = 'denied' } }
    },
    useSerialPoll(task, options) { poll = { task, options } },
    createPreviewFrameBuffer() {
      return { prepare: async () => 'blob:guard-frame', displayed() {}, dispose() { bufferDisposals++ }, clear() {} }
    },
  }
  globalThis[symbol] = runtime
  t.after(() => {
    for (const slot of slots) slot.cleanup?.()
    globalThis.document = previous.document
    globalThis.fetch = previous.fetch
    if (previous.runtime === undefined) delete globalThis[symbol]
    else globalThis[symbol] = previous.runtime
  })
  const data = (source) => `data:text/javascript;base64,${Buffer.from(source).toString('base64')}`
  const react = data(`const runtime=()=>globalThis[Symbol.for('aivision.guard-video-test')];
    export const useState=(...args)=>runtime().useState(...args);export const useRef=(...args)=>runtime().useRef(...args);
    export const useMemo=(...args)=>runtime().useMemo(...args);export const useEffect=(...args)=>runtime().useEffect(...args);`)
  const jsx = data('export const jsx=(type,props)=>({type,props});export const jsxs=jsx;')
  const stubs = data(`const runtime=()=>globalThis[Symbol.for('aivision.guard-video-test')];
    export const useSerialPoll=(...args)=>runtime().useSerialPoll(...args);
    export const useCameraVideoPreview=(...args)=>runtime().useCameraVideoPreview(...args);
    export const createPreviewFrameBuffer=()=>runtime().createPreviewFrameBuffer();
    export const createPreviewPerformanceRecorder=()=>({dispose(){},completed(){},failed(){},displayed(){}});
    export const aiVisionFrameUrl=(key,feature)=>'/api/cameras/'+key+'/frame.jpg?feature='+feature;
    export function AiVisionVideoPreview(){};export function GuardVideoStatusPill(){};`)
  const source = await readFile(new URL('../src/components/guard_behavior/GuardCameraPreview.tsx', import.meta.url), 'utf8')
  const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  }).outputText.replace('"react/jsx-runtime"', JSON.stringify(jsx)).replace("'react'", JSON.stringify(react))
    .replace(/from '(?:@\/hooks\/use-serial-poll|@\/lib\/aivision|\.\.\/AiVisionMonitor\.frame|\.\.\/AiVisionMonitor\.performance|\.\.\/AiVisionVideoPreview|\.\.\/useCameraVideoPreview|\.\/GuardMonitorUi)'/g, `from ${JSON.stringify(stubs)}`)
  const { GuardCameraPreview } = await import(data(compiled))
  const props = { member: { id: 1, camera_id: 63, shm_name: 'camera_63', name: '保安入口', department: 'general_electric', physical_enabled: true }, online: true, aiReady: true }
  const render = () => {
    cursor = 0
    const tree = GuardCameraPreview(props)
    for (const [index, effect] of pending) { slots[index].cleanup?.(); slots[index].cleanup = effect() }
    pending.clear()
    return tree
  }
  const nodes = (tree) => !tree || typeof tree !== 'object' ? []
    : [tree, ...[tree.props?.children ?? []].flat().flatMap(nodes)]
  const video = (tree) => nodes(tree).find((node) => node.type?.name === 'AiVisionVideoPreview')
  let tree = render()
  assert.equal(capabilityEnabled, true)
  assert.ok(video(tree))
  assert.equal(poll.options.enabled, false)
  await poll.task(new AbortController().signal)
  assert.equal(fetches, 0)
  video(tree).props.onFallback()
  tree = render()
  assert.equal(video(tree), undefined)
  assert.equal(poll.options.enabled, true)
  assert.equal(poll.options.intervalMs, 500)
  assert.equal(poll.options.intervalMode, 'from-start')
  await poll.task(new AbortController().signal)
  tree = render()
  assert.equal(fetches, 1)
  assert.ok(nodes(tree).find((node) => node.type === 'img'))
  assert.ok(nodes(tree).find((node) => node.type?.name === 'GuardVideoStatusPill').props.label.includes('JPEG 回退'))
  mode = 'denied'
  tree = render()
  assert.equal(poll.options.enabled, false)
  assert.equal(nodes(tree).some((node) => node.type === 'img'), false)
  assert.ok(bufferDisposals > 0)
  mode = 'mse'
  tree = render()
  video(tree).props.onAccessDenied()
  tree = render()
  assert.equal(video(tree), undefined)
  assert.equal(poll.options.enabled, false)
  document.hidden = true
  document.visibilityState = 'hidden'
  event(document, 'visibilitychange')
  render()
  assert.equal(capabilityEnabled, false)
  assert.equal(poll.options.enabled, false)
  assert.equal(fetches, 1)
})
