import { useNavigate } from 'react-router-dom'

export default function Baseline() {
  const navigate = useNavigate()

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
      <div className="flex items-center gap-3">
        <h2 className="text-2xl font-bold text-[#451DC7]">My baselines</h2>
        <span className="rounded-full bg-gray-200 px-2.5 py-1 text-xs font-medium text-gray-600">Coming soon</span>
      </div>

      <p className="mt-3 text-sm text-gray-600">
        This feature is not available yet. Future versions will let you generate and manage consolidated compliance
        baselines from completed regulatory mappings.
      </p>

      <button
        onClick={() => navigate('/')}
        className="mt-5 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700"
      >
        ＋ New mapping
      </button>
    </div>
  )
}
