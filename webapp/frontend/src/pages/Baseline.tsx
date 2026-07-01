import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  getCategories,
  startBaseline,
  getBaseline,
  baselineDownloadUrl,
  type Category,
  type Job,
} from '../api/client'
import { useAppState } from '../lib/appState'
import { Spinner } from './NewMapping'

export default function Baseline() {
  const { lastMapping } = useAppState()
  const navigate = useNavigate()
  const [categories, setCategories] = useState<Category[]>([])
  const [selected, setSelected] = useState<Record<string, boolean>>({})
  const [jobId, setJobId] = useState<string | null>(null)
  const [job, setJob] = useState<Job | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getCategories()
      .then((cats) => {
        setCategories(cats)
        setSelected(Object.fromEntries(cats.map((c) => [c.name, true])))
      })
      .catch((e) => setError(e.message))
  }, [])

  useEffect(() => {
    if (!jobId) return
    let stop = false
    async function poll() {
      while (!stop) {
        try {
          const j = await getBaseline(jobId!)
          if (stop) return
          setJob(j)
          if (j.status !== 'running') return
        } catch (e: any) {
          if (!stop) setError(e.message)
          return
        }
        await new Promise((r) => setTimeout(r, 1500))
      }
    }
    poll()
    return () => {
      stop = true
    }
  }, [jobId])

  if (!lastMapping) {
    return (
      <div className="flex flex-col gap-4">
        <h2 className="text-2xl font-bold text-[#451DC7]">Configurez votre Baseline Groupe</h2>
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-5">
          <p className="text-amber-800">Lancez d'abord un mapping pour pouvoir construire une baseline.</p>
          <button
            onClick={() => navigate('/')}
            className="mt-3 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700"
          >
            ＋ Nouveau Mapping
          </button>
        </div>
      </div>
    )
  }

  async function build() {
    setError(null)
    const chosen = categories.filter((c) => selected[c.name]).map((c) => c.name)
    if (chosen.length === 0) {
      setError('Sélectionnez au moins une catégorie.')
      return
    }
    try {
      const id = await startBaseline(lastMapping!.jobId, chosen)
      setJob({ id, kind: 'baseline', status: 'running', stage: '', error: '', result: null })
      setJobId(id)
    } catch (e: any) {
      setError(e.message)
    }
  }

  const running = job?.status === 'running'
  const result = job?.status === 'done' ? job.result : null

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h2 className="text-2xl font-bold text-[#451DC7]">Configurez votre Baseline Groupe</h2>
        <p className="text-sm text-gray-500">
          Le jeu de points de contrôle à respecter pour être conforme dans tous les pays sélectionnés.
        </p>
        <p className="mt-1 text-sm text-gray-600">
          Basée sur le mapping : {lastMapping.sourceName} → {lastMapping.targetName}
        </p>
      </div>

      <h3 className="mt-2 text-lg font-semibold text-[#451DC7]">
        Sélectionnez les domaines (catégories ENISA) à inclure
      </h3>
      <div className="grid grid-cols-1 gap-x-6 gap-y-1 md:grid-cols-2">
        {categories.map((c) => (
          <label key={c.name} className="flex items-center gap-2 text-sm text-gray-700" title={c.definition}>
            <input
              type="checkbox"
              checked={selected[c.name] ?? false}
              onChange={(e) => setSelected((prev) => ({ ...prev, [c.name]: e.target.checked }))}
              className="h-4 w-4 accent-indigo-600"
            />
            {c.name}
          </label>
        ))}
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">{error}</div>
      )}

      <hr className="my-2 border-gray-200" />

      {running ? (
        <div className="flex items-center gap-3 rounded-xl border border-indigo-200 bg-indigo-50 px-4 py-3">
          <Spinner />
          <span className="text-[#451DC7]">{job?.stage || 'Construction de la baseline…'}</span>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          <div>
            <button
              onClick={build}
              className="rounded-lg bg-indigo-600 px-5 py-2.5 font-medium text-white transition hover:bg-indigo-700"
            >
              🧱 Construire la baseline
            </button>
          </div>

          {result && jobId && (
            <div className="rounded-xl border border-green-200 bg-green-50 p-5">
              <h3 className="text-lg font-bold text-green-700">✅ Baseline générée</h3>
              <p className="mt-1 text-sm">{result.summary?.total ?? 0} points de contrôle consolidés</p>
              <a
                href={baselineDownloadUrl(jobId)}
                className="mt-3 inline-block rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700"
              >
                ⬇ Télécharger la baseline (Excel)
              </a>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
