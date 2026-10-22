import type { DepartmentId } from '@/auth/permissions'
import { FacePersonPermissions } from '@/components/face_recognition/FacePersonPermissions'
import { fencePersonPermissionsApi } from './api'

export function FenceWhitelist({ department }: { department: DepartmentId }) {
  return <FacePersonPermissions key={department} department={department}
    permissions={fencePersonPermissionsApi} title="围栏白名单" />
}
