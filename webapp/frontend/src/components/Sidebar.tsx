import { NavLink, useNavigate } from 'react-router-dom'
import { useAppState } from '../lib/appState'

function Section({ title }: { title: string }) {
  return <p className="px-4 pt-4 pb-1 text-xs font-bold tracking-wide text-gray-400">{title}</p>
}

function Item({ to, children }: { to: string; children: React.ReactNode }) {
  return (
    <NavLink
      to={to}
      end
      className={({ isActive }) =>
        `mx-2 rounded-lg px-3 py-2 text-sm transition ${
          isActive ? 'bg-indigo-600 font-medium text-white' : 'text-gray-700 hover:bg-gray-100'
        }`
      }
    >
      {children}
    </NavLink>
  )
}

function ActionButton({ onClick, children }: { onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className="mx-2 rounded-lg px-3 py-2 text-left text-sm text-gray-700 transition hover:bg-gray-100"
    >
      {children}
    </button>
  )
}

function SoonItem({ children }: { children: React.ReactNode }) {
  return (
    <div className="mx-2 flex items-center justify-between px-3 py-2 text-sm text-gray-400">
      <span>{children}</span>
      <span className="rounded bg-gray-200 px-1.5 py-0.5 text-[10px] text-gray-500">Bientôt</span>
    </div>
  )
}

export default function Sidebar({ onOpenSettings }: { onOpenSettings: () => void }) {
  const { lastMapping } = useAppState()
  const navigate = useNavigate()
  return (
    <aside className="flex w-64 shrink-0 flex-col overflow-y-auto border-r border-gray-200 bg-white">
      <div className="flex items-center gap-2 px-4 py-4">
        <span className="text-2xl">🛡️</span>
        <span className="text-lg font-bold text-[#451DC7]">NIS2 Mapper</span>
      </div>

      <Section title="📁 PROJETS RÉCENTS" />
      {lastMapping ? (
        <Item to="/">
          → {lastMapping.sourceName} → {lastMapping.targetName}
        </Item>
      ) : (
        <p className="px-4 text-xs text-gray-400">Aucun projet récent</p>
      )}

      <Section title="⚙️ ACTIONS" />
      <div className="flex flex-col">
        <Item to="/">＋ Nouveau Mapping</Item>
        <Item to="/mappings">🗂️ Mappings réalisés</Item>
        <ActionButton onClick={() => navigate('/?import=1')}>⬆️ Importer Framework</ActionButton>
        <Item to="/baseline">⬇️ Exporter Baseline</Item>
        <Item to="/baseline">📊 Mes Baselines</Item>
        <ActionButton onClick={onOpenSettings}>🔧 Paramètres</ActionButton>
      </div>

      <Section title="🛠️ OUTILS" />
      <div className="flex flex-col pb-4">
        <SoonItem>Comparateur</SoonItem>
        <SoonItem>Gap Analyzer</SoonItem>
        <SoonItem>Evidence Tracker</SoonItem>
        <SoonItem>Reporting</SoonItem>
      </div>
    </aside>
  )
}
