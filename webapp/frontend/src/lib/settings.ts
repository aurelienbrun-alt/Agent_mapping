// Azure credentials live ONLY in the browser (localStorage) and are attached to API
// calls as headers. They are never persisted on the server.

export interface Creds {
  apiKey: string
  endpoint: string
  apiVersion: string
}

const KEY = 'nis2_azure_settings'

const EMPTY: Creds = { apiKey: '', endpoint: '', apiVersion: '' }

export function getCreds(): Creds {
  const raw = localStorage.getItem(KEY)
  if (!raw) return { ...EMPTY }
  try {
    const d = JSON.parse(raw)
    return {
      apiKey: d.apiKey ?? '',
      endpoint: d.endpoint ?? '',
      apiVersion: d.apiVersion ?? '',
    }
  } catch {
    return { ...EMPTY }
  }
}

export function saveCreds(c: Creds): void {
  localStorage.setItem(KEY, JSON.stringify(c))
}

export function hasCreds(): boolean {
  return getCreds().apiKey.trim().length > 0
}
