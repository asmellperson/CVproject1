// 文件说明：包含`resizable-layout-contract.test` 模块的自动化测试、测试夹具与断言辅助代码。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const frontendRoot = new URL('../', import.meta.url)
/**
 * 功能：读取或查询 `read` 对应的`resizable-layout-contract.test` 模块逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：
 *   - `path`（未显式标注）：目标路径
 * 返回：void（由实现推断）；仅执行处理流程，不返回业务数据。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`readFile`、`URL`。
 * 副作用/注意事项：无明显外部副作用；下层调用失败时可能继续抛出异常。
 */
const read = (path) => readFile(new URL(path, frontendRoot), 'utf8')

const [app, sidebar, layout, securityVlm] = await Promise.all([
  read('src/App.tsx'),
  read('src/components/Sidebar.tsx'),
  read('src/components/monitor/ResizableMonitorLayout.tsx'),
  read('src/sections/SecurityVlmSection.tsx'),
])

test('desktop sidebar width is draggable, bounded, persistent, and aligned with main content', () => {
  assert.match(app, /DEFAULT_SIDEBAR_WIDTH = 272/)
  assert.match(app, /MIN_SIDEBAR_WIDTH = 240/)
  assert.match(app, /MAX_SIDEBAR_WIDTH = 420/)
  assert.match(app, /COLLAPSED_SIDEBAR_WIDTH = 84/)
  assert.match(app, /aivision:sidebar-width-v2/)
  assert.match(app, /window\.localStorage\.setItem/)
  assert.match(app, /paddingLeft: sidebarCollapsed \? COLLAPSED_SIDEBAR_WIDTH : sidebarWidth/)
  assert.match(app, /id="app-main-content"/)

  assert.match(sidebar, /role="separator"/)
  assert.match(sidebar, /aria-label="调整导航栏宽度"/)
  assert.match(sidebar, /cursor-col-resize/)
  assert.match(sidebar, /setPointerCapture/)
  assert.match(sidebar, /ArrowLeft/)
  assert.match(sidebar, /ArrowRight/)
  assert.match(sidebar, /!isMobile && !compact/)
})

test('shared monitor layout resizes two panels on desktop and stacks on small screens', () => {
  assert.match(layout, /DESKTOP_MONITOR_QUERY = '\(min-width: 1024px\)'/)
  assert.match(layout, /useDefaultLayout/)
  assert.match(layout, /window\.localStorage/)
  assert.match(layout, /ResizablePanelGroup/)
  assert.match(layout, /ResizablePanel/)
  assert.match(layout, /ResizableHandle/)
  assert.match(layout, /aria-label="调整实时监控模块宽度"/)
  assert.match(layout, /minSize="12rem"/)
  assert.match(layout, /minSize="18rem"/)
  assert.match(layout, /return <section className="grid min-w-0 gap-5">/)
})

test('security VLM keeps its existing single and multi-video layout', () => {
  assert.match(securityVlm, /singleView/)
  assert.match(securityVlm, /多画面/)
  assert.match(securityVlm, /单画面/)
  assert.doesNotMatch(securityVlm, /ResizableMonitorLayout/)
})
