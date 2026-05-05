// frontend/src/pages/DashboardPage.tsx
export function DashboardPage() {
  return (
    <div className="p-6">
      <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
      <p className="mt-2 text-gray-500">Morning briefing and alerts coming in Phase 2 & 3.</p>
      <div className="mt-6 grid grid-cols-3 gap-4">
        {['Active Trades', 'Open Alerts', 'Pending Review'].map(label => (
          <div key={label} className="bg-white rounded-lg border border-gray-200 p-4">
            <p className="text-sm text-gray-500">{label}</p>
            <p className="text-3xl font-bold text-gray-900 mt-1">—</p>
          </div>
        ))}
      </div>
    </div>
  )
}
