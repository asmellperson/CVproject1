import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { test } from 'node:test'
import ts from 'typescript'

// 复用项目 TypeScript 编译器在内存中运行状态逻辑，不写入临时编译文件。
const source = await readFile(new URL('../src/components/security_fence/statusState.ts', import.meta.url), 'utf8')
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } })
const { receiveFenceStatus, failFenceStatus, expireFenceStatus } = await import(
  `data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`
)

function snapshot(overrides = {}) {
  return {
    camera_key: 'camera_1', state: 'ready', mode: 'whitelist', timezone: 'Asia/Shanghai', online: true,
    count: 2, pending_count: 1, alarm: false, persons: [{ track_id: 1, identity: 'pending' }],
    updated_at: '2026-10-24T00:00:00+00:00', valid_for_seconds: 4.9, error: null, ...overrides,
  }
}

test('浏览器时钟偏差不会清空检测状态、当前规则、区域人数和待核验人数', (t) => {
  const value = snapshot()
  for (const offset of [-600_000, 600_000]) {
    const clock = t.mock.method(Date, 'now', () => Date.parse(value.updated_at) + offset)
    const result = receiveFenceStatus(null, value, 1000, 1300)
    assert.equal(result.value.state, 'ready')
    assert.equal(result.value.mode, 'whitelist')
    assert.equal(result.value.count, 2)
    assert.equal(result.value.pending_count, 1)
    assert.equal(result.expiresAt, 5900)
    clock.mock.restore()
  }
})

test('连续轮询相同快照时四个状态值保持有效，截止时间不顺延', () => {
  let result = null
  for (let startedAt = 0; startedAt <= 4000; startedAt += 500) {
    result = receiveFenceStatus(result, snapshot({ valid_for_seconds: (4900 - startedAt) / 1000 }), startedAt, startedAt + 100)
    assert.equal(result.value.state, 'ready')
    assert.equal(result.value.mode, 'whitelist')
    assert.equal(result.value.count, 2)
    assert.equal(result.value.pending_count, 1)
    assert.equal(result.expiresAt, 4900)
  }
})

test('传输途中失效的结果不先显示再被计时器清空', () => {
  for (const valid_for_seconds of [0, .3, -1, NaN, Infinity, undefined]) {
    const result = receiveFenceStatus(null, snapshot({ valid_for_seconds }), 1000, 1300)
    assert.equal(result.value, null)
    assert.equal(result.expiresAt, null)
    assert.match(result.error, /过期/)
  }
})

test('短暂请求失败保留四个有效统计值，恢复后清除通信错误', () => {
  const first = receiveFenceStatus(null, snapshot(), 1000, 1100)
  const failed = failFenceStatus(first, 'camera_1', '网络错误', 1800)
  assert.equal(failed.value, first.value)
  assert.equal(failed.expiresAt, first.expiresAt)
  assert.equal(failed.error, '网络错误')
  const recovered = receiveFenceStatus(failed, snapshot({ valid_for_seconds: 3.9 }), 2000, 2100)
  assert.equal(recovered.value.count, 2)
  assert.equal(recovered.value.pending_count, 1)
  assert.equal(recovered.error, '')
})

test('重复快照不能延长有效期，新检测结果可以正常续期', () => {
  const first = receiveFenceStatus(null, snapshot(), 1000, 1100)
  const repeated = receiveFenceStatus(first, snapshot(), 2000, 2100)
  assert.equal(repeated.expiresAt, first.expiresAt)
  const updated = receiveFenceStatus(repeated, snapshot({ updated_at: '2026-10-24T00:00:01+00:00' }), 2500, 2600)
  assert.equal(updated.expiresAt, 7400)
})

test('真正到期或持续请求失败时清除旧判定', () => {
  const first = receiveFenceStatus(null, snapshot(), 1000, 1100)
  const failed = failFenceStatus(first, 'camera_1', '网络错误', 5900)
  assert.equal(failed.value, null)
  const expired = expireFenceStatus(first)
  assert.equal(expired.value, null)
  assert.equal(expired.expiresAt, null)
  assert.match(expired.error, /过期/)
})

test('切换摄像头不保留上一台的值或截止时间', () => {
  const first = receiveFenceStatus(null, snapshot(), 1000, 1100)
  const failed = failFenceStatus(first, 'camera_2', '网络错误', 1200)
  assert.equal(failed.key, 'camera_2')
  assert.equal(failed.value, null)
  const switched = receiveFenceStatus(first, snapshot({ camera_key: 'camera_2' }), 1500, 1600)
  assert.equal(switched.key, 'camera_2')
  assert.equal(switched.expiresAt, 6400)
})

test('停用、离线、等待和后端过期状态立即替换已缓存的正常判定', () => {
  const first = receiveFenceStatus(null, snapshot(), 1000, 1100)
  for (const state of ['disabled', 'offline', 'waiting', 'stale']) {
    const result = receiveFenceStatus(first, snapshot({ state, count: null, pending_count: null, valid_for_seconds: 0 }), 1500, 1600)
    assert.equal(result.value.state, state)
    assert.equal(result.value.count, null)
    assert.equal(result.value.pending_count, null)
    assert.equal(result.expiresAt, null)
  }
})

test('推理异常保留后端的具体错误和未知人数，不显示为正常放行', () => {
  const result = receiveFenceStatus(null, snapshot({ state: 'error', error: '人体检测不可用', count: null, alarm: null }), 1000, 1100)
  assert.equal(result.value.state, 'error')
  assert.equal(result.value.error, '人体检测不可用')
  assert.equal(result.value.count, null)
  assert.equal(result.value.alarm, null)
  assert.equal(result.expiresAt, 5900)
})
