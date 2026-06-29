import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import {
  getFrameworks,
  deleteFramework,
  startMapping,
  getMapping,
  mappingDownloadUrl,
  type Framework,
  type Job,
} from '../api/client'
import { FrameworkCard, ImportFrameworkCard } from '../components/FrameworkCard'
import ImportModal from '../components/ImportModal'
import { hasCreds } from '../lib/settings'
import { useAppState } from '../lib/appState'

export default function NewMapping() {
  const [frameworks, setFrameworks] = useState<Framework[]>([])
  const [source, setSource] = useState<string | null>(null)
  const [target, setTarget] = useState<string | null>(null)
  const [jobId, setJobId] = useState<string | null>(null)
  const [job, setJob] = useState<Job | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [entityTypes, setEntityTypes] = useState<string[]>(['essential', 'important'])
  const [importOpen, setImportOpen] = useState(false)
  const { setLastMapping } = useAppState()

  function toggleEntityType(t: string) {
    setEntityTypes((prev) => (prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t]))
  }
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()

  const loadFrameworks = useCallback(() => {
    getFrameworks().then(setFrameworks).catch((e) => setError(e.message))
  }, [])

  useEffect(() => {
    loadFrameworks()
  }, [loadFrameworks])

  // Open the import modal when arriving via the sidebar action (/?import=1).
  useEffect(() => {
    if (searchParams.get('import') === '1') {
      setImportOpen(true)
      searchParams.delete('import')
      setSearchParams(searchParams, { replace: true })
    }
  }, [searchParams, setSearchParams])

  useEffect(() => {
    if (!jobId) return
    let stop = false
    async function poll() {
      while (!stop) {
        try {
          const j = await getMapping(jobId!)
          if (stop) return
          setJob(j)
          if (j.status !== 'running') {
            if (j.status === 'done' && j.result) {
              setLastMapping({
                jobId: jobId!,
                sourceName: j.result.source_name,
                targetName: j.result.target_name,
                summary: j.result.summary,
              })
            }
            return
          }
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

  async function handleDelete(id: string) {
    try {
      await deleteFramework(id)
      if (source === id) setSource(null)
      if (target === id) setTarget(null)
      loadFrameworks()
    } catch (e: any) {
      setError(e.message)
    }
  }

  async function run() {
    setError(null)
    if (!hasCreds()) {
      setError('Configurez votre clé API Azure (bouton Paramètres) avant de lancer une analyse.')
      return
    }
    if (!source || !target) return
    try {
      const id = await startMapping(source, target, entityTypes)
      setJob({ id, kind: 'mapping', status: 'running', stage: '', error: '', result: null })
      setJobId(id)
    } catch (e: any) {
      setError(e.message)
    }
  }

  const running = job?.status === 'running'
  const result = job?.status === 'done' ? job.result : null
  const ready = Boolean(source && target && entityTypes.length > 0) && !running

  return (
    <div className="flex flex-col gap-4">
      <h2 className="text-2xl font-bold text-[#451DC7]">Sélectionnez vos frameworks cybersécurité</h2>

      <Grid
        title="📌 Framework SOURCE (Exigences à mapper)"
        subtitle="Le référentiel dont vous voulez vérifier la couverture."
        frameworks={frameworks}
        selected={source}
        onSelect={setSource}
        onImport={() => setImportOpen(true)}
        onDelete={handleDelete}
      />
      <Grid
        title="🎯 Framework CIBLE (Référence de conformité)"
        subtitle="Le référentiel de comparaison."
        frameworks={frameworks}
        selected={target}
        onSelect={setTarget}
        onImport={() => setImportOpen(true)}
        onDelete={handleDelete}
      />

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">{error}</div>
      )}

      <hr className="my-2 border-gray-200" />

      <div className="rounded-xl border border-gray-200 bg-gray-50 p-4">
        <h3 className="text-sm font-semibold text-[#451DC7]">Type d'entité concernée</h3>
        <p className="mt-0.5 text-xs text-gray-500">
          Certaines exigences NIS2 ne s'appliquent qu'aux entités essentielles ou importantes.
        </p>
        <div className="mt-3 flex gap-6">
          <label className="flex cursor-pointer items-center gap-2">
            <input
              type="checkbox"
              checked={entityTypes.includes('essential')}
              onChange={() => toggleEntityType('essential')}
              className="accent-indigo-600"
            />
            <span className="text-sm font-medium text-gray-700">Entité Essentielle</span>
          </label>
          <label className="flex cursor-pointer items-center gap-2">
            <input
              type="checkbox"
              checked={entityTypes.includes('important')}
              onChange={() => toggleEntityType('important')}
              className="accent-indigo-600"
            />
            <span className="text-sm font-medium text-gray-700">Entité Importante</span>
          </label>
        </div>
        {entityTypes.length === 0 && (
          <p className="mt-2 text-xs text-red-500">Sélectionnez au moins un type d'entité.</p>
        )}
      </div>

      {running ? (
        <div className="flex items-center gap-3 rounded-xl border border-indigo-200 bg-indigo-50 px-4 py-3">
          <Spinner />
          <span className="text-[#451DC7]">{job?.stage || 'Analyse en cours…'}</span>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          <div>
            <button
              onClick={run}
              disabled={!ready}
              className="rounded-lg bg-indigo-600 px-5 py-2.5 font-medium text-white transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-40"
            >
              ▶ Lancer l'analyse
            </button>
            {!source || !target ? (
              <p className="mt-1 text-xs text-gray-400">
                Sélectionnez un framework source et un framework cible.
              </p>
            ) : null}
          </div>

          {result && jobId && (
            <ResultCard result={result} jobId={jobId} onBuildBaseline={() => navigate('/baseline')} />
          )}
        </div>
      )}

      {importOpen && <ImportModal onClose={() => setImportOpen(false)} onImported={loadFrameworks} />}
    </div>
  )
}

function Grid({
  title,
  subtitle,
  frameworks,
  selected,
  onSelect,
  onImport,
  onDelete,
}: {
  title: string
  subtitle: string
  frameworks: Framework[]
  selected: string | null
  onSelect: (id: string) => void
  onImport: () => void
  onDelete: (id: string) => void
}) {
  return (
    <div>
      <h3 className="mt-2 text-lg font-semibold text-[#451DC7]">{title}</h3>
      <p className="text-xs text-gray-500">{subtitle}</p>
      <div className="mt-3 flex flex-wrap gap-4">
        {frameworks.map((fw) => (
          <FrameworkCard
            key={fw.id}
            fw={fw}
            selected={fw.id === selected}
            onClick={() => onSelect(fw.id)}
            onDelete={fw.custom ? () => onDelete(fw.id) : undefined}
          />
        ))}
        <ImportFrameworkCard onClick={onImport} />
      </div>
    </div>
  )
}

function ResultCard({
  result,
  jobId,
  onBuildBaseline,
}: {
  result: any
  jobId: string
  onBuildBaseline: () => void
}) {
  const s = result.summary || {}
  return (
    <div className="rounded-xl border border-green-200 bg-green-50 p-5">
      <h3 className="text-lg font-bold text-green-700">✅ Analyse terminée</h3>
      <div className="mt-2 flex gap-8">
        <Kpi label="Couverture moyenne" value={`${s.average_coverage ?? 0}%`} />
        <Kpi label="Décisions analysées" value={s.atomic_decisions ?? 0} />
        <Kpi label="Écarts" value={s.gaps ?? 0} />
      </div>
      <div className="mt-4 flex flex-wrap gap-2">
        <a
          href={mappingDownloadUrl(jobId, 'excel')}
          className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700"
        >
          ⬇ Télécharger Excel
        </a>
        <a
          href={mappingDownloadUrl(jobId, 'pdf')}
          className="rounded-lg border border-indigo-500 px-4 py-2 text-sm text-indigo-600 hover:bg-indigo-50"
        >
          ⬇ Télécharger PDF
        </a>
        <button
          onClick={onBuildBaseline}
          className="rounded-lg px-4 py-2 text-sm font-medium text-indigo-600 hover:bg-indigo-100"
        >
          → Construire la baseline
        </button>
      </div>
    </div>
  )
}

function Kpi({ label, value }: { label: string; value: string | number }) {
  return (
    <div>
      <div className="text-2xl font-bold text-[#451DC7]">{value}</div>
      <div className="text-xs text-gray-500">{label}</div>
    </div>
  )
}

export function Spinner() {
  return <div className="h-6 w-6 animate-spin rounded-full border-2 border-indigo-300 border-t-indigo-600" />
}
