import { DEPARTMENT_LABELS, type DepartmentId } from '@/auth/permissions'
import { AiVisionMonitor } from '@/components/AiVisionMonitor'
import { DetectionPageHeader } from '@/components/detection/DetectionPageHeader'
import { TailgatingConfigView } from '@/components/tailgating/TailgatingConfigView'
import { TAILGATING_FEATURE } from '@/components/tailgating/config'
import { Tabs, TabsContent } from '@/components/ui/tabs'

export function TailgatingSection({ department }: { department: DepartmentId }) {
  return <div className="min-h-[calc(100vh-7rem)] rounded-3xl bg-[#F3F5FA] p-4 dark:bg-slate-950 dark:text-slate-100 sm:p-5 lg:p-6">
    <Tabs defaultValue="monitor" className="space-y-5">
      <DetectionPageHeader
        title="非法闯闸检测"
        subtitle="同向过线与区域共同出现联合判定"
        departmentLabel={DEPARTMENT_LABELS[department]} />
      <TabsContent value="monitor" className="mt-0 space-y-5">
        <AiVisionMonitor
          title="非法闯闸监控"
          feature={TAILGATING_FEATURE}
          department={department}
          presentation="tailgating" />
      </TabsContent>
      <TabsContent value="config" className="mt-0 space-y-6">
        <TailgatingConfigView key={department} department={department} />
      </TabsContent>
    </Tabs>
  </div>
}
