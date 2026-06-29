import { createContext, useContext, useState, type ReactNode } from 'react'

// The completed mapping that the Baseline page builds upon. Kept in memory (and a
// lightweight localStorage mirror so a reload keeps the reference within the session).
export interface LastMapping {
  jobId: string
  sourceName: string
  targetName: string
  summary: Record<string, number>
}

interface AppState {
  lastMapping: LastMapping | null
  setLastMapping: (m: LastMapping | null) => void
}

const LS_KEY = 'nis2_last_mapping'

function load(): LastMapping | null {
  try {
    const raw = localStorage.getItem(LS_KEY)
    return raw ? (JSON.parse(raw) as LastMapping) : null
  } catch {
    return null
  }
}

const Ctx = createContext<AppState | null>(null)

export function AppStateProvider({ children }: { children: ReactNode }) {
  const [lastMapping, setLastMappingState] = useState<LastMapping | null>(load)

  const setLastMapping = (m: LastMapping | null) => {
    setLastMappingState(m)
    if (m) localStorage.setItem(LS_KEY, JSON.stringify(m))
    else localStorage.removeItem(LS_KEY)
  }

  return <Ctx.Provider value={{ lastMapping, setLastMapping }}>{children}</Ctx.Provider>
}

export function useAppState(): AppState {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useAppState must be used within AppStateProvider')
  return ctx
}
