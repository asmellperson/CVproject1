import { Settings2, Video } from 'lucide-react'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { MonitorSection } from '@/sections/MonitorSection'
import { ConfigSection } from '@/sections/ConfigSection'

export function GuardBehaviorSection() {
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
          <MonitorSection />
        </TabsContent>

        <TabsContent value="config">
          <ConfigSection />
        </TabsContent>
      </Tabs>
    </div>
  )
}

export default GuardBehaviorSection
