import type { DepartmentId } from '../auth/permissions'
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
  department: DepartmentId
  onNavigate: (page: string, department: DepartmentId) => void
  overviewState: ReturnType<typeof useOverview>
}

export type UseOverviewStatusContractAssertions = [
  AssertTrue<Equal<Parameters<typeof getOverview>, [department: DepartmentId, init?: RequestInit]>>,
  AssertTrue<Equal<ReturnType<typeof getOverview>, Promise<OverviewStatus>>>,
  AssertTrue<Equal<Parameters<typeof useOverview>, [department: DepartmentId | null]>>,
  AssertTrue<Equal<ReturnType<typeof useOverview>, import('./use-overview').OverviewState>>,
  AssertTrue<Equal<ComponentProps<typeof HomeSection>, ExpectedHomeSectionProps>>,
]
