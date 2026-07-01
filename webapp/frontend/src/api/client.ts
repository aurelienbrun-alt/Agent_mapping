import { getCreds, type Creds } from '../lib/settings'

export interface Framework {
  id: string
  display_name: string
  country: string
  requirement_count: number
  description: string
  available: boolean
  custom: boolean
}

export interface Category {
  name: string
  number: string
  definition: string
}

export interface OutputFile {
  name: string
  size_kb: number
  modified: string
  sheets: string[]
}

export interface OutputSheet {
  name: string
  title: string
  headers: string[]
  rows: string[][]
  total_rows: number
  truncated: boolean
}

export interface OutputWorkbook {
  name: string
  sheets: OutputSheet[]
}

export type JobStatus = 'running' | 'done' | 'error'

export interface Job {
  id: string
  kind: string
  status: JobStatus
  stage: string
  error: string
  result: any | null
}

function credsHeaders(creds?: Creds): Record<string, string> {
  const c = creds ?? getCreds()
  const h: Record<string, string> = {}
  if (c.apiKey) h['X-Azure-Api-Key'] = c.apiKey
  if (c.endpoint) h['X-Azure-Endpoint'] = c.endpoint
  if (c.apiVersion) h['X-Azure-Api-Version'] = c.apiVersion
  return h
}

async function jsonOrThrow(res: Response): Promise<any> {
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      if (body?.detail) detail = body.detail
    } catch {
      /* ignore */
    }
    throw new Error(detail)
  }
  return res.json()
}

export async function getFrameworks(): Promise<Framework[]> {
  return jsonOrThrow(await fetch('/api/frameworks'))
}

export async function getCategories(): Promise<Category[]> {
  return jsonOrThrow(await fetch('/api/categories'))
}

export async function importFramework(
  file: File,
  meta: { display_name: string; country: string },
): Promise<Framework> {
  const fd = new FormData()
  fd.append('file', file)
  fd.append('display_name', meta.display_name)
  fd.append('country', meta.country)
  // No Content-Type header: the browser sets the multipart boundary.
  return jsonOrThrow(await fetch('/api/frameworks/import', { method: 'POST', body: fd }))
}

export async function deleteFramework(id: string): Promise<void> {
  await jsonOrThrow(await fetch(`/api/frameworks/${id}`, { method: 'DELETE' }))
}

export async function getOutputs(): Promise<OutputFile[]> {
  return jsonOrThrow(await fetch('/api/outputs'))
}

export async function getOutputView(name: string): Promise<OutputWorkbook> {
  return jsonOrThrow(await fetch(`/api/outputs/${encodeURIComponent(name)}/view`))
}

export function outputDownloadUrl(name: string): string {
  return `/api/outputs/${encodeURIComponent(name)}/download`
}

export async function testConnection(creds: Creds): Promise<{ ok: boolean; message: string }> {
  return jsonOrThrow(
    await fetch('/api/settings/test', { method: 'POST', headers: credsHeaders(creds) }),
  )
}

export async function startMapping(sourceId: string, targetId: string, entityTypes: string[]): Promise<string> {
  const data = await jsonOrThrow(
    await fetch('/api/mappings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...credsHeaders() },
      body: JSON.stringify({ source_id: sourceId, target_id: targetId, entity_types: entityTypes }),
    }),
  )
  return data.job_id
}

export async function getMapping(jobId: string): Promise<Job> {
  return jsonOrThrow(await fetch(`/api/mappings/${jobId}`))
}

export function mappingDownloadUrl(jobId: string, fmt: 'excel' | 'pdf'): string {
  return `/api/mappings/${jobId}/download?fmt=${fmt}`
}

export async function startBaseline(mappingJobId: string, categories: string[]): Promise<string> {
  const data = await jsonOrThrow(
    await fetch('/api/baselines', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mapping_job_id: mappingJobId, categories }),
    }),
  )
  return data.job_id
}

export async function getBaseline(jobId: string): Promise<Job> {
  return jsonOrThrow(await fetch(`/api/baselines/${jobId}`))
}

export function baselineDownloadUrl(jobId: string): string {
  return `/api/baselines/${jobId}/download`
}
