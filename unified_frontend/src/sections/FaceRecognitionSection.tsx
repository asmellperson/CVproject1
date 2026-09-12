import { AiVisionMonitor } from '@/components/AiVisionMonitor'
import { DetectionPageHeader } from '@/components/detection/DetectionPageHeader'
import { RecognitionConfigView } from '@/components/face_recognition/RecognitionConfigView'
import { RecognitionRecordsView } from '@/components/face_recognition/RecognitionRecordsView'
import { FACE_DEPARTMENT, FACE_FEATURE } from '@/components/face_recognition/api'
import { Tabs, TabsContent } from '@/components/ui/tabs'

export function FaceRecognitionSection() {
  return (
    <div className="min-h-[calc(100vh-7rem)] rounded-3xl bg-[#F3F5FA] p-4 dark:bg-slate-950 dark:text-slate-100 sm:p-5 lg:p-6">
      <Tabs defaultValue="monitor" className="space-y-5">
        <DetectionPageHeader title="人脸身份识别" subtitle="多人脸实时身份识别与记录查询" departmentLabel="电子电工事业部" recordsValue="records" />
        <TabsContent value="monitor" className="mt-0 space-y-5"><AiVisionMonitor title="人脸身份识别监控" feature={FACE_FEATURE} department={FACE_DEPARTMENT} presentation="face-identity" /></TabsContent>
        <TabsContent value="records" className="mt-0 space-y-5"><RecognitionRecordsView /></TabsContent>
        <TabsContent value="config" className="mt-0 space-y-6"><RecognitionConfigView /></TabsContent>
      </Tabs>
    </div>
  )
}
