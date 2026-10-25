import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { test } from 'node:test'
import ts from 'typescript'

async function compile(path) {
  const source = await readFile(new URL(`../src/${path}.ts`, import.meta.url), 'utf8')
  return ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  }).outputText
}
const dataUrl = (source) => `data:text/javascript;base64,${Buffer.from(source).toString('base64')}`
const apiUrl = dataUrl(await compile('lib/preview-stream'))
const { getCameraPreviewStream, PreviewStreamAccessError } = await import(apiUrl)
// 使用可提交/清理 effect 的最小 hooks 容器，直接执行正式 hook 的异步与会话逻辑。
const hooksUrl = dataUrl(`
const runtime = () => globalThis[Symbol.for('aivision.preview-hooks-test')];
export const useMemo = (...args) => runtime().useMemo(...args);
export const useState = (...args) => runtime().useState(...args);
export const useEffect = (...args) => runtime().useEffect(...args);
export const useCallback = (...args) => runtime().useMemo(() => args[0], args[1]);
`)
const hookCode = (await compile('components/useCameraVideoPreview'))
  .replace("'react'", JSON.stringify(hooksUrl))
  .replace("'../lib/preview-stream'", JSON.stringify(apiUrl))
const { useCameraVideoPreview } = await import(dataUrl(hookCode))

const baseContext = { cameraKey: 'camera_1', feature: 'security_fence', department: 'general_electric', enabled: true }
const fallbackReason = '视频试播未连接，显示 JPEG 画面'
const capability = (camera = 'camera_1') => ({
  enabled: true, mode: 'mse', url: `/ws/cameras/${camera}/preview?feature=security_fence`, raw: true,
})
const disabled = { enabled: false, mode: 'jpeg', url: null, raw: true }
const json = (value, status = 200) => new Response(JSON.stringify(value), { status })
const deferred = () => {
  let resolve
  const promise = new Promise((finish) => { resolve = finish })
  return { promise, resolve }
}
async function settle() { for (let index = 0; index < 12; index++) await Promise.resolve() }

function environment(t) {
  const symbol = Symbol.for('aivision.preview-hooks-test')
  const previous = { window: globalThis.window, fetch: globalThis.fetch, hooks: globalThis[symbol] }
  const window = Object.assign(new EventTarget(), { location: { origin: 'https://preview.invalid' } })
  globalThis.window = window
  t.after(() => {
    globalThis.window = previous.window
    globalThis.fetch = previous.fetch
    if (previous.hooks === undefined) delete globalThis[symbol]
    else globalThis[symbol] = previous.hooks
  })
  return window
}

function hookHarness(t, initial = baseContext) {
  const symbol = Symbol.for('aivision.preview-hooks-test')
  const slots = []
  const pending = new Map()
  let cursor = 0
  let context = initial
  const changed = (first, second) => !first || first.length !== second.length || first.some((value, index) => !Object.is(value, second[index]))
  const runtime = {
    useMemo(factory, dependencies) {
      const index = cursor++
      if (!slots[index] || changed(slots[index].dependencies, dependencies)) {
        slots[index] = { value: factory(), dependencies }
      }
      return slots[index].value
    },
    useState(initialValue) {
      const index = cursor++
      if (!slots[index]) slots[index] = { value: initialValue }
      return [slots[index].value, (next) => {
        slots[index].value = typeof next === 'function' ? next(slots[index].value) : next
      }]
    },
    useEffect(effect, dependencies) {
      const index = cursor++
      const slot = slots[index] ??= {}
      if (changed(slot.dependencies, dependencies)) {
        slot.dependencies = dependencies
        pending.set(index, effect)
      }
    },
  }
  globalThis[symbol] = runtime
  const commit = () => {
    for (const [index, effect] of pending) {
      slots[index].cleanup?.()
      slots[index].cleanup = effect()
    }
    pending.clear()
  }
  t.after(() => {
    for (const slot of slots) slot.cleanup?.()
  })
  return {
    render(next = context, commitEffects = true) {
      context = next
      cursor = 0
      const result = useCameraVideoPreview(context)
      if (commitEffects) commit()
      return result
    },
    commit,
  }
}

