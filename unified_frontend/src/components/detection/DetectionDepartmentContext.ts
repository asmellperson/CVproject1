import { createContext, useContext } from 'react'
import type { DepartmentId } from '@/auth/permissions'

// 公共报警与设备组件共享当前页面事业部，避免从 URL 猜测或回退到全局列表。
export const DetectionDepartmentContext = createContext<DepartmentId | null>(null)
export const useDetectionDepartment = () => useContext(DetectionDepartmentContext)
