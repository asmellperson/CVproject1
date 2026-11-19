import { FacePersonPermissions } from '@/components/face_recognition/FacePersonPermissions'
import { fencePersonPermissionsApi } from './api'

export function FenceWhitelist({ cameraKey }: { cameraKey: string }) {
  return <div className="space-y-3">
    <p className="text-sm text-slate-500 dark:text-slate-400">各摄像头独立生效，切换摄像头后请分别维护白名单。</p>
    <FacePersonPermissions key={cameraKey} scope={cameraKey}
      permissions={fencePersonPermissionsApi} title="围栏白名单" />
  </div>
}
