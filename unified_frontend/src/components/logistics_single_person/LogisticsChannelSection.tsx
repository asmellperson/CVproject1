// 文件说明：实现`LogisticsChannelSection` 模块的 React 展示与交互。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

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

const FEATURE_DEPARTMENT_LABELS: Record<LogisticsFeatureName, string> = {
  detect_logistics_single_person: '通用电气事业部',
  detect_logistics_single_person_electronics_electrician: '电子电工事业部',
  detect_logistics_single_person_electrical_components: '电气部件事业部',
  detect_logistics_single_person_precious_metal_recycling: '伟达公司',
}

/**
 * 功能：渲染 `LogisticsChannelSection` React 组件，根据输入属性组织界面并返回 JSX 节点
 * 参数：
 *   - `props`（LogisticsChannelSectionProps）：React 组件属性对象；解构字段包括 feature, title
 * 返回：JSX.Element（由 React 推断）；返回用于界面渲染的 React 元素树。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`useAuth`、`useLogisticsChannels`、`useLogisticsChannelStatus`、`refresh`、`refreshSelectedChannel`、`refreshStatus`、`refreshSummary`、`refreshFrame`、`return`、`calc`
 *          等共 17 个调用。
 * 副作用/注意事项：会参与 React 渲染；事件回调可能更新状态或触发外部操作。
 */
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
        <DetectionPageHeader
          title={title.replace(/监控与配置$/, '')}
          subtitle="物流通道单人检测监控面板"
          departmentLabel={FEATURE_DEPARTMENT_LABELS[feature]}
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
