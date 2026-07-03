import type { ReactNode } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'

function Section({ title }: { title: string }) {
  return <p className="px-4 pt-4 pb-1 text-xs font-bold tracking-wide text-gray-400">{title}</p>
}

function AppLogo() {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M12 2 4 5v6c0 5.2 3.4 9.9 8 11 4.6-1.1 8-5.8 8-11V5l-8-3Z"
        fill="#EEF2FF"
        stroke="#451DC7"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
      <path d="m9.2 12 1.8 1.8 3.8-4.1" stroke="#451DC7" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function UploadIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true" className="shrink-0">
      <path d="M12 16V5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      <path d="m8 9 4-4 4 4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M5 19h14" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  )
}

function ListIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true" className="shrink-0">
      <path d="M9 6h10M9 12h10M9 18h10" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      <circle cx="5" cy="6" r="1.2" fill="currentColor" />
      <circle cx="5" cy="12" r="1.2" fill="currentColor" />
      <circle cx="5" cy="18" r="1.2" fill="currentColor" />
    </svg>
  )
}

function SettingsIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true" className="shrink-0">
      <circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="1.8" />
      <path d="M19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-1.8-.3 1.6 1.6 0 0 0-1 1.5V21a2 2 0 0 1-4 0v-.1a1.6 1.6 0 0 0-1-1.5 1.6 1.6 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.6 1.6 0 0 0 .3-1.8 1.6 1.6 0 0 0-1.5-1H3a2 2 0 0 1 0-4h.1a1.6 1.6 0 0 0 1.5-1 1.6 1.6 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.6 1.6 0 0 0 1.8.3H9a1.6 1.6 0 0 0 1-1.5V3a2 2 0 0 1 4 0v.1a1.6 1.6 0 0 0 1 1.5 1.6 1.6 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0-.3 1.8V9a1.6 1.6 0 0 0 1.5 1h.1a2 2 0 0 1 0 4h-.1a1.6 1.6 0 0 0-1.5 1Z" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function BaselineIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true" className="shrink-0">
      <path d="M7 4h10l2 2v12a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2Z" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
      <path d="M9 10h6M9 14h4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      <path d="M15 4v3h3" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function NewBaselineIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden="true" className="shrink-0">
      <path d="M7 4h10l2 2v12a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2Z" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" />
      <path d="M12 9v6M9 12h6" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
      <path d="M15 4v3h3" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function Item({ to, children }: { to: string; children: ReactNode }) {
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
      <span className="flex items-center gap-2">{children}</span>
    </NavLink>
  )
}

function ActionButton({ onClick, children }: { onClick: () => void; children: ReactNode }) {
  return (
    <button
      onClick={onClick}
      className="mx-2 rounded-lg px-3 py-2 text-left text-sm text-gray-700 transition hover:bg-gray-100"
    >
      <span className="flex items-center gap-2">{children}</span>
    </button>
  )
}

function SoonItem({ children }: { children: ReactNode }) {
  return (
    <div className="mx-2 flex items-center justify-between rounded-lg px-3 py-2 text-sm text-gray-400">
      <span className="flex items-center gap-2">{children}</span>
      <span className="rounded bg-gray-200 px-1.5 py-0.5 text-[10px] font-medium text-gray-500">Coming soon</span>
    </div>
  )
}

export default function Sidebar({ onOpenSettings }: { onOpenSettings: () => void }) {
  const navigate = useNavigate()

  return (
    <aside className="flex w-64 shrink-0 flex-col overflow-y-auto border-r border-gray-200 bg-white">
      <div className="flex items-center gap-3 px-4 py-4">
        <AppLogo />
        <span className="text-lg font-bold text-[#451DC7]">Compliance Assistant</span>
      </div>

      <Section title="ACTIONS" />
      <div className="flex flex-col gap-0.5">
        <Item to="/">
          <span className="text-base leading-none">＋</span>
          <span>New mapping</span>
        </Item>
        <Item to="/mappings">
          <ListIcon />
          <span>Completed mappings</span>
        </Item>
        <ActionButton onClick={() => navigate('/?import=1')}>
          <UploadIcon />
          <span>Import framework</span>
        </ActionButton>
        <SoonItem>
          <NewBaselineIcon />
          <span>New baseline</span>
        </SoonItem>
        <SoonItem>
          <BaselineIcon />
          <span>My baselines</span>
        </SoonItem>
        <ActionButton onClick={onOpenSettings}>
          <SettingsIcon />
          <span>Azure OpenAI Configuration</span>
        </ActionButton>
      </div>
    </aside>
  )
}
