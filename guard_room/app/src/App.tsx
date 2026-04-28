import { useState } from 'react';
import { Sidebar } from '@/components/Sidebar';
import { MonitorSection } from '@/sections/MonitorSection';
import { AlarmsSection } from '@/sections/AlarmsSection';
import { StatisticsSection } from '@/sections/StatisticsSection';
import { ConfigSection } from '@/sections/ConfigSection';
import { Toaster } from '@/components/ui/sonner';

function App() {
  const [currentPage, setCurrentPage] = useState('monitor');

  const renderContent = () => {
    switch (currentPage) {
      case 'monitor':
        return <MonitorSection />;
      case 'alarms':
        return <AlarmsSection />;
      case 'statistics':
        return <StatisticsSection />;
      case 'config':
        return <ConfigSection />;
      default:
        return <MonitorSection />;
    }
  };

  return (
    <div className="min-h-screen bg-slate-50">
      <Sidebar currentPage={currentPage} onPageChange={setCurrentPage} />
      <main className="ml-64 p-8">
        <div className="max-w-7xl mx-auto">
          {renderContent()}
        </div>
      </main>
      <Toaster />
    </div>
  );
}

export default App;
