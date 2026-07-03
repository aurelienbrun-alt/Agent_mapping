import type { Framework } from '../api/client'

export function FrameworkCard({
  fw,
  selected,
  onClick,
  onDelete,
}: {
  fw: Framework
  selected: boolean
  onClick: () => void
  onDelete?: () => void
}) {
  if (!fw.available) {
    return (
      <div className="rounded-xl border border-dashed border-gray-300 bg-gray-50 p-4 text-gray-400">
        <div className="font-semibold">{fw.display_name}</div>
        <div className="text-xs">{fw.country}</div>
        <span className="mt-3 inline-block rounded bg-gray-200 px-2 py-1 text-xs text-gray-500">Coming soon</span>
      </div>
    )
  }

  return (
    <button
      onClick={onClick}
      className={`relative rounded-xl border p-4 text-left transition ${
        selected ? 'border-indigo-600 bg-indigo-50 shadow-sm' : 'border-gray-200 bg-white hover:border-indigo-300 hover:bg-indigo-50/40'
      }`}
    >
      <div className="font-semibold text-gray-900">{fw.display_name}</div>
      <div className="mt-1 text-xs text-gray-500">{fw.country}</div>
      <div className="mt-3 text-xs text-gray-500">{fw.requirement_count} requirements</div>
      <div className="mt-3 text-xs font-medium text-indigo-600">
        {selected ? '✓ Selected' : fw.custom ? 'Imported' : 'Available'}
      </div>

      {fw.custom && onDelete && (
        <button
          onClick={(e) => {
            e.stopPropagation()
            onDelete()
          }}
          title="Delete this framework"
          className="absolute right-1.5 top-1.5 h-6 w-6 rounded-full bg-white/90 text-gray-400 shadow-sm transition hover:bg-red-50 hover:text-red-600"
        >
          ×
        </button>
      )}
    </button>
  )
}

export function ImportFrameworkCard({ onClick }: { onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="rounded-xl border border-dashed border-indigo-300 bg-white p-4 text-left transition hover:border-indigo-500 hover:bg-indigo-50"
    >
      <div className="text-2xl text-indigo-600">＋</div>
      <div className="mt-2 font-semibold text-gray-900">Import a framework</div>
      <div className="mt-1 text-xs text-gray-500">Add your own reference framework</div>
      <div className="mt-3 text-xs font-medium text-indigo-600">Import</div>
    </button>
  )
}
