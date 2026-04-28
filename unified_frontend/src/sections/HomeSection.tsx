import { ArrowRight, CircleDotDashed, DoorOpen, ScanFace, ShieldCheck, Smartphone, UserRound } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'

interface HomeSectionProps {
  onNavigate: (page: string) => void
}

const moduleEntries = [
  {
    id: 'guard-behavior',
    title: '保安行为规范检测入口',
    icon: ShieldCheck,
    status: '已接入',
    accent: 'from-sky-500 to-blue-600',
    glow: 'shadow-blue-500/18',
    iconColor: 'text-blue-600',
    iconBg: 'from-blue-50 to-sky-100',
  },
  {
    id: 'intrusion-detection',
    title: '区域入侵检测入口',
    icon: UserRound,
    status: '已接入',
    accent: 'from-teal-400 to-emerald-500',
    glow: 'shadow-emerald-500/16',
    iconColor: 'text-teal-600',
    iconBg: 'from-teal-50 to-cyan-100',
  },
  {
    id: 'door-detection',
    title: '大门检测入口',
    icon: DoorOpen,
    status: '已接入',
    accent: 'from-indigo-500 to-blue-600',
    glow: 'shadow-indigo-500/16',
    iconColor: 'text-indigo-600',
    iconBg: 'from-indigo-50 to-blue-100',
  },
  {
    id: 'face-detection',
    title: '人脸检测入口',
    icon: ScanFace,
    status: '已接入',
    accent: 'from-violet-500 to-purple-600',
    glow: 'shadow-violet-500/16',
    iconColor: 'text-violet-600',
    iconBg: 'from-violet-50 to-purple-100',
  },
  {
    id: 'human-detection',
    title: '人体逗留检测入口',
    icon: CircleDotDashed,
    status: '已接入',
    accent: 'from-amber-400 to-orange-500',
    glow: 'shadow-orange-500/16',
    iconColor: 'text-orange-600',
    iconBg: 'from-orange-50 to-amber-100',
  },
  {
    id: 'phone-detection',
    title: '手机检测入口',
    icon: Smartphone,
    status: '已接入',
    accent: 'from-rose-500 to-red-500',
    glow: 'shadow-rose-500/16',
    iconColor: 'text-rose-600',
    iconBg: 'from-rose-50 to-red-100',
  },
]

export function HomeSection({ onNavigate }: HomeSectionProps) {
  return (
    <div className="relative -mx-3 -my-4 min-h-[calc(100dvh-64px)] overflow-hidden bg-[#f5f8fc] p-3 sm:-mx-4 sm:-my-5 sm:min-h-[calc(100vh-72px)] sm:p-4 lg:-mx-8 lg:-my-6 lg:p-8 2xl:-mx-10 2xl:p-10">
      <div aria-hidden className="pointer-events-none absolute inset-0 bg-[linear-gradient(180deg,#f8fbff_0%,#eef4fb_48%,#f8fafc_100%)]" />
      <div aria-hidden className="pointer-events-none absolute inset-x-10 top-8 h-24 rounded-full bg-blue-200/20 blur-3xl" />

      <div className="relative z-[1] flex w-full min-w-0 flex-col gap-4 sm:gap-7">
        <section className="relative min-h-[190px] overflow-hidden rounded-[14px] border border-white/80 bg-slate-900 shadow-[0_22px_54px_rgba(15,44,92,0.16)] sm:min-h-[310px] sm:rounded-[18px]">
          <img src="/company-home-bg.jpg" alt="" className="absolute inset-0 h-full w-full object-cover object-center" />
          <div className="absolute inset-0 bg-[linear-gradient(90deg,rgba(232,242,255,0.96)_0%,rgba(222,236,255,0.78)_50%,rgba(218,235,255,0.16)_100%)] sm:bg-[linear-gradient(90deg,rgba(232,242,255,0.94)_0%,rgba(222,236,255,0.66)_38%,rgba(218,235,255,0.08)_72%)]" />
          <div className="absolute inset-0 bg-[radial-gradient(circle_at_15%_20%,rgba(255,255,255,0.9),transparent_24%),linear-gradient(180deg,rgba(255,255,255,0.2),rgba(255,255,255,0))]" />
          <div className="relative flex min-h-[190px] max-w-3xl flex-col justify-center px-5 py-8 sm:min-h-[310px] sm:px-16 sm:py-10">
            <h2 className="text-4xl font-black tracking-[0] text-[#061d45] drop-shadow-[0_10px_22px_rgba(255,255,255,0.65)] sm:text-5xl md:text-6xl">
              福达视觉平台
            </h2>
          </div>
        </section>

        <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-6">
          {moduleEntries.map((entry) => {
            const Icon = entry.icon
            return (
              <article
                key={entry.title}
                className={cn(
                  'group relative min-h-[176px] overflow-hidden rounded-[14px] border border-white bg-white shadow-[0_16px_42px_rgba(25,53,93,0.10)] sm:min-h-[218px]',
                  'transition duration-200 hover:-translate-y-1 hover:shadow-[0_24px_58px_rgba(25,53,93,0.16)]',
                  entry.glow,
                )}
              >
                <div className={`h-1.5 bg-gradient-to-r ${entry.accent}`} />
                <div className="absolute -right-10 bottom-2 opacity-[0.055] transition duration-200 group-hover:scale-105 group-hover:opacity-[0.08] sm:-right-12">
                  <Icon className="h-32 w-32 text-slate-900 sm:h-40 sm:w-40" strokeWidth={1.4} />
                </div>
                <div className="relative flex h-full flex-col justify-between p-5 sm:p-7">
                  <div className="flex items-start gap-4 sm:gap-5">
                    <div className={`flex h-14 w-14 shrink-0 items-center justify-center rounded-full bg-gradient-to-br ${entry.iconBg} shadow-[0_10px_26px_rgba(30,78,141,0.12)] ring-1 ring-white sm:h-[74px] sm:w-[74px]`}>
                      <Icon className={`h-7 w-7 sm:h-9 sm:w-9 ${entry.iconColor}`} strokeWidth={1.8} />
                    </div>
                    <div className="min-w-0 pt-1 sm:pt-3">
                      <h3 className="text-lg font-bold tracking-[0] text-[#071d3d] sm:text-[22px]">{entry.title}</h3>
                      <Badge className="mt-3 border border-emerald-200 bg-emerald-50 px-3 py-1 text-sm font-medium text-emerald-600 shadow-none hover:bg-emerald-50">
                        {entry.status}
                      </Badge>
                    </div>
                  </div>
                  <Button
                    className="mt-5 h-11 w-full justify-between rounded-xl bg-[#001b43] px-5 text-base font-semibold text-white shadow-[0_10px_20px_rgba(0,27,67,0.22)] hover:bg-[#082a5f] sm:mt-7 sm:h-12 sm:w-[210px] sm:px-8"
                    onClick={() => onNavigate(entry.id)}
                  >
                    进入功能
                    <ArrowRight className="h-5 w-5" />
                  </Button>
                </div>
              </article>
            )
          })}
        </section>
      </div>
    </div>
  )
}
