import { lazy, Suspense, useEffect, useState } from 'react'
import { Sidebar } from '@/components/Sidebar'
import { Topbar } from '@/components/Topbar'
import { HomeSection } from '@/sections/HomeSection'
import { Toaster } from '@/components/ui/sonner'
import { cn } from '@/lib/utils'
import { useIsMobile } from '@/hooks/use-mobile'
import { useOverview } from '@/hooks/use-overview'
import { useAuth } from '@/auth/useAuth'
import { isDetectionPage, resolveDepartment, resolvePage, type DepartmentId } from '@/auth/permissions'
import type { AuthUser } from '@/auth/auth-context'

const SIDEBAR_WIDTH_STORAGE_KEY = 'aivision:sidebar-width-v2'
const DEFAULT_SIDEBAR_WIDTH = 272
const MIN_SIDEBAR_WIDTH = 240
const MAX_SIDEBAR_WIDTH = 420
const COLLAPSED_SIDEBAR_WIDTH = 84

function clampSidebarWidth(width: number) {
  return Math.min(MAX_SIDEBAR_WIDTH, Math.max(MIN_SIDEBAR_WIDTH, width))
}

function getInitialSidebarWidth() {
  try {
    const stored = Number(window.localStorage.getItem(SIDEBAR_WIDTH_STORAGE_KEY))
    return Number.isFinite(stored) && stored > 0
      ? clampSidebarWidth(stored)
      : DEFAULT_SIDEBAR_WIDTH
  } catch {
    return DEFAULT_SIDEBAR_WIDTH
  }
}

const GuardBehaviorSection = lazy(() =>
  import('@/sections/GuardBehaviorSection').then((module) => ({ default: module.GuardBehaviorSection })),
)
const IntrusionDetectionSection = lazy(() =>
  import('@/sections/IntrusionDetectionSection').then((module) => ({ default: module.IntrusionDetectionSection })),
)
const DoorDetectionSection = lazy(() =>
  import('@/sections/DoorDetectionSection').then((module) => ({ default: module.DoorDetectionSection })),
)
const FaceDetectionSection = lazy(() =>
  import('@/sections/FaceDetectionSection').then((module) => ({ default: module.FaceDetectionSection })),
)
const FaceRecognitionSection = lazy(() =>
  import('@/sections/FaceRecognitionSection').then((module) => ({ default: module.FaceRecognitionSection })),
)
const HumanDetectionSection = lazy(() =>
  import('@/sections/HumanDetectionSection').then((module) => ({ default: module.HumanDetectionSection })),
)
const LogisticsSinglePersonDetectionSection = lazy(() =>
  import('@/sections/LogisticsSinglePersonDetectionSection').then((module) => ({ default: module.LogisticsSinglePersonDetectionSection })),
)
const PhoneDetectionSection = lazy(() =>
  import('@/sections/PhoneDetectionSection').then((module) => ({ default: module.PhoneDetectionSection })),
)
const SecurityVlmSection = lazy(() =>
  import('@/sections/SecurityVlmSection').then((module) => ({ default: module.SecurityVlmSection })),
)
const AlarmsSection = lazy(() => import('@/sections/AlarmsSection').then((module) => ({ default: module.AlarmsSection })))
const StatisticsSection = lazy(() =>
  import('@/sections/StatisticsSection').then((module) => ({ default: module.StatisticsSection })),
)
const UserManagementSection = lazy(() =>
  import('@/sections/UserManagementSection').then((module) => ({ default: module.UserManagementSection })),
)
const AccessAuditSection = lazy(() =>
  import('@/sections/AccessAuditSection').then((module) => ({ default: module.AccessAuditSection })),
)

function getInitialPage() {
  const params = new URLSearchParams(window.location.search)
  return params.get('page') || 'overview'
}

function initializeNavigation(user: AuthUser | null, page: string, requestedDepartment: unknown) {
  const department = resolveDepartment(user, requestedDepartment)
  const nextPage = resolvePage(user, page, requestedDepartment)
  return {
    page: nextPage,
    // 总览属于平台，不能继承检测页面的事业部上下文。
    department: nextPage === 'overview' ? null : department,
  }
}

function getInitialAlarmId() {
  return new URLSearchParams(window.location.search).get('alarmId') || ''
}

function PageLoadingFallback() {
  return (
    <div className="flex min-h-[320px] items-center justify-center rounded-xl border border-slate-200 bg-white text-sm font-medium text-slate-500 shadow-sm dark:border-slate-800 dark:bg-slate-900/80 dark:text-slate-300">
      正在加载页面...
    </div>
  )
}

