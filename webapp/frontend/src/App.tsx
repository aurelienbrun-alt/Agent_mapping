import { useState } from 'react'
import { Routes, Route } from 'react-router-dom'
import { AppStateProvider } from './lib/appState'
import Sidebar from './components/Sidebar'
import Header from './components/Header'
import SettingsModal from './components/SettingsModal'
import NewMapping from './pages/NewMapping'
import Baseline from './pages/Baseline'
import Mappings from './pages/Mappings'

export default function App() {
  const [settingsOpen, setSettingsOpen] = useState(false)
  return (
    <AppStateProvider>
      <div className="flex h-screen overflow-hidden">
        <Sidebar onOpenSettings={() => setSettingsOpen(true)} />
        <div className="flex flex-1 flex-col overflow-hidden">
          <Header onOpenSettings={() => setSettingsOpen(true)} />
          <main className="flex-1 overflow-auto bg-gray-50 p-6">
            <div className="mx-auto max-w-5xl">
              <Routes>
                <Route path="/" element={<NewMapping />} />
                <Route path="/mappings" element={<Mappings />} />
                <Route path="/baseline" element={<Baseline />} />
              </Routes>
            </div>
          </main>
        </div>
      </div>
      {settingsOpen && <SettingsModal onClose={() => setSettingsOpen(false)} />}
    </AppStateProvider>
  )
}
