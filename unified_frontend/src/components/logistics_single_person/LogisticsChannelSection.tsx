import { useDepartmentCatalog } from '@/hooks/use-department-catalog'
import { useAuth } from '@/auth/useAuth'
import { DetectionPageHeader } from '@/components/detection/DetectionPageHeader'
import { Tabs, TabsContent } from '@/components/ui/tabs'

import { LogisticsChannelConfigView } from './LogisticsChannelConfigView'
import { LogisticsChannelMonitorView } from './LogisticsChannelMonitorView'
import { LogisticsChannelRuntimeControl } from './LogisticsChannelRuntimeControl'
import { useLogisticsChannels, useLogisticsChannelStatus } from './useLogisticsChannels'
import type { LogisticsFeatureName } from './types'

export type LogisticsChannelSectionProps = {
  feature: LogisticsFeatureName
  title: string
}

export function LogisticsChannelSection({ feature, title }: LogisticsChannelSectionProps) {
  const { isAdmin } = useAuth()
  const { labels } = useDepartmentCatalog()
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
        <DetectionPageHeader
          title={title.replace(/监控与配置$/, '')}
          subtitle="物流通道单人检测监控面板"
          departmentLabel={channelQuery.selectedChannel ? (labels[channelQuery.selectedChannel.department] ?? channelQuery.selectedChannel.department) : '物流通道'}
          runtimeControl={(
            <LogisticsChannelRuntimeControl
              feature={feature}
              channel={channelQuery.selectedChannelDetail}
              loading={channelQuery.loading}
              isAdmin={isAdmin}
              onChanged={refreshAll}
            />
          )}
        />
        <TabsContent value="monitor" className="mt-0">
          <LogisticsChannelMonitorView
            feature={feature}
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
