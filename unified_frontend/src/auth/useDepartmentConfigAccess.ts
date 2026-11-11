import { useAuth } from '@/auth/useAuth'
import { canConfigureDepartment, type DepartmentId } from '@/auth/permissions'
import { useDetectionDepartment } from '@/components/detection/DetectionDepartmentContext'

export function useDepartmentConfigAccess(department?: DepartmentId | null, feature?: string) {
  const { user } = useAuth()
  const currentDepartment = useDetectionDepartment()
  return canConfigureDepartment(user, department === undefined ? currentDepartment : department, feature)
}
