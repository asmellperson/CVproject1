import { useEffect, useMemo, useState } from 'react'
import { Settings2, Video } from 'lucide-react'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { MonitorSection } from '@/sections/MonitorSection'
import { ConfigSection } from '@/sections/ConfigSection'
import { createGuardRoomSite, deleteGuardRoomSite, getGuardRoomSites } from '@/lib/api'
import type { GuardRoomSite } from '@/types'

type GuardBehaviorSectionProps = {
  department?: string
}

export function GuardBehaviorSection({ department }: GuardBehaviorSectionProps) {
  const [sites, setSites] = useState<GuardRoomSite[]>([])
  const [selectedSiteId, setSelectedSiteId] = useState<number | null>(null)
  const [loadingSites, setLoadingSites] = useState(true)
  const [siteError, setSiteError] = useState('')
  const pageTitle = department === 'electronics_electrician'
    ? '电子电工保安行为规范监控与配置'
    : '通用电气保安行为规范监控与配置'

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
    <div className="min-h-[calc(100vh-7rem)] rounded-3xl bg-[#F3F5FA] p-4 sm:p-5 lg:p-6">
      <Tabs defaultValue="monitor" className="space-y-5">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <h1 className="text-2xl font-black tracking-tight text-slate-950 sm:text-[28px]">{pageTitle}</h1>
            <p className="mt-1 text-sm text-slate-500 sm:text-base">行为分析监控面板</p>
          </div>
          <TabsList className="grid h-auto w-full shrink-0 grid-cols-2 rounded-full border border-slate-200/70 bg-white p-1 shadow-sm sm:w-auto">
            <TabsTrigger
              value="monitor"
              className="gap-2 rounded-full px-4 py-1.5 text-slate-500 shadow-none data-[state=active]:bg-[#132C72] data-[state=active]:text-white data-[state=active]:shadow-sm"
            >
              <Video className="h-4 w-4" />
              实时监控
            </TabsTrigger>
            <TabsTrigger
              value="config"
              className="gap-2 rounded-full px-4 py-1.5 text-slate-500 shadow-none data-[state=active]:bg-[#132C72] data-[state=active]:text-white data-[state=active]:shadow-sm"
            >
              <Settings2 className="h-4 w-4" />
              配置管理
            </TabsTrigger>
          </TabsList>
        </div>

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
