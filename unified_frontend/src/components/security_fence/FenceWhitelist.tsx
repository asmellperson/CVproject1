import { FacePersonPermissions } from '@/components/face_recognition/FacePersonPermissions'
import { fencePersonPermissionsApi } from './api'

export function FenceWhitelist({ cameraKey }: { cameraKey: string }) {
  return <FacePersonPermissions key={cameraKey} scope={cameraKey}
    permissions={fencePersonPermissionsApi} title="围栏白名单" />
}
