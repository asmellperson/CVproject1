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
    <div className="min-h-[calc(100vh-7rem)] rounded-3xl bg-[#F3F5FA] p-4 dark:bg-slate-950 dark:text-slate-100 sm:p-5 lg:p-6">
      <Tabs defaultValue="monitor" className="space-y-5">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <h1 className="text-2xl font-black tracking-tight text-slate-950 dark:text-slate-100 sm:text-[28px]">{title}</h1>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400 sm:text-base">物流通道单人检测监控面板</p>
          </div>
          <TabsList className="grid h-auto w-full shrink-0 grid-cols-2 rounded-full border border-slate-200/70 bg-white p-1 shadow-sm dark:border-slate-800 dark:bg-slate-900 sm:w-auto">
            <TabsTrigger value="monitor" className="gap-2 rounded-full px-4 py-1.5 text-slate-500 shadow-none data-[state=active]:bg-[#132C72] data-[state=active]:text-white data-[state=active]:shadow-sm">
              <Video className="h-4 w-4" />实时监控
            </TabsTrigger>
            <TabsTrigger value="config" className="gap-2 rounded-full px-4 py-1.5 text-slate-500 shadow-none data-[state=active]:bg-[#132C72] data-[state=active]:text-white data-[state=active]:shadow-sm">
              <Settings2 className="h-4 w-4" />配置管理
            </TabsTrigger>
          </TabsList>
        </div>
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
            latestAlarmAt={runtimeQuery.alarms[0]?.created_at ?? null}
            events={runtimeQuery.events}
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