function App() {
  const { user } = useAuth()
  const [navigation, setNavigation] = useState(() => initializeNavigation(
    user, getInitialPage(), new URLSearchParams(window.location.search).get('department'),
  ))
  const currentPage = navigation.page
  const activePage = resolvePage(user, currentPage, navigation.department)
  const currentDepartment = activePage === 'overview' ? null : resolveDepartment(user, navigation.department)
  const overviewState = useOverview(user)
  const [initialAlarmId] = useState(getInitialAlarmId)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [sidebarWidth, setSidebarWidth] = useState(getInitialSidebarWidth)
  const [sidebarResizing, setSidebarResizing] = useState(false)
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false)
  const isMobile = useIsMobile()

  useEffect(() => {
    const url = new URL(window.location.href)
    url.searchParams.set('page', activePage)
    if (currentDepartment) url.searchParams.set('department', currentDepartment)
    else url.searchParams.delete('department')
    window.history.replaceState(null, '', url)
  }, [activePage, currentDepartment, navigation])

  useEffect(() => {
    const syncLocation = () => {
      setNavigation(initializeNavigation(
        user, getInitialPage(), new URLSearchParams(window.location.search).get('department'),
      ))
    }
    window.addEventListener('popstate', syncLocation)
    return () => window.removeEventListener('popstate', syncLocation)
  }, [user])

  const handlePageChange = (page: string, department?: DepartmentId) => {
    const requestedDepartment = page === 'overview' ? null : isDetectionPage(page) ? department : department ?? currentDepartment
    setNavigation(initializeNavigation(user, page, requestedDepartment))
    if (isMobile) setMobileSidebarOpen(false)
  }

  const handleToggleSidebar = () => {
    if (isMobile) {
      setMobileSidebarOpen((value) => !value)
      return
    }
    setSidebarCollapsed((value) => !value)
  }

  const renderContent = () => {
    switch (activePage) {
      case 'overview':
        return <HomeSection onNavigate={handlePageChange} overviewState={overviewState} />
      case 'security-vlm':
        return currentDepartment && <SecurityVlmSection department={currentDepartment} />
      case 'guard-behavior':
        return currentDepartment && <GuardBehaviorSection department={currentDepartment} />
      case 'intrusion-detection':
        return currentDepartment && <IntrusionDetectionSection department={currentDepartment} />
      case 'door-detection':
        return currentDepartment && <DoorDetectionSection department={currentDepartment} />
      case 'face-detection':
        return currentDepartment && <FaceDetectionSection department={currentDepartment} />
      case 'face-recognition':
        return currentDepartment && <FaceRecognitionSection department={currentDepartment} />
      case 'human-detection':
        return currentDepartment && <HumanDetectionSection department={currentDepartment} />
      case 'logistics-single-person':
        return currentDepartment && <LogisticsSinglePersonDetectionSection department={currentDepartment} />
      case 'phone-detection':
        return currentDepartment && <PhoneDetectionSection department={currentDepartment} />
      case 'alarms':
        return <AlarmsSection initialAlarmId={initialAlarmId} />
      case 'statistics':
        return <StatisticsSection />
      case 'user-management':
        return <UserManagementSection />
      case 'access-audit':
        return <AccessAuditSection />
      default:
        return <HomeSection onNavigate={handlePageChange} overviewState={overviewState} />
    }
  }

  return (
    <div className="relative min-h-screen bg-background text-foreground">
      <div
        aria-hidden
        className="pointer-events-none fixed inset-0 -z-10 bg-[radial-gradient(60rem_40rem_at_-10%_-20%,hsl(var(--primary)/0.06),transparent),radial-gradient(50rem_30rem_at_110%_10%,hsl(217_91%_60%/0.08),transparent)]"
      />

      <Sidebar
        currentPage={activePage}
        currentDepartment={currentDepartment}
        onPageChange={handlePageChange}
        collapsed={sidebarCollapsed}
        onToggleCollapsed={() => setSidebarCollapsed((v) => !v)}
        width={sidebarWidth}
        minWidth={MIN_SIDEBAR_WIDTH}
        maxWidth={MAX_SIDEBAR_WIDTH}
        resizing={sidebarResizing}
        onWidthChange={(width) => setSidebarWidth(clampSidebarWidth(width))}
        onWidthCommit={(width) => {
          const nextWidth = clampSidebarWidth(width)
          setSidebarWidth(nextWidth)
          try {
            window.localStorage.setItem(SIDEBAR_WIDTH_STORAGE_KEY, String(nextWidth))
          } catch {
            void 0
          }
        }}
        onResizeStateChange={setSidebarResizing}
        mobileOpen={mobileSidebarOpen}
        onMobileClose={() => setMobileSidebarOpen(false)}
        isMobile={isMobile}
        monitoringCount={overviewState.data?.summary.camera_online ?? null}
        systemRunning={overviewState.data?.ok ?? true}
      />

      {isMobile && mobileSidebarOpen && (
        <button
          type="button"
          aria-label="关闭侧边栏"
          className="fixed inset-0 z-30 bg-slate-950/40 backdrop-blur-[2px]"
          onClick={() => setMobileSidebarOpen(false)}
        />
      )}

      <div
        className={cn(
          'min-w-0 transition-[padding] duration-300 ease-in-out',
          isMobile && 'pl-0',
          sidebarResizing && 'duration-0',
        )}
        style={isMobile ? undefined : {
          paddingLeft: sidebarCollapsed ? COLLAPSED_SIDEBAR_WIDTH : sidebarWidth,
        }}
      >
        <Topbar currentPage={activePage} onToggleSidebar={handleToggleSidebar} />
        <main id="app-main-content" className="min-w-0 px-3 py-4 sm:px-4 sm:py-5 lg:px-8 lg:py-6 2xl:px-10">
          <div className="w-full min-w-0">
            <Suspense key={`${activePage}:${currentDepartment}`} fallback={<PageLoadingFallback />}>{renderContent()}</Suspense>
          </div>
        </main>
      </div>

      <Toaster />
    </div>
  )
}

export default App