test('能力查询携带登录凭证、取消信号和功能，仅接收同源正式视频路径', async (t) => {
  environment(t)
  let requested
  globalThis.fetch = async (url, options) => { requested = { url, options }; return json(capability()) }
  assert.deepEqual(await getCameraPreviewStream('camera_1', 'security_fence'), capability())
  assert.equal(requested.url, '/api/cameras/camera_1/preview?feature=security_fence')
  assert.equal(requested.options.credentials, 'include')
  assert.equal(requested.options.cache, 'no-store')
  assert.ok(requested.options.signal instanceof AbortSignal)
  globalThis.fetch = async () => json(capability())
  assert.deepEqual(await getCameraPreviewStream('1', 'security_fence'), capability())
  globalThis.fetch = async () => json(disabled)
  assert.deepEqual(await getCameraPreviewStream('camera_1', 'security_fence'), disabled)
})

test('异源、凭据、其他摄像头、功能串用和无效协议响应都不能进入视频播放', async (t) => {
  environment(t)
  const invalid = [
    { ...capability(), url: 'https://other.invalid/ws/cameras/camera_1/preview?feature=security_fence' },
    { ...capability(), url: 'https://user:password@preview.invalid/ws/cameras/camera_1/preview?feature=security_fence' },
    capability('camera_2'),
    { ...capability(), url: '/ws/cameras/camera_1/preview?feature=tailgating' },
    { ...capability(), url: '/ws/cameras/camera_1/preview?feature=security_fence&token=unused' },
    { ...capability(), url: '/ws/cameras/camera_1/preview?feature=security_fence&feature=security_fence' },
    { ...capability(), url: '/ws/cameras/camera_1/preview?feature=security_fence#fragment' },
    { ...capability(), mode: 'jpeg' }, { ...capability(), raw: false }, null,
  ]
  for (const value of invalid) {
    globalThis.fetch = async () => json(value)
    await assert.rejects(getCameraPreviewStream('camera_1', 'security_fence'), Error)
  }
})

test('401/403 保留权限错误身份，只有 401 触发平台已有未登录事件', async (t) => {
  const window = environment(t)
  let unauthorized = 0
  window.addEventListener('aicv:unauthorized', () => unauthorized++)
  for (const status of [401, 403]) {
    globalThis.fetch = async () => json({ detail: 'denied' }, status)
    await assert.rejects(getCameraPreviewStream('camera_1', 'security_fence'), (error) => {
      assert.ok(error instanceof PreviewStreamAccessError)
      return error.status === status
    })
  }
  assert.equal(unauthorized, 1)
})

test('超时涵盖网络和响应体等待，即使 fetch 未响应取消也按时结束', async (t) => {
  environment(t)
  for (const stalled of ['headers', 'body']) {
    let signal
    globalThis.fetch = async (_, options) => {
      signal = options.signal
      if (stalled === 'headers') return new Promise(() => undefined)
      return { ok: true, status: 200, json: () => new Promise(() => undefined) }
    }
    await assert.rejects(getCameraPreviewStream('camera_1', 'security_fence', { timeoutMs: 10 }), { name: 'TimeoutError' })
    assert.equal(signal.aborted, true)
  }
})

test('取消旧请求后迟到的 401 不触发全站退出，已取消请求也不继续发起网络访问', async (t) => {
  const window = environment(t)
  let unauthorized = 0
  window.addEventListener('aicv:unauthorized', () => unauthorized++)
  const late = deferred()
  let requests = 0
  globalThis.fetch = async () => { requests++; return late.promise }
  const controller = new AbortController()
  const request = getCameraPreviewStream('camera_1', 'security_fence', { signal: controller.signal })
  controller.abort()
  await assert.rejects(request, { name: 'AbortError' })
  late.resolve(json({ detail: 'denied' }, 401))
  await settle()
  await assert.rejects(getCameraPreviewStream('camera_1', 'security_fence', { signal: controller.signal }), { name: 'AbortError' })
  assert.equal(unauthorized, 0)
  assert.equal(requests, 1)
})

