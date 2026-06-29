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
      setError('Sélectionnez un fichier Excel (.xlsx).')
      return
    }
    if (!name.trim()) {
      setError('Le nom du framework est requis.')
      return
    }
    setBusy(true)
    try {
      await importFramework(file, { display_name: name.trim(), country: country.trim() })
      onImported()
      onClose()
    } catch (e: any) {
      setError(e.message ?? "Échec de l'import")
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
      <div className="w-[480px] rounded-xl bg-white p-6 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <h2 className="text-lg font-bold text-[#451DC7]">Importer un framework</h2>
        <div className="mt-2 rounded-lg border border-gray-100 bg-gray-50 px-3 py-2 text-xs text-gray-500">
          <p className="font-medium text-gray-600">Colonnes requises dans votre fichier Excel :</p>
          <ul className="mt-1 space-y-0.5">
            <li><b>ID</b> — identifiant unique de l'exigence (ex. CYF-001)</li>
            <li><b>Title</b> — intitulé du contrôle (ex. CyFun 2025)</li>
            <li><b>Requirement</b> — texte détaillé de l'exigence</li>
            <li><b>Category</b> — catégorie de l'exigence dans ce référentiel</li>
          </ul>
          <p className="mt-1 text-gray-400">La casse des en-têtes est ignorée.</p>
        </div>

        <div className="mt-4 flex flex-col gap-3">
          <label className="flex flex-col gap-1">
            <span className="text-xs font-medium text-gray-600">Fichier (.xlsx)</span>
            <input
              type="file"
              accept=".xlsx,.xlsm"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="text-sm file:mr-3 file:rounded-md file:border-0 file:bg-indigo-50 file:px-3 file:py-1.5 file:text-indigo-700"
            />
          </label>
          <Field label="Nom du framework" value={name} onChange={setName} placeholder="Ex. Allemagne BSI 2024" />
          <Field label="Pays" value={country} onChange={setCountry} placeholder="Allemagne" />
        </div>

        {error && (
          <pre className="mt-3 whitespace-pre-wrap rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
            {error}
          </pre>
        )}

        <div className="mt-5 flex justify-end gap-2">
          <button onClick={onClose} className="rounded-lg px-3 py-2 text-sm text-gray-600 hover:bg-gray-100">
            Annuler
          </button>
          <button
            onClick={submit}
            disabled={busy}
            className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
          >
            {busy ? 'Import en cours…' : 'Importer'}
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
        type="text"
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-indigo-500"
      />
    </label>
  )
}
