import { useState, useEffect } from 'react'
import { Sidebar } from '@/components/Sidebar'
import { Topbar } from '@/components/Topbar'
import { HomeSection } from '@/sections/HomeSection'
import { GuardBehaviorSection } from '@/sections/GuardBehaviorSection'
import { IntrusionDetectionSection } from '@/sections/IntrusionDetectionSection'
import { DoorDetectionSection } from '@/sections/DoorDetectionSection'
import { FaceDetectionSection } from '@/sections/FaceDetectionSection'
import { HumanDetectionSection } from '@/sections/HumanDetectionSection'
import { PhoneDetectionSection } from '@/sections/PhoneDetectionSection'
import { SecurityVlmSection } from '@/sections/SecurityVlmSection'
import { AlarmsSection } from '@/sections/AlarmsSection'
import { StatisticsSection } from '@/sections/StatisticsSection'
import { Toaster } from '@/components/ui/sonner'
import { cn } from '@/lib/utils'
import { useIsMobile } from '@/hooks/use-mobile'
import { useAuth } from '@/auth/useAuth'
import { hasPageAccess } from '@/lib/permissions'
import { buildDynamicNavGroups, navGroups as navGroupsFallback, type NavGroup } from '@/lib/nav'

function App() {
  const { user } = useAuth()
  const [currentPage, setCurrentPage] = useState('overview')
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false)
  const [navGroups, setNavGroups] = useState<NavGroup[]>(navGroupsFallback)
  const [navLoading, setNavLoading] = useState(false)
  const isMobile = useIsMobile()
  const activePage = hasPageAccess(user, currentPage) ? currentPage : 'overview'

  // Parse the activePage to get feature and department
  const [basePage, pageDept] = activePage.split('@')
  const normalizedDepartment = pageDept ? pageDept.replace(/-/g, '_') : undefined

  // 加载动态导航数据
  useEffect(() => {
    let mounted = true
    const loadNav = async () => {
      setNavLoading(true)
      try {
        const dynamicGroups = await buildDynamicNavGroups()
        if (mounted) {
          setNavGroups(dynamicGroups)
        }
      } catch (error) {
        console.error('Failed to load navigation groups:', error)
        // 出错时保持使用 fallback 数据
      } finally {
        if (mounted) {
          setNavLoading(false)
        }
      }
    }
    loadNav()
    return () => { mounted = false }
  }, [])

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
    switch (basePage) {
      case 'overview':
        return <HomeSection onNavigate={handlePageChange} />
      case 'home':
        return <HomeSection onNavigate={handlePageChange} />
      case 'guard-behavior':
        return <GuardBehaviorSection />
      case 'intrusion-detection':
        return <IntrusionDetectionSection department={normalizedDepartment} />
      case 'door-detection':
        return <DoorDetectionSection department={normalizedDepartment} />
      case 'face-detection':
        return <FaceDetectionSection department={normalizedDepartment} />
      case 'human-detection':
        return <HumanDetectionSection department={normalizedDepartment} />
      case 'phone-detection':
        return <PhoneDetectionSection department={normalizedDepartment} />
      case 'security-vlm':
        return <SecurityVlmSection />
      case 'alarms':
        return <AlarmsSection />
      case 'statistics':
        return <StatisticsSection />
      default:
        return <HomeSection onNavigate={handlePageChange} />
    }
  }

  return (
    <div className="relative min-h-screen bg-background text-foreground">
      {/* Subtle background texture */}
      <div
        aria-hidden
        className="pointer-events-none fixed inset-0 -z-10 bg-[radial-gradient(60rem_40rem_at_-10%_-20%,hsl(var(--primary)/0.06),transparent),radial-gradient(50rem_30rem_at_110%_10%,hsl(217_91%_60%/0.08),transparent)]"
      />

      <Sidebar
        currentPage={activePage}
        onPageChange={handlePageChange}
        collapsed={sidebarCollapsed}
        onToggleCollapsed={() => setSidebarCollapsed((v) => !v)}
        mobileOpen={mobileSidebarOpen}
        onMobileClose={() => setMobileSidebarOpen(false)}
        isMobile={isMobile}
        navGroups={navGroups}
        loading={navLoading}
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
          isMobile ? 'pl-0' : sidebarCollapsed ? 'pl-[4.75rem]' : 'pl-[18rem]',
        )}
      >
        <Topbar currentPage={activePage} onToggleSidebar={handleToggleSidebar} navGroups={navGroups} />
        <main className="min-w-0 px-3 py-4 sm:px-4 sm:py-5 lg:px-8 lg:py-6 2xl:px-10">
          <div className="w-full min-w-0">{renderContent()}</div>
        </main>
      </div>

      <Toaster />
    </div>
  )
}

export default App
