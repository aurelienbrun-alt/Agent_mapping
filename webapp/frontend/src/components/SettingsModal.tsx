import { useState } from 'react'
import { getCreds, saveCreds, type Creds } from '../lib/settings'
import { testConnection } from '../api/client'

export default function SettingsModal({ onClose }: { onClose: () => void }) {
  const initial = getCreds()
  const [endpoint, setEndpoint] = useState(initial.endpoint)
  const [apiVersion, setApiVersion] = useState(initial.apiVersion)
  const [apiKey, setApiKey] = useState(initial.apiKey)
  const [testing, setTesting] = useState(false)
  const [status, setStatus] = useState<{ ok: boolean; msg: string } | null>(null)

  const creds = (): Creds => ({ apiKey: apiKey.trim(), endpoint: endpoint.trim(), apiVersion: apiVersion.trim() })

  async function doTest() {
    setTesting(true)
    setStatus(null)
    try {
      const r = await testConnection(creds())
      setStatus({ ok: r.ok, msg: r.message })
    } catch (e: any) {
      setStatus({ ok: false, msg: e.message ?? 'Échec du test' })
    } finally {
      setTesting(false)
    }
  }

  function doSave() {
    if (!apiKey.trim()) {
      setStatus({ ok: false, msg: 'La clé API est requise.' })
      return
    }
    saveCreds(creds())
    onClose()
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
      <div className="w-[480px] rounded-xl bg-white p-6 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <h2 className="text-lg font-bold text-[#451DC7]">Paramètres — Azure OpenAI</h2>
        <p className="mt-1 text-xs text-gray-500">
          La clé API est stockée uniquement dans votre navigateur (jamais sur le serveur).
        </p>

        <div className="mt-4 flex flex-col gap-3">
          <Field label="Endpoint Azure" value={endpoint} onChange={setEndpoint} placeholder="https://mon-resource.openai.azure.com" />
          <Field label="API version" value={apiVersion} onChange={setApiVersion} placeholder="2024-02-01" />
          <Field label="Clé API" value={apiKey} onChange={setApiKey} type="password" placeholder="••••••••" />
        </div>

        {status && (
          <p className={`mt-3 text-sm ${status.ok ? 'text-green-600' : 'text-red-600'}`}>{status.msg}</p>
        )}

        <div className="mt-5 flex items-center justify-between">
          <button
            onClick={doTest}
            disabled={testing}
            className="rounded-lg border border-indigo-500 px-3 py-2 text-sm text-indigo-600 transition hover:bg-indigo-50 disabled:opacity-50"
          >
            {testing ? 'Test en cours…' : 'Tester la connexion'}
          </button>
          <div className="flex gap-2">
            <button onClick={onClose} className="rounded-lg px-3 py-2 text-sm text-gray-600 hover:bg-gray-100">
              Annuler
            </button>
            <button onClick={doSave} className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700">
              Enregistrer
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

function Field({
  label,
  value,
  onChange,
  type = 'text',
  placeholder,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  type?: string
  placeholder?: string
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs font-medium text-gray-600">{label}</span>
      <input
        type={type}
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-indigo-500"
      />
    </label>
  )
}
