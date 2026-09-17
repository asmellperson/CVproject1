import type { DepartmentId } from '../auth/permissions'
import type { AuthUser } from '../auth/auth-context'
import type { ComponentProps } from 'react'
import type { getOverview, OverviewStatus } from '../lib/api'
import type { HomeSection } from '../sections/HomeSection'
import type { useOverview } from './use-overview'

type Equal<Left, Right> =
  (<Value>() => Value extends Left ? 1 : 2) extends
  (<Value>() => Value extends Right ? 1 : 2)
    ? true
    : false

type AssertTrue<Value extends true> = Value

type ExpectedHomeSectionProps = {
  onNavigate: (page: string, department?: DepartmentId) => void
  overviewState: ReturnType<typeof useOverview>
}

export type UseOverviewStatusContractAssertions = [
  AssertTrue<Equal<Parameters<typeof getOverview>, [init?: RequestInit]>>,
  AssertTrue<Equal<ReturnType<typeof getOverview>, Promise<OverviewStatus>>>,
  AssertTrue<Equal<Parameters<typeof useOverview>, [user: AuthUser | null]>>,
  AssertTrue<Equal<ReturnType<typeof useOverview>, import('./use-overview').OverviewState>>,
  AssertTrue<Equal<ComponentProps<typeof HomeSection>, ExpectedHomeSectionProps>>,
]
