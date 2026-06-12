import { useEffect, useMemo, useState } from 'react'
import { Settings2, Video } from 'lucide-react'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { MonitorSection } from '@/sections/MonitorSection'
import { ConfigSection } from '@/sections/ConfigSection'
import { createGuardRoomSite, deleteGuardRoomSite, getGuardRoomSites } from '@/lib/api'
import type { GuardRoomSite } from '@/types'

export function GuardBehaviorSection() {
  const [sites, setSites] = useState<GuardRoomSite[]>([])
  const [selectedSiteId, setSelectedSiteId] = useState<number | null>(null)
  const [loadingSites, setLoadingSites] = useState(true)
  const [siteError, setSiteError] = useState('')

  const selectedSite = useMemo(
    () => sites.find((site) => site.id === selectedSiteId) || null,
    [selectedSiteId, sites],
  )

  const loadSites = async () => {
    const next = await getGuardRoomSites()
    setSites(next)
    setSelectedSiteId((current) => {
      if (current && next.some((site) => site.id === current)) return current
      return next[0]?.id ?? null
    })
  }

  useEffect(() => {
    let mounted = true
    getGuardRoomSites()
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
  }, [])

  const handleCreateSite = async (name: string) => {
    setSiteError('')
    try {
      const created = await createGuardRoomSite({ name })
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
    <div className="space-y-6">
      <Tabs defaultValue="monitor" className="space-y-6">
        <TabsList className="grid h-auto w-full max-w-md grid-cols-2 p-1">
          <TabsTrigger value="monitor" className="gap-2 py-2">
            <Video className="h-4 w-4" />
            实时监控
          </TabsTrigger>
          <TabsTrigger value="config" className="gap-2 py-2">
            <Settings2 className="h-4 w-4" />
            配置管理
          </TabsTrigger>
        </TabsList>

        <TabsContent value="monitor" className="space-y-6">
          <MonitorSection
            site={selectedSite}
            sites={sites}
            selectedSiteId={selectedSiteId}
            loadingSites={loadingSites}
            onSelectSite={setSelectedSiteId}
          />
        </TabsContent>

        <TabsContent value="config">
          <ConfigSection
            site={selectedSite}
            sites={sites}
            selectedSiteId={selectedSiteId}
            loadingSites={loadingSites}
            siteError={siteError}
            onSelectSite={setSelectedSiteId}
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
