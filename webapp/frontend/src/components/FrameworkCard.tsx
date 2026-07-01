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
      <div
        title={fw.description}
        className="w-48 cursor-not-allowed rounded-xl border border-gray-100 bg-gray-50 p-4 opacity-50"
      >
        <div className="font-semibold leading-tight text-gray-400">{fw.display_name}</div>
        <div className="text-xs text-gray-400">{fw.country}</div>
        <span className="mt-2 inline-block rounded bg-gray-200 px-2 py-0.5 text-xs text-gray-400">
          Bientôt
        </span>
      </div>
    )
  }

  return (
    <div className="relative">
      <button
        onClick={onClick}
        className={`w-48 rounded-xl border p-4 text-left transition-all ${
          selected
            ? 'border-2 border-indigo-500 bg-indigo-50 shadow-md'
            : 'border-gray-200 bg-white hover:shadow-md'
        }`}
      >
        <div className="mt-1 font-semibold leading-tight text-[#451DC7]">{fw.display_name}</div>
        <div className="text-xs text-gray-500">{fw.requirement_count} exigences</div>
        <span
          className={`mt-2 inline-block rounded px-2 py-0.5 text-xs ${
            selected ? 'bg-indigo-600 text-white' : fw.custom ? 'bg-violet-100 text-violet-700' : 'bg-green-100 text-green-700'
          }`}
        >
          {selected ? '✓ Sélectionné' : fw.custom ? 'Importé' : 'Disponible'}
        </span>
      </button>
      {fw.custom && onDelete && (
        <button
          onClick={(e) => {
            e.stopPropagation()
            onDelete()
          }}
          title="Supprimer ce framework"
          className="absolute right-1.5 top-1.5 h-6 w-6 rounded-full bg-white/90 text-gray-400 shadow-sm transition hover:bg-red-50 hover:text-red-600"
        >
          ×
        </button>
      )}
    </div>
  )
}

export function ImportFrameworkCard({ onClick }: { onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="w-48 rounded-xl border border-dashed border-gray-300 bg-gray-50 p-4 text-left transition hover:border-indigo-400 hover:bg-indigo-50/40"
    >
      <div className="text-3xl text-gray-400">＋</div>
      <div className="mt-1 font-semibold leading-tight text-gray-600">Importer un framework</div>
      <div className="text-xs text-gray-400">Ajoutez votre propre référentiel</div>
      <span className="mt-2 inline-block rounded bg-indigo-100 px-2 py-0.5 text-xs text-indigo-700">Importer</span>
    </button>
  )
}
