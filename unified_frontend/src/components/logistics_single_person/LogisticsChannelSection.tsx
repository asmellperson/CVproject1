import { useEffect, useState } from 'react'
import { getAiVisionCameras, type AiVisionCamera } from '@/lib/aivision'
import { PLATFORM_CAMERAS_CHANGED_EVENT } from '@/lib/camera-events'
import { DEPARTMENT_LABELS, type DepartmentId } from '@/auth/permissions'
import { useDepartmentConfigAccess } from '@/auth/useDepartmentConfigAccess'
import { DetectionPageHeader } from '@/components/detection/DetectionPageHeader'
import { Tabs, TabsContent } from '@/components/ui/tabs'

import { LogisticsChannelConfigView } from './LogisticsChannelConfigView'
import { LogisticsChannelMonitorView } from './LogisticsChannelMonitorView'
import { useLogisticsChannels, useLogisticsChannelStatus } from './useLogisticsChannels'
import type { LogisticsFeatureName } from './types'

export type LogisticsChannelSectionProps = {
  feature: LogisticsFeatureName
  department: DepartmentId
  title: string
}

export function LogisticsChannelSection({ feature, department, title }: LogisticsChannelSectionProps) {
  const canConfigure = useDepartmentConfigAccess(department, feature)
  const [cameraCount, setCameraCount] = useState<number | null>(null)
  const [cameras, setCameras] = useState<AiVisionCamera[]>([])
  const [cameraError, setCameraError] = useState('')
  useEffect(() => {
    let generation = 0
    let active = true
    const refresh = async () => {
      const request = ++generation
      try {
        const cameras = await getAiVisionCameras(department)
        if (active && request === generation) {
          setCameraCount(cameras.length)
          setCameras(cameras)
          setCameraError('')
        }
      } catch (error) {
        if (active && request === generation) {
          setCameraCount(null)
          setCameraError(`摄像头列表读取失败：${error instanceof Error ? error.message : String(error)}`)
        }
      }
    }
    setCameraCount(null)
    setCameras([])
    void refresh()
    window.addEventListener(PLATFORM_CAMERAS_CHANGED_EVENT, refresh)
    return () => {
      active = false
      window.removeEventListener(PLATFORM_CAMERAS_CHANGED_EVENT, refresh)
    }
  }, [department])
  const channelQuery = useLogisticsChannels(feature, department)
  const runtimeQuery = useLogisticsChannelStatus(feature, channelQuery.selectedChannelId)

  const refreshAll = () => {
    channelQuery.refresh()
    channelQuery.refreshSelectedChannel()
    runtimeQuery.refreshStatus()
    runtimeQuery.refreshSummary()
  }

  return (
    <div className="min-h-[calc(100vh-7rem)] rounded-3xl bg-[#F3F5FA] p-4 dark:bg-slate-950 dark:text-slate-100 sm:p-5 lg:p-6">
      <Tabs defaultValue="monitor" className="space-y-5">
        <DetectionPageHeader
          title={title.replace(/监控与配置$/, '')}
          departmentLabel={DEPARTMENT_LABELS[department]}
        />
        <TabsContent value="monitor" className="mt-0">
          {cameraCount === 0 && <p>当前事业部暂未配置摄像头</p>}
          {cameraError && <p role="alert">{cameraError}</p>}
          <LogisticsChannelMonitorView
            feature={feature}
            cameras={cameras}
            title={title}
            channels={channelQuery.channels}
            selectedChannelId={channelQuery.selectedChannelId}
            selectedChannel={channelQuery.selectedChannel}
            selectedChannelDetail={channelQuery.selectedChannelDetail}
            status={runtimeQuery.status}
            todayAlarmCount={runtimeQuery.statistics?.summary.today ?? runtimeQuery.alarms.length}
            latestAlarmAt={runtimeQuery.alarms[0]?.created_at ?? null}
            events={runtimeQuery.events}
            loading={channelQuery.loading}
            error={channelQuery.error || runtimeQuery.errors.status || runtimeQuery.errors.summary}
            onSelectChannel={channelQuery.setSelectedChannelId}
            onRefresh={refreshAll}
          />
        </TabsContent>
        <TabsContent value="config" className="mt-0">
          <LogisticsChannelConfigView
            department={department}
            feature={feature}
            channels={channelQuery.channels}
            selectedChannelId={channelQuery.selectedChannelId}
            selectedChannelDetail={channelQuery.selectedChannelDetail}
            canConfigure={canConfigure}
            onSelectChannel={channelQuery.setSelectedChannelId}
            onChannelCreated={channelQuery.selectCreatedChannelLocally}
            onChannelDeleted={channelQuery.removeChannelLocally}
            onChanged={refreshAll}
          />
        </TabsContent>
      </Tabs>
    </div>
  )
}

export default LogisticsChannelSection
