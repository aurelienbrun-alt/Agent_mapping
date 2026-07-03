import { useState } from 'react'

import { testConnection } from '../api/client'
import { getCreds, saveCreds, type Creds } from '../lib/settings'

export default function SettingsModal({ onClose }: { onClose: () => void }) {
  const initial = getCreds()

  const [endpoint, setEndpoint] = useState(initial.endpoint)
  const [apiVersion, setApiVersion] = useState(initial.apiVersion)
  const [apiKey, setApiKey] = useState(initial.apiKey)
  const [testing, setTesting] = useState(false)
  const [status, setStatus] = useState<{ ok: boolean; msg: string } | null>(null)

  const creds = (): Creds => ({
    apiKey: apiKey.trim(),
    endpoint: endpoint.trim(),
    apiVersion: apiVersion.trim(),
  })

  async function doTest() {
    setTesting(true)
    setStatus(null)

    try {
      const r = await testConnection(creds())
      setStatus({ ok: r.ok, msg: r.message })
    } catch (e: any) {
      setStatus({ ok: false, msg: e.message ?? 'Connection test failed.' })
    } finally {
      setTesting(false)
    }
  }

  function doSave() {
    if (!apiKey.trim()) {
      setStatus({ ok: false, msg: 'The API key is required.' })
      return
    }

    saveCreds(creds())
    onClose()
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
      <div className="w-[480px] rounded-xl bg-white p-6 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <h2 className="text-lg font-bold text-[#451DC7]">Azure OpenAI Configuration</h2>
        <p className="mt-1 text-xs text-gray-500">
          The API key is stored only in your browser and is never persisted on the server.
        </p>

        <div className="mt-4 flex flex-col gap-3">
          <Field
            label="Azure endpoint"
            value={endpoint}
            onChange={setEndpoint}
            placeholder="https://my-resource.openai.azure.com"
          />
          <Field label="API version" value={apiVersion} onChange={setApiVersion} placeholder="2024-02-01" />
          <Field label="API key" value={apiKey} onChange={setApiKey} type="password" placeholder="••••••••" />
        </div>

        {status && <p className={`mt-3 text-sm ${status.ok ? 'text-green-600' : 'text-red-600'}`}>{status.msg}</p>}

        <div className="mt-5 flex items-center justify-between">
          <button
            onClick={doTest}
            disabled={testing}
            className="rounded-lg border border-indigo-500 px-3 py-2 text-sm text-indigo-600 transition hover:bg-indigo-50 disabled:opacity-50"
          >
            {testing ? 'Testing…' : 'Test connection'}
          </button>

          <div className="flex gap-2">
            <button onClick={onClose} className="rounded-lg px-3 py-2 text-sm text-gray-600 hover:bg-gray-100">
              Cancel
            </button>
            <button onClick={doSave} className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700">
              Save
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
