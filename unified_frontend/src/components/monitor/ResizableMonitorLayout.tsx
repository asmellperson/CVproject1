// 文件说明：实现监控展示的 React 展示与交互。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import { Children, useEffect, useState, type ReactNode } from 'react'
import { useDefaultLayout, type LayoutStorage } from 'react-resizable-panels'

import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from '@/components/ui/resizable'

const DESKTOP_MONITOR_QUERY = '(min-width: 1024px)'
const DETAILS_PANEL_ID = 'details'
const MONITOR_PANEL_ID = 'monitor'

/**
 * 功能：封装 `useDesktopMonitorLayout` React Hook，向调用组件提供监控展示状态与操作
 * 参数：无。
 * 返回：未显式标注（由 TypeScript 推断）；返回实现中 `return` 表达式计算得到的结果。
 * 调用关系：
 *   - 调用方：`unified_frontend/src/components/monitor/ResizableMonitorLayout.tsx` 的 `ResizableMonitorLayout` 调用本符号
 *   - 内部调用：`useState`、`matchMedia`、`useEffect`、`setDesktop`、`addEventListener`、`update`、`return`、`removeEventListener`。
 * 副作用/注意事项：会更新 React 状态并触发相关组件重新渲染；会读取或修改浏览器全局对象/DOM 状态。
 */
function useDesktopMonitorLayout() {
  const [desktop, setDesktop] = useState(() => (
    typeof window !== 'undefined' && window.matchMedia(DESKTOP_MONITOR_QUERY).matches
  ))

  useEffect(() => {
    const query = window.matchMedia(DESKTOP_MONITOR_QUERY)
    const update = () => setDesktop(query.matches)
    query.addEventListener('change', update)
    update()
    return () => query.removeEventListener('change', update)
  }, [])

  return desktop
}

/**
 * 功能：读取或查询 `getLayoutStorage` 对应的监控展示逻辑；输入由参数提供，处理结果见返回值说明
 * 参数：无。
 * 返回：LayoutStorage | undefined；返回该函数计算、请求或构造得到的结果；具体语义由类型及调用方使用方式确定。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：不调用其他项目函数，仅进行字段声明、值返回或原地计算。
 * 副作用/注意事项：会读写浏览器本地存储；会读取或修改浏览器全局对象/DOM 状态。
 */
function getLayoutStorage(): LayoutStorage | undefined {
  try {
    return typeof window === 'undefined' ? undefined : window.localStorage
  } catch {
    return undefined
  }
}

/**
 * 功能：渲染 `ResizableMonitorLayout` React 组件，根据输入属性组织界面并返回 JSX 节点
 * 参数：
 *   - `props`（未显式标注）：React 组件属性对象；解构字段包括 id, children, id, string, children, ReactNode
 * 返回：JSX.Element（由 React 推断）；返回用于界面渲染的 React 元素树。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`useDesktopMonitorLayout`、`useState`、`toArray`、`useDefaultLayout`、`return`、`ResizablePanelGroup`、`ResizablePanel`、`ResizableHandle`。
 * 副作用/注意事项：会参与 React 渲染；事件回调可能更新状态或触发外部操作。
 */
export function ResizableMonitorLayout({
  id,
  children,
}: {
  id: string
  children: ReactNode
}) {
  const desktop = useDesktopMonitorLayout()
  const [storage] = useState(getLayoutStorage)
  const panels = Children.toArray(children)
  const details = panels[0] ?? null
  const monitor = panels[1] ?? null
  const groupId = `monitor-layout-${id}`
  const { defaultLayout, onLayoutChanged } = useDefaultLayout({
    id: groupId,
    panelIds: [DETAILS_PANEL_ID, MONITOR_PANEL_ID],
    storage,
  })

  if (!desktop) {
    return <section className="grid min-w-0 gap-5">{details}{monitor}</section>
  }

  return (
    <section className="min-w-0" data-monitor-resizable-layout={id}>
      <ResizablePanelGroup
        id={groupId}
        orientation="horizontal"
        defaultLayout={defaultLayout ?? { [DETAILS_PANEL_ID]: 33, [MONITOR_PANEL_ID]: 67 }}
        onLayoutChanged={onLayoutChanged}
        className="h-auto min-w-0 items-start"
      >
        <ResizablePanel id={DETAILS_PANEL_ID} minSize="12rem" maxSize="50%" className="min-w-0">
          <div className="min-w-0 pr-2">{details}</div>
        </ResizablePanel>
        <ResizableHandle
          withHandle
          aria-label="调整实时监控模块宽度"
          title="拖动调整实时监控模块宽度"
          className="mx-2 w-2 shrink-0 cursor-col-resize rounded-full bg-transparent after:w-4 hover:bg-blue-50 focus-visible:ring-blue-500 dark:hover:bg-blue-950/50"
        />
        <ResizablePanel id={MONITOR_PANEL_ID} minSize="18rem" className="min-w-0">
          <div className="min-w-0 pl-2">{monitor}</div>
        </ResizablePanel>
      </ResizablePanelGroup>
    </section>
  )
}
