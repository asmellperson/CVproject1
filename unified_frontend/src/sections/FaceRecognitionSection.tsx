import { DEPARTMENT_LABELS, type DepartmentId } from '@/auth/permissions'
import { AiVisionMonitor } from '@/components/AiVisionMonitor'
import { DetectionPageHeader } from '@/components/detection/DetectionPageHeader'
import { RecognitionConfigView } from '@/components/face_recognition/RecognitionConfigView'
import { RecognitionRecordsView } from '@/components/face_recognition/RecognitionRecordsView'
import { FACE_FEATURE } from '@/components/face_recognition/api'
import { Tabs, TabsContent } from '@/components/ui/tabs'

export function FaceRecognitionSection({ department }: { department: DepartmentId }) {
  return (
    <div className="min-h-[calc(100vh-7rem)] rounded-3xl bg-[#F3F5FA] p-4 dark:bg-slate-950 dark:text-slate-100 sm:p-5 lg:p-6">
      <Tabs defaultValue="monitor" className="space-y-5">
        <DetectionPageHeader title="人脸身份识别" departmentLabel={DEPARTMENT_LABELS[department]} recordsValue="records" />
        <TabsContent value="monitor" className="mt-0 space-y-5"><AiVisionMonitor title="人脸身份识别监控" feature={FACE_FEATURE} department={department} presentation="face-identity" /></TabsContent>
        <TabsContent value="records" className="mt-0 space-y-5"><RecognitionRecordsView department={department} /></TabsContent>
        <TabsContent value="config" className="mt-0 space-y-6"><RecognitionConfigView department={department} /></TabsContent>
      </Tabs>
    </div>
  )
}
