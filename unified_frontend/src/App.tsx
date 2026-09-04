import { lazy, Suspense, useState } from 'react'
import { Sidebar } from '@/components/Sidebar'
import { Topbar } from '@/components/Topbar'
import { HomeSection } from '@/sections/HomeSection'
import { Toaster } from '@/components/ui/sonner'
import { cn } from '@/lib/utils'
import { useIsMobile } from '@/hooks/use-mobile'
import { usePlatformStatus } from '@/hooks/use-platform-status'
import { useAuth } from '@/auth/useAuth'
import { hasPageAccess } from '@/auth/permissions'

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
const HumanDetectionSection = lazy(() =>
  import('@/sections/HumanDetectionSection').then((module) => ({ default: module.HumanDetectionSection })),
)
const HaodaHumanDetectionSection = lazy(() =>
  import('@/sections/HaodaHumanDetectionSection').then((module) => ({ default: module.HaodaHumanDetectionSection })),
)
const LogisticsSinglePersonDetectionSection = lazy(() =>
  import('@/sections/LogisticsSinglePersonDetectionSection').then((module) => ({ default: module.LogisticsSinglePersonDetectionSection })),
)
const LogisticsSinglePersonElectronicsElectricianDetectionSection = lazy(() =>
  import('@/sections/LogisticsSinglePersonElectronicsElectricianDetectionSection').then((module) => ({ default: module.LogisticsSinglePersonElectronicsElectricianDetectionSection })),
)
const LogisticsSinglePersonElectricalComponentsDetectionSection = lazy(() =>
  import('@/sections/LogisticsSinglePersonElectricalComponentsDetectionSection').then((module) => ({ default: module.LogisticsSinglePersonElectricalComponentsDetectionSection })),
)
const LogisticsSinglePersonPreciousMetalRecyclingDetectionSection = lazy(() =>
  import('@/sections/LogisticsSinglePersonPreciousMetalRecyclingDetectionSection').then((module) => ({ default: module.LogisticsSinglePersonPreciousMetalRecyclingDetectionSection })),
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
  const platformStatus = usePlatformStatus()
  const [currentPage, setCurrentPage] = useState(getInitialPage)
  const [initialAlarmId] = useState(getInitialAlarmId)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [sidebarWidth, setSidebarWidth] = useState(getInitialSidebarWidth)
  const [sidebarResizing, setSidebarResizing] = useState(false)
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false)
  const isMobile = useIsMobile()
  const activePage = hasPageAccess(user, currentPage) ? currentPage : 'overview'

  const handlePageChange = (page: string) => {
    setCurrentPage(hasPageAccess(user, page) ? page : 'overview')
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
        return <HomeSection onNavigate={handlePageChange} platformStatus={platformStatus} />
      case 'home':
        return <HomeSection onNavigate={handlePageChange} platformStatus={platformStatus} />
      case 'guard-behavior':
        return <GuardBehaviorSection department="general_electric" />
      case 'guard-behavior-general-electric':
        return <GuardBehaviorSection department="general_electric" />
      case 'guard-behavior-electronics-electrician':
        return <GuardBehaviorSection department="electronics_electrician" />
      case 'intrusion-detection':
        return <IntrusionDetectionSection />
      case 'door-detection':
        return <DoorDetectionSection />
      case 'face-detection':
        return <FaceDetectionSection />
      case 'human-detection':
        return <HumanDetectionSection />
      case 'haoda-human-detection':
        return <HaodaHumanDetectionSection />
      case 'logistics-single-person-detection':
        return <LogisticsSinglePersonDetectionSection />
      case 'logistics-single-person-electronics-electrician-detection':
        return <LogisticsSinglePersonElectronicsElectricianDetectionSection />
      case 'logistics-single-person-electrical-components-detection':
        return <LogisticsSinglePersonElectricalComponentsDetectionSection />
      case 'logistics-single-person-precious-metal-recycling-detection':
        return <LogisticsSinglePersonPreciousMetalRecyclingDetectionSection />
      case 'phone-detection':
        return <PhoneDetectionSection />
      case 'security-vlm':
      case 'security-vlm-general-electric':
        return <SecurityVlmSection department="general_electric" />
      case 'security-vlm-electronics-electrician':
        return <SecurityVlmSection department="electronics_electrician" />
      case 'security-vlm-electrical-components':
        return <SecurityVlmSection department="electrical_components" />
      case 'security-vlm-precious-metal-recycling':
        return <SecurityVlmSection department="precious_metal_recycling" />
      case 'alarms':
        return <AlarmsSection initialAlarmId={initialAlarmId} />
      case 'statistics':
        return <StatisticsSection />
      case 'user-management':
        return <UserManagementSection />
      case 'access-audit':
        return <AccessAuditSection />
      default:
        return <HomeSection onNavigate={handlePageChange} platformStatus={platformStatus} />
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
        monitoringCount={platformStatus?.summary.camera_online ?? null}
        systemRunning={platformStatus?.ok ?? true}
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
            <Suspense fallback={<PageLoadingFallback />}>{renderContent()}</Suspense>
          </div>
        </main>
      </div>

      <Toaster />
    </div>
  )
}

export default App
