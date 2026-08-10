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

function getLayoutStorage(): LayoutStorage | undefined {
  try {
    return typeof window === 'undefined' ? undefined : window.localStorage
  } catch {
    return undefined
  }
}

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
