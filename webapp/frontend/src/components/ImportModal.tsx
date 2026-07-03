import { useState } from 'react'

import { importFramework } from '../api/client'

export default function ImportModal({
  onClose,
  onImported,
}: {
  onClose: () => void
  onImported: () => void
}) {
  const [file, setFile] = useState<File | null>(null)
  const [name, setName] = useState('')
  const [country, setCountry] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit() {
    setError(null)

    if (!file) {
      setError('Select an Excel file (.xlsx).')
      return
    }

    if (!name.trim()) {
      setError('Framework name is required.')
      return
    }

    setBusy(true)
    try {
      await importFramework(file, { display_name: name.trim(), country: country.trim() })
      onImported()
      onClose()
    } catch (e: any) {
      setError(e.message ?? 'Import failed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
      <div className="w-[560px] rounded-xl bg-white p-6 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <h2 className="text-lg font-bold text-[#451DC7]">Import a framework</h2>

        <p className="mt-2 text-sm text-gray-600">Required columns in your Excel file:</p>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-gray-600">
          <li>
            <strong>ID</strong> — unique requirement identifier, for example CYF-001
          </li>
          <li>
            <strong>Title</strong> — control title, for example CyFun 2025
          </li>
          <li>
            <strong>Requirement</strong> — detailed requirement text
          </li>
          <li>
            <strong>Category</strong> — requirement category in this framework
          </li>
        </ul>
        <p className="mt-2 text-xs text-gray-500">Header casing is ignored.</p>

        <div className="mt-4 flex flex-col gap-3">
          <Field label="Framework name" value={name} onChange={setName} placeholder="CyFun 2025" />
          <Field label="Country or scope" value={country} onChange={setCountry} placeholder="Belgium" />

          <label className="flex flex-col gap-1">
            <span className="text-xs font-medium text-gray-600">File (.xlsx)</span>
            <input
              type="file"
              accept=".xlsx"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="text-sm file:mr-3 file:rounded-md file:border-0 file:bg-indigo-50 file:px-3 file:py-1.5 file:text-indigo-700"
            />
          </label>
        </div>

        {error && <p className="mt-3 text-sm text-red-600">{error}</p>}

        <div className="mt-5 flex justify-end gap-2">
          <button onClick={onClose} className="rounded-lg px-3 py-2 text-sm text-gray-600 hover:bg-gray-100">
            Cancel
          </button>
          <button
            onClick={submit}
            disabled={busy}
            className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            {busy ? 'Importing…' : 'Import'}
          </button>
        </div>
      </div>
    </div>
  )
}

function Field({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  placeholder?: string
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs font-medium text-gray-600">{label}</span>
      <input
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-indigo-500"
      />
    </label>
  )
}
