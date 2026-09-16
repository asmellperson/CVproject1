import { DEPARTMENT_LABELS, type DepartmentId } from '@/auth/permissions'
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
  department: DepartmentId
}

export function GuardBehaviorSection({ department }: GuardBehaviorSectionProps) {
  const { isAdmin } = useAuth()
  const [sites, setSites] = useState<GuardRoomSite[]>([])
  const [selectedSiteId, setSelectedSiteId] = useState<number | null>(null)
  const [loadingSites, setLoadingSites] = useState(true)
  const [siteError, setSiteError] = useState('')
  const detectionTitle = '保安行为规范检测'

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
          departmentLabel={DEPARTMENT_LABELS[department]}
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
          {!loadingSites && !siteError && !sites.some((site) => site.cameras.length) && <p>当前事业部暂未配置摄像头</p>}
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
