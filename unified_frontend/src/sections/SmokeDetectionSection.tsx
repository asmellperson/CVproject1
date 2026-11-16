import { DEPARTMENT_LABELS, type DepartmentId } from '@/auth/permissions'
import { AiVisionMonitor } from '@/components/AiVisionMonitor'
import { DetectionPageHeader } from '@/components/detection/DetectionPageHeader'
import { SmokeConfigView } from '@/components/smoke_detection/SmokeConfigView'
import { SMOKE_FEATURE } from '@/components/smoke_detection/config'
import { Tabs, TabsContent } from '@/components/ui/tabs'

export function SmokeDetectionSection({ department }: { department: DepartmentId }) {
  return <div className="min-h-[calc(100vh-7rem)] rounded-3xl bg-[#F3F5FA] p-4 dark:bg-slate-950 dark:text-slate-100 sm:p-5 lg:p-6">
    <Tabs defaultValue="monitor" className="space-y-5">
      <DetectionPageHeader title="烟雾检测" departmentLabel={DEPARTMENT_LABELS[department]} />
      <TabsContent value="monitor" className="mt-0 space-y-5">
        <AiVisionMonitor title="烟雾监控" feature={SMOKE_FEATURE} department={department} presentation="smoke" />
      </TabsContent>
      <TabsContent value="config" className="mt-0 space-y-6">
        <SmokeConfigView key={department} department={department} />
      </TabsContent>
    </Tabs>
  </div>
}
