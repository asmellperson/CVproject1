import { FacePersonPermissions } from '@/components/face_recognition/FacePersonPermissions'
import { fencePersonPermissionsApi } from './api'

export function FenceWhitelist({ cameraKey }: { cameraKey: string }) {
  return <FacePersonPermissions key={cameraKey} scope={cameraKey}
    permissions={fencePersonPermissionsApi} title="围栏白名单"
    description="管理当前摄像头的通行白名单，各摄像头独立生效；未添加的人员默认不允许通行。仅管理员可以修改允许状态。" />
}
