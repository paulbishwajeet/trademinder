// frontend/src/components/Layout/NotFound.tsx
import { Link } from 'react-router-dom'

export function NotFound({ title = 'Page not found', message }: { title?: string; message?: string }) {
  return (
    <div className="p-10 max-w-lg">
      <h1 className="text-xl font-semibold text-gray-900">{title}</h1>
      {message && <p className="mt-2 text-sm text-gray-600">{message}</p>}
      <Link to="/" className="mt-4 inline-block text-sm text-blue-600 hover:underline">← Back to Dashboard</Link>
    </div>
  )
}
