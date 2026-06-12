import { useEffect, useMemo, useState } from 'react'
import { Plus, Settings2, Video } from 'lucide-react'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { MonitorSection } from '@/sections/MonitorSection'
import { ConfigSection } from '@/sections/ConfigSection'
import { createGuardRoomSite, getGuardRoomSites } from '@/lib/api'
import { useAuth } from '@/auth/useAuth'
import type { GuardRoomSite } from '@/types'

export function GuardBehaviorSection() {
  const { isAdmin } = useAuth()
  const [sites, setSites] = useState<GuardRoomSite[]>([])
  const [selectedSiteId, setSelectedSiteId] = useState<number | null>(null)
  const [siteName, setSiteName] = useState('')
  const [loadingSites, setLoadingSites] = useState(true)
  const [siteBusy, setSiteBusy] = useState(false)
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
    loadSites()
      .catch((error) => setSiteError(error instanceof Error ? error.message : String(error)))
      .finally(() => setLoadingSites(false))
  }, [])

  const handleCreateSite = async () => {
    const name = siteName.trim()
    if (!name || siteBusy || !isAdmin) return
    setSiteBusy(true)
    setSiteError('')
    try {
      const created = await createGuardRoomSite({ name })
      setSiteName('')
      await loadSites()
      setSelectedSiteId(created.id)
    } catch (error) {
      setSiteError(error instanceof Error ? error.message : String(error))
    } finally {
      setSiteBusy(false)
    }
  }

  return (
    <div className="space-y-6">
      <Card className="border-slate-200 bg-white shadow-sm">
        <CardContent className="space-y-4 p-4 sm:p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="min-w-0">
              <h2 className="text-xl font-bold text-slate-900">保安室</h2>
              <p className="text-sm text-slate-500">按保安室选择查看拼接画面和独立配置。</p>
            </div>
            <Badge variant="outline">{sites.length} 个保安室</Badge>
          </div>

          <div className="flex flex-wrap gap-2">
            {loadingSites ? (
              <span className="text-sm text-slate-500">正在加载保安室...</span>
            ) : sites.length === 0 ? (
              <span className="text-sm text-slate-500">暂无保安室。</span>
            ) : (
              sites.map((site) => (
                <Button
                  key={site.id}
                  variant={site.id === selectedSiteId ? 'default' : 'outline'}
                  size="sm"
                  className="gap-2"
                  onClick={() => setSelectedSiteId(site.id)}
                >
                  {site.name}
                  <Badge variant="secondary" className="ml-1">{site.enabled_camera_count}/{site.camera_count}</Badge>
                </Button>
              ))
            )}
          </div>

          <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_auto]">
            <Input
              value={siteName}
              onChange={(event) => setSiteName(event.target.value)}
              placeholder="新增保安室名称，例如：一厂区南门保安室"
              disabled={!isAdmin || siteBusy}
            />
            <Button className="gap-2" onClick={handleCreateSite} disabled={!isAdmin || siteBusy || !siteName.trim()}>
              <Plus className="h-4 w-4" />
              {siteBusy ? '新增中' : '新增保安室'}
            </Button>
          </div>
          {siteError ? <div className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{siteError}</div> : null}
        </CardContent>
      </Card>

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
          <MonitorSection site={selectedSite} />
        </TabsContent>

        <TabsContent value="config">
          <ConfigSection site={selectedSite} onSitesChanged={loadSites} />
        </TabsContent>
      </Tabs>
    </div>
  )
}

export default GuardBehaviorSection
