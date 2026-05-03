import { createContext } from 'react'
import type { Department, UserRole } from '@/lib/permissions'

export type AuthUser = {
  employee_id: string
  name: string
  role: UserRole | string
  department?: Department | string | null
}

export type AuthContextValue = {
  user: AuthUser | null
  loading: boolean
  isAdmin: boolean
  login: (employeeId: string, password: string) => Promise<void>
  logout: () => Promise<void>
  refreshMe: () => Promise<void>
  handleUnauthorized: () => void
}

export const AuthContext = createContext<AuthContextValue | null>(null)
