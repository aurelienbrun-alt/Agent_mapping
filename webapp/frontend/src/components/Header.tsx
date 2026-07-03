function RegulatoryLogo() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <rect x="3" y="5" width="7" height="14" rx="1.5" fill="rgba(255,255,255,0.15)" stroke="white" strokeWidth="1.6" />
      <rect x="14" y="3" width="7" height="7" rx="1.5" fill="rgba(255,255,255,0.15)" stroke="white" strokeWidth="1.6" />
      <rect x="14" y="14" width="7" height="7" rx="1.5" fill="rgba(255,255,255,0.15)" stroke="white" strokeWidth="1.6" />
      <path d="M10 8h2.5A1.5 1.5 0 0 0 14 6.5" stroke="white" strokeWidth="1.6" strokeLinecap="round" />
      <path d="M10 16h2.5A1.5 1.5 0 0 1 14 17.5" stroke="white" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  )
}

function SettingsIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </svg>
  )
}

export default function Header({ onOpenSettings }: { onOpenSettings: () => void }) {
  return (
    <header className="flex items-center justify-between bg-[#451DC7] px-6 py-3 text-white shadow">
      <div className="flex items-center gap-3">
        <RegulatoryLogo />
        <h1 className="text-lg font-semibold">Regulatory mapping</h1>
      </div>

      <button
        onClick={onOpenSettings}
        title="Azure OpenAI Configuration"
        className="rounded-full p-2 transition hover:bg-white/10"
      >
        <SettingsIcon />
      </button>
    </header>
  )
}
