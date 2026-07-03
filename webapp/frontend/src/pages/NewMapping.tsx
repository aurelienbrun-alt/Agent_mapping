import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import {
  deleteFramework,
  getFrameworks,
  getMapping,
  mappingDownloadUrl,
  startMapping,
  type Framework,
  type Job,
} from '../api/client'
import { FrameworkCard, ImportFrameworkCard } from '../components/FrameworkCard'
import ImportModal from '../components/ImportModal'
import { useAppState } from '../lib/appState'
import { hasCreds } from '../lib/settings'

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
  const [searchParams, setSearchParams] = useSearchParams()

  const loadFrameworks = useCallback(() => {
    getFrameworks()
      .then(setFrameworks)
      .catch((e) => setError(e.message))
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
  }, [jobId, setLastMapping])

  function toggleEntityType(t: string) {
    setEntityTypes((prev) => (prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t]))
  }

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
      setError('Configure your Azure API key in Azure OpenAI Configuration before running an analysis.')
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
      <h2 className="text-2xl font-bold text-[#451DC7]">Select your cybersecurity frameworks</h2>

      <Grid
        title="SOURCE framework (requirements to map)"
        subtitle="The reference framework whose coverage you want to assess."
        frameworks={frameworks}
        selected={source}
        onSelect={setSource}
        onImport={() => setImportOpen(true)}
        onDelete={handleDelete}
      />

      <Grid
        title="TARGET framework (coverage reference)"
        subtitle="The framework used as the comparison target."
        frameworks={frameworks}
        selected={target}
        onSelect={setTarget}
        onImport={() => setImportOpen(true)}
        onDelete={handleDelete}
      />

      {error && <p className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</p>}

      <hr />

      <section className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
        <h3 className="font-semibold text-gray-900">Applicable entity type</h3>
        <p className="mt-1 text-sm text-gray-500">Some requirements only apply to essential or important entities.</p>

        <div className="mt-3 flex gap-4 text-sm text-gray-700">
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={entityTypes.includes('essential')}
              onChange={() => toggleEntityType('essential')}
              className="accent-indigo-600"
            />
            Essential entity
          </label>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={entityTypes.includes('important')}
              onChange={() => toggleEntityType('important')}
              className="accent-indigo-600"
            />
            Important entity
          </label>
        </div>

        {entityTypes.length === 0 && <p className="mt-2 text-sm text-red-600">Select at least one entity type.</p>}
      </section>

      {running ? (
        <div className="flex items-center gap-3 rounded-xl border border-indigo-100 bg-indigo-50 p-4 text-indigo-700">
          <Spinner />
          <span>{job?.stage || 'Analysis in progress…'}</span>
        </div>
      ) : (
        <div className="flex items-center gap-3">
          <button
            onClick={run}
            disabled={!ready}
            className="rounded-lg bg-indigo-600 px-5 py-2 text-sm font-medium text-white transition hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            ▶ Run analysis
          </button>
          {!source || !target ? <p className="text-sm text-gray-500">Select a source framework and a target framework.</p> : null}
        </div>
      )}

      {result && jobId && <ResultCard result={result} jobId={jobId} />}

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
    <section className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
      <h3 className="font-semibold text-gray-900">{title}</h3>
      <p className="mt-1 text-sm text-gray-500">{subtitle}</p>

      <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {frameworks.map((fw) => (
          <FrameworkCard
            key={fw.id}
            fw={fw}
            selected={selected === fw.id}
            onClick={() => onSelect(fw.id)}
            onDelete={fw.custom ? () => onDelete(fw.id) : undefined}
          />
        ))}
        <ImportFrameworkCard onClick={onImport} />
      </div>
    </section>
  )
}

function ResultCard({ result, jobId }: { result: any; jobId: string }) {
  const s = result.summary || {}

  return (
    <section className="rounded-xl border border-green-200 bg-green-50 p-4 shadow-sm">
      <h3 className="font-semibold text-green-800">✅ Analysis completed</h3>

      <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Kpi label="Source requirements" value={s.source_requirements ?? s.source_total ?? '-'} />
        <Kpi label="Target requirements" value={s.target_requirements ?? s.target_total ?? '-'} />
        <Kpi label="Mapped items" value={s.mapped ?? s.mapped_items ?? '-'} />
        <Kpi label="Coverage" value={s.coverage_percent != null ? `${s.coverage_percent}%` : '-'} />
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        <a
          href={mappingDownloadUrl(jobId, 'excel')}
          className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700"
        >
          ⬇ Download Excel
        </a>
        <a
          href={mappingDownloadUrl(jobId, 'pdf')}
          className="rounded-lg border border-indigo-500 px-4 py-2 text-sm font-medium text-indigo-600 hover:bg-indigo-50"
        >
          ⬇ Download PDF
        </a>
      </div>
    </section>
  )
}

function Kpi({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-lg bg-white p-3 text-center shadow-sm">
      <div className="text-lg font-bold text-[#451DC7]">{value}</div>
      <div className="text-xs text-gray-500">{label}</div>
    </div>
  )
}

export function Spinner() {
  return (
    <span className="inline-block h-5 w-5 animate-spin rounded-full border-2 border-indigo-300 border-t-indigo-700" />
  )
}