test('hook 首次检查能力，未启用静默使用 JPEG，启用后才提供视频地址', async (t) => {
  environment(t)
  for (const configured of [disabled, capability()]) {
    globalThis.fetch = async () => json(configured)
    const hook = hookHarness(t)
    assert.equal(hook.render().mode, 'checking')
    await settle()
    const value = hook.render()
    assert.equal(value.mode, configured.enabled ? 'mse' : 'jpeg')
    assert.equal(value.url, configured.url)
    assert.equal(value.fallbackReason, '')
  }
})

test('hook 把权限拒绝保留为 denied，不能当作网络失败启动 JPEG', async (t) => {
  environment(t)
  for (const status of [401, 403]) {
    globalThis.fetch = async () => json({}, status)
    const hook = hookHarness(t)
    hook.render()
    await settle()
    const value = hook.render()
    assert.equal(value.mode, 'denied')
    assert.equal(value.url, null)
    value.onFallback()
    assert.equal(hook.render().mode, 'denied')
  }
})

test('hook 仅在网络、超时和协议错误时显示固定 JPEG 回退原因', async (t) => {
  environment(t)
  for (const failure of [new TypeError('network'), new DOMException('timeout', 'TimeoutError'), 'invalid']) {
    globalThis.fetch = async () => { if (failure === 'invalid') return json({ ...capability(), raw: false }); throw failure }
    const hook = hookHarness(t)
    hook.render()
    await settle()
    const value = hook.render()
    assert.equal(value.mode, 'jpeg')
    assert.equal(value.url, null)
    assert.equal(value.fallbackReason, fallbackReason)
  }
})

test('切换上下文立即隐藏旧地址，旧播放器回调不能覆盖下一摄像头能力结果', async (t) => {
  environment(t)
  const pending = []
  globalThis.fetch = (_, options) => { const request = deferred(); pending.push({ ...request, signal: options.signal }); return request.promise }
  const hook = hookHarness(t)
  hook.render()
  pending[0].resolve(json(capability()))
  await settle()
  const old = hook.render()
  assert.equal(old.mode, 'mse')
  const next = { ...baseContext, cameraKey: 'camera_2' }
  const checking = hook.render(next, false)
  assert.equal(checking.mode, 'checking')
  assert.equal(checking.url, null)
  old.onFallback()
  old.onAccessDenied()
  assert.equal(hook.render(next, false).mode, 'checking')
  hook.commit()
  pending[1].resolve(json(capability('camera_2')))
  await settle()
  assert.equal(hook.render().mode, 'mse')
  old.onFallback()
  old.onAccessDenied()
  assert.equal(hook.render().url, capability('camera_2').url)
  const current = hook.render()
  current.onFallback()
  assert.equal(hook.render().mode, 'jpeg')
  assert.equal(hook.render().fallbackReason, fallbackReason)
})

test('旧能力响应迟到和部门切换不串会话，隐藏取消请求且恢复重新查询', async (t) => {
  const window = environment(t)
  let unauthorized = 0
  window.addEventListener('aicv:unauthorized', () => unauthorized++)
  const pending = []
  globalThis.fetch = (_, options) => { const request = deferred(); pending.push({ ...request, signal: options.signal }); return request.promise }
  const hook = hookHarness(t)
  hook.render()
  const next = { ...baseContext, department: 'electronics_electrician' }
  assert.equal(hook.render(next).mode, 'checking')
  assert.equal(pending[0].signal.aborted, true)
  pending[0].resolve(json({}, 401))
  pending[1].resolve(json(capability()))
  await settle()
  const old = hook.render()
  assert.equal(old.mode, 'mse')
  assert.equal(unauthorized, 0)
  const hidden = hook.render({ ...next, enabled: false })
  assert.equal(hidden.url, null)
  assert.equal(pending.length, 2)
  assert.equal(hook.render(next).mode, 'checking')
  assert.equal(pending.length, 3)
  hook.render({ ...next, enabled: false })
  assert.equal(pending[2].signal.aborted, true)
  pending[2].resolve(json(capability()))
  await settle()
  assert.equal(hook.render().url, null)
  hook.render(next)
  pending[3].resolve(json(capability()))
  await settle()
  old.onAccessDenied()
  assert.equal(hook.render().mode, 'mse')
  const current = hook.render()
  current.onAccessDenied()
  assert.equal(hook.render().mode, 'denied')
  assert.equal(hook.render().url, null)
})
