import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { test } from 'node:test'
import ts from 'typescript'

// 复用项目已有 TypeScript 编译器，在内存中运行状态逻辑，不生成临时编译产物。
const source = await readFile(new URL('../src/components/tailgating/statusState.ts', import.meta.url), 'utf8')
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } })
const { receiveTailgatingStatus, failTailgatingStatus, expireTailgatingStatus } = await import(
  `data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`
)

function snapshot(overrides = {}) {
  return {
    camera_key: 'camera_1', state: 'ready', reason: 'clear', count: 2, alarm: false,
    persons: [{ track_id: 1, in_roi: true, direction: 1 }], events: [],
    sample_interval_seconds: 0.45, updated_at: '2026-10-22T00:00:00+00:00',
    valid_for_seconds: 1.8, error: null, ...overrides,
  }
}

test('浏览器时钟快慢不影响有效结果和三个统计字段', (t) => {
  const value = snapshot()
  for (const offset of [-600_000, 600_000]) {
    const clock = t.mock.method(Date, 'now', () => Date.parse(value.updated_at) + offset)
    const result = receiveTailgatingStatus(null, value, 1000, 1300)
    assert.equal(result.value.count, 2)
    assert.equal(result.value.state, 'ready')
    assert.equal(result.value.sample_interval_seconds, 0.45)
    assert.equal(result.expiresAt - 1300, 1500)
    clock.mock.restore()
  }
})

test('传输途中失效的结果直接显示过期，不短暂展示正常数据', () => {
  for (const valid_for_seconds of [0, 0.3, -1, NaN, Infinity, undefined]) {
    const result = receiveTailgatingStatus(null, snapshot({ valid_for_seconds }), 1000, 1300)
    assert.equal(result.value, null)
    assert.equal(result.expiresAt, null)
    assert.match(result.error, /过期/)
  }
})

test('重复获取同一快照不能延长截止时间，新快照可以续期', () => {
  const first = receiveTailgatingStatus(null, snapshot(), 1000, 1100)
  const repeated = receiveTailgatingStatus(first, snapshot({ valid_for_seconds: 1.5 }), 1500, 1600)
  assert.equal(repeated.expiresAt, first.expiresAt)
  const updated = receiveTailgatingStatus(repeated, snapshot({ updated_at: '2026-10-22T00:00:01+00:00' }), 2000, 2100)
  assert.equal(updated.expiresAt, 3800)
  assert.equal(updated.error, '')
})

test('短暂请求失败保留有效快照，恢复后清除错误且不清空统计值', () => {
  const first = receiveTailgatingStatus(null, snapshot(), 1000, 1100)
  const failed = failTailgatingStatus(first, 'camera_1', '网络错误', 1800)
  assert.equal(failed.value, first.value)
  assert.equal(failed.expiresAt, first.expiresAt)
  assert.equal(failed.error, '网络错误')
  const recovered = receiveTailgatingStatus(failed, snapshot({ valid_for_seconds: 0.8 }), 2000, 2100)
  assert.equal(recovered.value.count, 2)
  assert.equal(recovered.error, '')
})

test('请求持续失败或轮询中断时清除过期结论', () => {
  const first = receiveTailgatingStatus(null, snapshot(), 1000, 1100)
  const failed = failTailgatingStatus(first, 'camera_1', '网络错误', 2800)
  assert.equal(failed.value, null)
  const expired = expireTailgatingStatus(first)
  assert.equal(expired.value, null)
  assert.equal(expired.expiresAt, null)
  assert.match(expired.error, /过期/)
})

test('摄像头切换不保留上一台的有效值或截止时间', () => {
  const previous = receiveTailgatingStatus(null, snapshot(), 1000, 1100)
  const failed = failTailgatingStatus(previous, 'camera_2', '网络错误', 1200)
  assert.equal(failed.key, 'camera_2')
  assert.equal(failed.value, null)
  const switched = receiveTailgatingStatus(previous, snapshot({ camera_key: 'camera_2' }), 1500, 1600)
  assert.equal(switched.key, 'camera_2')
  assert.equal(switched.expiresAt, 3300)
})

test('停用、离线、等待和后端过期状态直接按服务端状态展示', () => {
  const previous = receiveTailgatingStatus(null, snapshot(), 1000, 1100)
  for (const state of ['disabled', 'offline', 'waiting', 'stale']) {
    const result = receiveTailgatingStatus(previous, snapshot({ state, count: null, valid_for_seconds: 0 }), 1500, 1600)
    assert.equal(result.value.state, state)
    assert.equal(result.value.count, null)
    assert.equal(result.expiresAt, null)
    assert.equal(result.error, '')
  }
})

test('检测异常保留具体错误并使用相同的剩余有效期', () => {
  const result = receiveTailgatingStatus(null, snapshot({ state: 'error', error: '推理失败', count: null }), 1000, 1100)
  assert.equal(result.value.error, '推理失败')
  assert.equal(result.expiresAt, 2800)
})
