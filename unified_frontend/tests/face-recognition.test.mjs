import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import test from 'node:test'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import ts from 'typescript'

const require = createRequire(import.meta.url)
const root = new URL('../', import.meta.url)

async function compile(path, imports = {}) {
  const source = await readFile(new URL(path, root), 'utf8')
  const output = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX },
  }).outputText
  const module = { exports: {} }
  Function('require', 'exports', 'module', output)((name) => imports[name] ?? require(name), module.exports, module)
  return module.exports
}

const wrapper = ({ children }) => React.createElement('div', null, children)
const icons = new Proxy({}, { get: () => () => React.createElement('svg') })
const ui = new Proxy({}, { get: () => wrapper })

test('人脸身份识别只列在电子电工事业部，原有报警权限不变', async () => {
  const permissions = await compile('src/auth/permissions.ts')
  const electronic = { role: 'viewer', departments: ['electronics_electrician'] }
  assert.equal(permissions.hasPageAccess(electronic, 'face-recognition'), true)
  for (const department of ['research_institute', 'general_electric', 'electrical_components']) {
    assert.equal(permissions.hasPageAccess({ role: 'viewer', departments: [department] }, 'face-recognition'), false)
  }
  assert.equal(permissions.hasPageAccess({ role: 'admin' }, 'face-recognition'), true)
  assert.equal(permissions.hasPageAccess(null, 'face-recognition'), false)
  assert.equal(permissions.getAccessibleAlarmEventTypes(electronic).includes('recognize_face'), false)
})

test('顶部页签按实时监控、识别记录、配置管理排列，原有页面仍然只有两个页签', async () => {
  const { DetectionPageHeader } = await compile('src/components/detection/DetectionPageHeader.tsx', {
    'lucide-react': icons, '@/components/ui/tabs': ui,
  })
  const props = { title: '人脸身份识别', subtitle: '', departmentLabel: '电子电工事业部' }
  const html = renderToStaticMarkup(React.createElement(DetectionPageHeader, { ...props, recordsValue: 'records' }))
  assert.ok(html.indexOf('实时监控') < html.indexOf('识别记录'))
  assert.ok(html.indexOf('识别记录') < html.indexOf('配置管理'))
  const other = renderToStaticMarkup(React.createElement(DetectionPageHeader, props))
  assert.equal(other.includes('识别记录'), false)
})

test('同一摄像头的一帧展示所有身份、相似度与未知人员，断连后清除姓名', async () => {
  let status = {
    online: true, reason: 'normal', frame_width: 1000, frame_height: 600,
    detections: [
      { bbox: [10, 20, 100, 150], matched: true, person_id: 1, person_name: '测试甲', similarity: .88 },
      { bbox: [200, 20, 300, 150], matched: true, person_id: 2, person_name: '测试乙', similarity: .91 },
      { bbox: [400, 20, 500, 150], matched: false, person_id: null, person_name: '未知人员', similarity: .42 },
    ],
  }
  const { FaceRecognitionMonitorView } = await compile('src/components/face_recognition/FaceRecognitionMonitorView.tsx', {
    'lucide-react': icons,
    '@/components/ui/button': ui, '@/components/ui/card': ui, '@/components/ui/label': ui, '@/components/ui/select': ui,
    '@/components/monitor/ResizableMonitorLayout': { ResizableMonitorLayout: wrapper },
    '@/lib/aivision': { getAiVisionCameraKey: (camera) => camera.shm_name },
    './useFaceRecognitionStatus': { useFaceRecognitionStatus: () => ({ status, error: '' }) },
  })
  const props = { cameras: [], selectedCamera: 'camera_1', loading: false, message: '实时画面已连接', frameConnected: true, frameContent: null }
  let html = renderToStaticMarkup(React.createElement(FaceRecognitionMonitorView, props))
  for (const text of ['测试甲', '测试乙', '未知人员', '88.0%', '91.0%', '42.0%']) assert.ok(html.includes(text))
  assert.equal((html.match(/<rect /g) || []).length, 3)
  status = { ...status, online: false }
  html = renderToStaticMarkup(React.createElement(FaceRecognitionMonitorView, props))
  assert.equal(html.includes('测试甲'), false)
  assert.equal((html.match(/<rect /g) || []).length, 0)
})

test('API 请求携带登录凭据、摄像头过滤和取消信号', async () => {
  const api = await compile('src/components/face_recognition/api.ts', { '@/lib/aivision': { AIVISION_URL: '/aivision/' } })
  const originalFetch = globalThis.fetch
  const calls = []
  globalThis.fetch = async (...args) => {
    calls.push(args)
    return { ok: true, status: 200, json: async () => ({ items: [] }) }
  }
  try {
    const signal = new AbortController().signal
    await api.getFaceRecognitionStatus('camera / 一', signal)
    await api.getRecognitionRecords(2, '7', signal)
    assert.equal(calls[0][0], `/aivision/api/features/recognize_face/cameras/${encodeURIComponent('camera / 一')}/status`)
    assert.equal(calls[1][0], '/aivision/api/face-recognition/records?page=2&page_size=20&camera_id=7')
    assert.equal(calls[0][1].credentials, 'include')
    assert.equal(calls[0][1].signal, signal)
    globalThis.fetch = async () => ({ ok: false, status: 403 })
    await assert.rejects(api.getRecognitionRecords(1, ''), /HTTP 403/)
  } finally {
    globalThis.fetch = originalFetch
  }
})
