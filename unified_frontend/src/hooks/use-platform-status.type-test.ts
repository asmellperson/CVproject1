import type { ComponentProps } from 'react'
import type { getPlatformStatus, PlatformStatus } from '../lib/api'
import type { HomeSection } from '../sections/HomeSection'
import type { usePlatformStatus } from './use-platform-status'

type Equal<Left, Right> =
  (<Value>() => Value extends Left ? 1 : 2) extends
  (<Value>() => Value extends Right ? 1 : 2)
    ? true
    : false

type AssertTrue<Value extends true> = Value

type ExpectedHomeSectionProps = {
  onNavigate: (page: string) => void
  platformStatus: PlatformStatus | null
}

export type UsePlatformStatusContractAssertions = [
  AssertTrue<Equal<Parameters<typeof getPlatformStatus>, [init?: RequestInit]>>,
  AssertTrue<Equal<ReturnType<typeof getPlatformStatus>, Promise<PlatformStatus>>>,
  AssertTrue<Equal<Parameters<typeof usePlatformStatus>, []>>,
  AssertTrue<Equal<ReturnType<typeof usePlatformStatus>, PlatformStatus | null>>,
  AssertTrue<Equal<ComponentProps<typeof HomeSection>, ExpectedHomeSectionProps>>,
]
