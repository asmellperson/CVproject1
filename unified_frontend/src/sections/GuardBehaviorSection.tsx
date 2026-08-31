// 文件说明：实现`GuardBehaviorSection` 模块的 React 展示与交互。
// 数据流：接收属性、状态或响应数据，并将结果交给组件、接口层或测试断言。

import { useEffect, useMemo, useState } from 'react'
import { useAuth } from '@/auth/useAuth'
import { DetectionPageHeader } from '@/components/detection/DetectionPageHeader'
import { GuardRoomRuntimeControl } from '@/components/guard_room/GuardRoomRuntimeControl'
import { Tabs, TabsContent } from '@/components/ui/tabs'
import { MonitorSection } from '@/sections/MonitorSection'
import { ConfigSection } from '@/sections/ConfigSection'
import { createGuardRoomSite, deleteGuardRoomSite, getGuardRoomSites } from '@/lib/api'
import type { GuardRoomSite } from '@/types'

type GuardBehaviorSectionProps = {
  department?: string
}

/**
 * 功能：渲染 `GuardBehaviorSection` React 组件，根据输入属性组织界面并返回 JSX 节点
 * 参数：
 *   - `props`（GuardBehaviorSectionProps）：React 组件属性对象；解构字段包括 department
 * 返回：JSX.Element（由 React 推断）；返回用于界面渲染的 React 元素树。
 * 调用关系：
 *   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
 *   - 内部调用：`useAuth`、`useState`、`useMemo`、`find`、`async`、`getGuardRoomSites`、`setSites`、`setSelectedSiteId`、`some`、`useEffect` 等共
 *          27 个调用。
 * 副作用/注意事项：会更新 React 状态并触发相关组件重新渲染；校验或请求失败时会主动抛出异常。
 */
export function GuardBehaviorSection({ department }: GuardBehaviorSectionProps) {
  const { isAdmin } = useAuth()
  const [sites, setSites] = useState<GuardRoomSite[]>([])
  const [selectedSiteId, setSelectedSiteId] = useState<number | null>(null)
  const [loadingSites, setLoadingSites] = useState(true)
  const [siteError, setSiteError] = useState('')
  const detectionTitle = department === 'electronics_electrician'
    ? '电子电工保安行为规范'
    : '通用电气保安行为规范'

  const selectedSite = useMemo(
    () => sites.find((site) => site.id === selectedSiteId) || null,
    [selectedSiteId, sites],
  )

  const loadSites = async () => {
    const next = await getGuardRoomSites(department)
    setSites(next)
    setSelectedSiteId((current) => {
      if (current && next.some((site) => site.id === current)) return current
      return next[0]?.id ?? null
    })
  }

  useEffect(() => {
    let mounted = true
    getGuardRoomSites(department)
      .then((next) => {
        if (!mounted) return
        setSites(next)
        setSelectedSiteId((current) => {
          if (current && next.some((site) => site.id === current)) return current
          return next[0]?.id ?? null
        })
      })
      .catch((error) => setSiteError(error instanceof Error ? error.message : String(error)))
      .finally(() => {
        if (mounted) setLoadingSites(false)
      })
    return () => {
      mounted = false
    }
  }, [department])

  const handleCreateSite = async (name: string) => {
    setSiteError('')
    try {
      const created = await createGuardRoomSite({ name, department })
      await loadSites()
      setSelectedSiteId(created.id)
      return created
    } catch (error) {
      setSiteError(error instanceof Error ? error.message : String(error))
      throw error
    }
  }

  const handleDeleteSite = async (siteId: number) => {
    setSiteError('')
    try {
      await deleteGuardRoomSite(siteId)
      await loadSites()
    } catch (error) {
      setSiteError(error instanceof Error ? error.message : String(error))
      throw error
    }
  }

  return (
    <div className="min-h-[calc(100vh-7rem)] rounded-3xl bg-[#F3F5FA] p-4 dark:bg-slate-950 dark:text-slate-100 sm:p-5 lg:p-6">
      <Tabs defaultValue="monitor" className="space-y-5">
        <DetectionPageHeader
          title={detectionTitle}
          subtitle="行为分析监控面板"
          departmentLabel={department === 'electronics_electrician' ? '电子电工事业部' : '通用电气事业部'}
          runtimeControl={(
            <GuardRoomRuntimeControl
              site={selectedSite}
              department={department}
              isAdmin={isAdmin}
              onChanged={loadSites}
            />
          )}
        />

        <TabsContent value="monitor" className="mt-0 space-y-5">
          <MonitorSection
            site={selectedSite}
            sites={sites}
            selectedSiteId={selectedSiteId}
            loadingSites={loadingSites}
            onSelectSite={setSelectedSiteId}
            department={department}
          />
        </TabsContent>

        <TabsContent value="config" className="mt-0">
          <ConfigSection
            site={selectedSite}
            sites={sites}
            selectedSiteId={selectedSiteId}
            loadingSites={loadingSites}
            siteError={siteError}
            onSelectSite={setSelectedSiteId}
            department={department}
            onCreateSite={handleCreateSite}
            onDeleteSite={handleDeleteSite}
            onSitesChanged={loadSites}
          />
        </TabsContent>
      </Tabs>
    </div>
  )
}

export default GuardBehaviorSection
