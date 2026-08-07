import { Settings2, Video } from 'lucide-react'

import { useAuth } from '@/auth/useAuth'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'

import { LogisticsChannelConfigView } from './LogisticsChannelConfigView'
import { LogisticsChannelMonitorView } from './LogisticsChannelMonitorView'
import { useLogisticsChannels, useLogisticsChannelStatus } from './useLogisticsChannels'
import type { LogisticsFeatureName } from './types'

export type LogisticsChannelSectionProps = {
  feature: LogisticsFeatureName
  title: string
}

export function LogisticsChannelSection({ feature, title }: LogisticsChannelSectionProps) {
  const { isAdmin } = useAuth()
  const channelQuery = useLogisticsChannels(feature)
  const runtimeQuery = useLogisticsChannelStatus(feature, channelQuery.selectedChannelId)

  const refreshAll = () => {
    channelQuery.refresh()
    channelQuery.refreshSelectedChannel()
    runtimeQuery.refreshStatus()
    runtimeQuery.refreshSummary()
    runtimeQuery.refreshFrame()
  }

  return (
    <div className="space-y-6">
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.22em] text-blue-700">Logistics Channel</p>
        <h1 className="mt-2 text-2xl font-black tracking-tight text-slate-950 dark:text-slate-100">{title}</h1>
        <p className="mt-2 text-sm text-slate-500">按物流通道聚合最多 9 路摄像头；任一路多人或全部明确无人时触发通道异常。</p>
      </div>

      <Tabs defaultValue="monitor" className="space-y-5">
        <TabsList className="grid h-auto w-full max-w-md grid-cols-2 p-1">
          <TabsTrigger value="monitor" className="gap-2 py-2"><Video className="h-4 w-4" />实时监控</TabsTrigger>
          <TabsTrigger value="config" className="gap-2 py-2"><Settings2 className="h-4 w-4" />通道配置</TabsTrigger>
        </TabsList>
        <TabsContent value="monitor" className="mt-0">
          <LogisticsChannelMonitorView
            title={title}
            channels={channelQuery.channels}
            selectedChannelId={channelQuery.selectedChannelId}
            selectedChannel={channelQuery.selectedChannel}
            selectedChannelDetail={channelQuery.selectedChannelDetail}
            status={runtimeQuery.status}
            frameUrl={runtimeQuery.frameUrl}
            todayAlarmCount={runtimeQuery.statistics?.summary.today ?? runtimeQuery.alarms.length}
            loading={channelQuery.loading}
            error={channelQuery.error || runtimeQuery.errors.status || runtimeQuery.errors.summary}
            frameError={runtimeQuery.errors.frame}
            onSelectChannel={channelQuery.setSelectedChannelId}
            onRefresh={refreshAll}
          />
        </TabsContent>
        <TabsContent value="config" className="mt-0">
          <LogisticsChannelConfigView
            feature={feature}
            channels={channelQuery.channels}
            selectedChannelId={channelQuery.selectedChannelId}
            selectedChannelDetail={channelQuery.selectedChannelDetail}
            isAdmin={isAdmin}
            onSelectChannel={channelQuery.setSelectedChannelId}
            onChannelDeleted={channelQuery.removeChannelLocally}
            onChanged={refreshAll}
          />
        </TabsContent>
      </Tabs>
    </div>
  )
}

export default LogisticsChannelSection
