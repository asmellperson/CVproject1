import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { test } from 'node:test'
import ts from 'typescript'

// 沿用现有前端测试方式，直接在内存编译，避免留下诊断产物。
const source = await readFile(new URL('../src/components/AiVisionMonitor.performance.ts', import.meta.url), 'utf8')
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } })
const { createPreviewPerformanceRecorder } = await import(
  `data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`
)

function recorder() {
  let at = 0
  const reports = []
  const value = createPreviewPerformanceRecorder({
    cameraKey: 'camera_1', feature: 'tailgating', department: 'general_electric', refreshMs: 100,
    now: () => at, onReport: (report) => reports.push(report),
  })
  return { value, reports, time(next) { at = next } }
}

function sample(startedAt, sequence, extra = {}) {
  return {
    startedAt, headersReceivedAt: startedAt + 700, bodyReceivedAt: startedAt + 900,
    decodedAt: startedAt + 1000, bytes: 2048, src: `blob:${startedAt}`,
    headers: new Headers({
      'Server-Timing': 'frame_lookup;dur=100, jpeg_encode;dur=200, frame_total;dur=300',
      'X-Capture-Sequence': String(sequence), 'X-Capture-Updated-At': String(1000 + startedAt / 1000),
      'X-Capture-Age-Ms': '40',
    }), ...extra,
  }
}

test('分开统计等待、下载和解码，保留目标频率与实际加载频率的区别', () => {
  const { value, reports, time } = recorder()
  for (let index = 0; index < 6; index++) {
    const frame = sample(index * 1000, 10 + index * 5)
    value.completed(frame)
    time(frame.decodedAt + 20)
    value.displayed(frame.src)
  }
  assert.equal(reports.length, 1)
  const report = reports[0]
  assert.equal(report.targetFps, 10)
  assert.equal(report.readyFps, 1)
  assert.equal(report.imageLoadFps, 0.8)
  assert.equal(report.capturePublishedFpsEstimate, 5)
  assert.equal(report.averageImageKiB, 2)
  assert.deepEqual(report.averageMs, {
    requestToHeaders: 700, downloadBody: 200, imageDecode: 100, requestToReady: 1000,
    readyToImageLoad: 20, frameLookupAndOverlay: 100, jpegEncode: 200,
    frameHandler: 300, outsideFrameHandler: 400, captureAge: 40,
  })
  assert.equal(report.failedRequests, 0)
})

test('重复共享帧估算为零更新，不能把五次 JPEG 请求当成五张新采集帧', () => {
  const { value, reports } = recorder()
  for (let index = 0; index < 5; index++) {
    value.completed(sample(index * 1000, 10, {
      headers: new Headers({ 'X-Capture-Sequence': '10', 'X-Capture-Updated-At': '1000' }),
    }))
  }
  assert.equal(reports[0].capturePublishedFpsEstimate, 0)
  assert.equal(reports[0].readyFps, 1)
  assert.equal(reports[0].averageMs.frameHandler, null)
})

test('缺少或非法采集头不伪造零帧率，未知服务器阶段保留为空', () => {
  for (const invalid of ['', 'NaN', '-1', 'Infinity', '1.5']) {
    const { value, reports } = recorder()
    value.completed(sample(0, 1, { headers: new Headers() }))
    value.completed(sample(4000, 2, { headers: new Headers({
      'X-Capture-Sequence': invalid, 'X-Capture-Updated-At': '1000',
      'Server-Timing': 'frame_lookup;dur=-10, jpeg_encode;dur=NaN, frame_total;dur=Infinity',
    }) }))
    assert.equal(reports[0].capturePublishedFpsEstimate, null)
    assert.equal(reports[0].averageMs.frameLookupAndOverlay, null)
    assert.equal(reports[0].averageMs.jpegEncode, null)
    assert.equal(reports[0].averageMs.frameHandler, null)
    assert.equal(reports[0].averageMs.outsideFrameHandler, null)
  }
})

test('采集序号重置后重新建立估算区间，不出现负帧率', () => {
  const { value, reports } = recorder()
  value.completed(sample(0, 100))
  value.completed(sample(1000, 105))
  value.completed(sample(2000, 1))
  value.completed(sample(4000, 11))
  assert.equal(reports[0].capturePublishedFpsEstimate, 5)
})

test('使用服务端读帧时间计算采集速率，网络抖动不降低采集估计值', () => {
  const { value, reports } = recorder()
  value.completed(sample(0, 10))
  value.completed(sample(4000, 30, { headers: new Headers({
    'X-Capture-Sequence': '30', 'X-Capture-Updated-At': '1002',
  }) }))
  assert.equal(reports[0].capturePublishedFpsEstimate, 10)
})

test('失败单独计数，迟到或重复图片加载不计数，停止后不再发布', () => {
  const { value, reports, time } = recorder()
  value.completed(sample(0, 10))
  value.displayed('blob:other')
  time(1020)
  value.displayed('blob:0')
  value.displayed('blob:0')
  time(5000)
  value.failed()
  assert.equal(reports[0].failedRequests, 1)
  assert.equal(reports[0].completedRequests, 1)
  assert.equal(reports[0].imageLoadFps, 0.2)
  assert.equal(reports[0].capturePublishedFpsEstimate, null)
  assert.equal(reports[0].averageMs.requestToReady, 1000)
  value.dispose()
  value.completed(sample(6000, 20))
  time(12000)
  value.failed()
  value.displayed('blob:6000')
  assert.equal(reports.length, 1)
})

test('连续失败仍汇总，失败请求不会伪装成成功帧的平均耗时', () => {
  const { value, reports, time } = recorder()
  time(5000)
  value.failed()
  assert.equal(reports[0].readyFps, 0)
  assert.equal(reports[0].averageImageKiB, null)
  assert.equal(reports[0].averageMs.requestToReady, null)
  time(10000)
  value.failed()
  assert.equal(reports[1].failedRequests, 1)
})
