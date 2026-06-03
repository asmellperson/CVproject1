import { createContext } from 'react'
import type { Department, UserRole } from '@/auth/permissions'

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
  login: (account: string, password: string) => Promise<void>
  changePassword: (currentPassword: string, newPassword: string) => Promise<void>
  logout: () => Promise<void>
  refreshMe: () => Promise<void>
  handleUnauthorized: () => void
}

export const AuthContext = createContext<AuthContextValue | null>(null)
