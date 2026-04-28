import { cn } from '@/lib/utils';
import { 
  Video, 
  Bell, 
  Settings, 
  BarChart3, 
  Shield,
  Activity
} from 'lucide-react';

interface SidebarProps {
  currentPage: string;
  onPageChange: (page: string) => void;
}

const navItems = [
  { id: 'monitor', label: '实时监控', icon: Video },
  { id: 'alarms', label: '报警记录', icon: Bell },
  { id: 'statistics', label: '统计分析', icon: BarChart3 },
  { id: 'config', label: '配置管理', icon: Settings },
];

export function Sidebar({ currentPage, onPageChange }: SidebarProps) {
  return (
    <div className="w-64 bg-slate-900 text-white h-screen flex flex-col fixed left-0 top-0">
      {/* Logo */}
      <div className="p-6 border-b border-slate-800">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-blue-600 rounded-lg flex items-center justify-center">
            <Shield className="w-6 h-6 text-white" />
          </div>
          <div>
            <h1 className="font-bold text-lg leading-tight">智能监控系统</h1>
            <p className="text-xs text-slate-400">保安室行为分析</p>
          </div>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 p-4 space-y-2">
        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive = currentPage === item.id;
          return (
            <button
              key={item.id}
              onClick={() => onPageChange(item.id)}
              className={cn(
                'w-full flex items-center gap-3 px-4 py-3 rounded-lg transition-all duration-200',
                'hover:bg-slate-800 focus:outline-none focus:ring-2 focus:ring-blue-500',
                isActive 
                  ? 'bg-blue-600 text-white shadow-lg shadow-blue-900/30' 
                  : 'text-slate-300 hover:text-white'
              )}
            >
              <Icon className={cn('w-5 h-5', isActive && 'animate-pulse')} />
              <span className="font-medium">{item.label}</span>
              {isActive && (
                <div className="ml-auto w-2 h-2 bg-white rounded-full" />
              )}
            </button>
          );
        })}
      </nav>

      {/* Status */}
      <div className="p-4 border-t border-slate-800">
        <div className="bg-slate-800 rounded-lg p-4">
          <div className="flex items-center gap-2 mb-2">
            <Activity className="w-4 h-4 text-green-400" />
            <span className="text-sm font-medium text-slate-200">系统状态</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 bg-green-500 rounded-full animate-pulse" />
            <span className="text-xs text-slate-400">运行正常</span>
          </div>
          <div className="mt-2 text-xs text-slate-500">
            FPS: 12.5 | 帧数: 25.6K
          </div>
        </div>
      </div>
    </div>
  );
}
