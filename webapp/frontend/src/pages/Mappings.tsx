import { useEffect, useMemo, useState } from 'react'
import {
  getOutputs,
  getOutputView,
  outputDownloadUrl,
  type OutputFile,
  type OutputWorkbook,
} from '../api/client'
import { Spinner } from './NewMapping'

export default function Mappings() {
  const [files, setFiles] = useState<OutputFile[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<string | null>(null)

  useEffect(() => {
    getOutputs()
      .then(setFiles)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  if (selected) return <Viewer name={selected} onBack={() => setSelected(null)} />

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h2 className="text-2xl font-bold text-[#451DC7]">Mappings réalisés</h2>
        <p className="text-sm text-gray-500">
          Les classeurs Excel produits par l'agent. Visualisez-les ici ou téléchargez-les.
        </p>
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">{error}</div>
      )}

      {loading ? (
        <div className="flex items-center gap-3 text-gray-500">
          <Spinner /> Chargement…
        </div>
      ) : files.length === 0 ? (
        <div className="rounded-xl border border-dashed border-gray-300 bg-gray-50 p-8 text-center text-gray-500">
          Aucun mapping pour le moment. Lancez une analyse depuis <b>Nouveau Mapping</b> ; le classeur
          apparaîtra ici.
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {files.map((f) => (
            <FileRow key={f.name} file={f} onView={() => setSelected(f.name)} />
          ))}
        </div>
      )}
    </div>
  )
}

function FileRow({ file, onView }: { file: OutputFile; onView: () => void }) {
  const when = new Date(file.modified).toLocaleString('fr-FR', {
    dateStyle: 'medium',
    timeStyle: 'short',
  })
  return (
    <div className="flex items-center justify-between rounded-xl border border-gray-200 bg-white p-4 transition hover:shadow-sm">
      <div className="min-w-0">
        <div className="truncate font-medium text-[#451DC7]" title={file.name}>
          📊 {file.name}
        </div>
        <div className="mt-0.5 text-xs text-gray-500">
          {when} · {file.size_kb} Ko · {file.sheets.length} feuille{file.sheets.length > 1 ? 's' : ''}
        </div>
      </div>
      <div className="flex shrink-0 gap-2">
        <button
          onClick={onView}
          className="rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700"
        >
          👁 Visualiser
        </button>
        <a
          href={outputDownloadUrl(file.name)}
          className="rounded-lg border border-indigo-500 px-3 py-1.5 text-sm text-indigo-600 hover:bg-indigo-50"
        >
          ⬇ Excel
        </a>
      </div>
    </div>
  )
}

function _norm(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9]/g, '')
}

function coverageClass(header: string, value: string): string {
  if (_norm(header) !== 'coveragelevel') return ''
  const n = parseInt(value, 10)
  if (Number.isNaN(n)) return ''
  if (n >= 100) return 'bg-green-100 text-green-800 font-medium'
  if (n >= 40) return 'bg-amber-100 text-amber-800 font-medium'
  if (n > 0) return 'bg-red-50 text-red-700'
  return 'bg-red-100 text-red-700 font-medium'
}

function Viewer({ name, onBack }: { name: string; onBack: () => void }) {
  const [wb, setWb] = useState<OutputWorkbook | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [active, setActive] = useState(0)

  useEffect(() => {
    setLoading(true)
    getOutputView(name)
      .then((data) => {
        setWb(data)
        // Land on the first real mapping sheet (one with a "Source control ID" header).
        const idx = data.sheets.findIndex((s) => s.headers.some((h) => _norm(h) === 'sourcecontrolid'))
        setActive(idx >= 0 ? idx : 0)
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [name])

  const sheet = useMemo(() => wb?.sheets[active] ?? null, [wb, active])

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-3">
          <button
            onClick={onBack}
            className="shrink-0 rounded-lg px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-100"
          >
            ← Retour
          </button>
          <span className="truncate font-medium text-[#451DC7]" title={name}>
            {name}
          </span>
        </div>
        <a
          href={outputDownloadUrl(name)}
          className="shrink-0 rounded-lg border border-indigo-500 px-3 py-1.5 text-sm text-indigo-600 hover:bg-indigo-50"
        >
          ⬇ Télécharger Excel
        </a>
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">{error}</div>
      )}

      {loading ? (
        <div className="flex items-center gap-3 text-gray-500">
          <Spinner /> Lecture du classeur…
        </div>
      ) : wb && sheet ? (
        <>
          <div className="flex flex-wrap gap-1.5 border-b border-gray-200 pb-2">
            {wb.sheets.map((s, i) => (
              <button
                key={s.name}
                onClick={() => setActive(i)}
                className={`rounded-t-lg px-3 py-1.5 text-sm transition ${
                  i === active
                    ? 'bg-indigo-600 font-medium text-white'
                    : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                }`}
              >
                {s.name}
              </button>
            ))}
          </div>

          {sheet.title && <p className="text-sm font-medium text-[#451DC7]">{sheet.title}</p>}
          <p className="text-xs text-gray-400">
            {sheet.total_rows} ligne{sheet.total_rows > 1 ? 's' : ''}
            {sheet.truncated && ' · affichage limité aux 2000 premières — téléchargez le fichier pour tout voir'}
          </p>

          <SheetTable sheet={sheet} />
        </>
      ) : null}
    </div>
  )
}

function SheetTable({ sheet }: { sheet: OutputWorkbook['sheets'][number] }) {
  if (sheet.headers.length === 0 && sheet.rows.length === 0) {
    return <p className="text-sm text-gray-400">Feuille vide.</p>
  }
  return (
    <div className="max-h-[70vh] overflow-auto rounded-lg border border-gray-200">
      <table className="min-w-full border-collapse text-xs">
        <thead className="sticky top-0 z-10">
          <tr>
            {sheet.headers.map((h, i) => (
              <th
                key={i}
                className="border-b border-gray-200 bg-[#451DC7] px-3 py-2 text-left font-semibold text-white"
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sheet.rows.map((row, ri) => (
            <tr key={ri} className={ri % 2 ? 'bg-gray-50' : 'bg-white'}>
              {row.map((cell, ci) => (
                <td
                  key={ci}
                  className={`max-w-md border-b border-gray-100 px-3 py-1.5 align-top text-gray-700 ${coverageClass(
                    sheet.headers[ci] ?? '',
                    cell,
                  )}`}
                >
                  <div className="max-h-32 overflow-auto whitespace-pre-wrap">{cell}</div>
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
