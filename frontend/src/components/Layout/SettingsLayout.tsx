// frontend/src/components/Layout/SettingsLayout.tsx
import { NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'

const tab = ({ isActive }: { isActive: boolean }) =>
  `border-b-2 px-1 pb-2 text-sm ${isActive ? 'border-blue-600 font-medium text-blue-700' : 'border-transparent text-gray-500 hover:text-gray-800'}`

export function SettingsLayout() {
  const isAdmin = useAuth().user?.role === 'admin'
  return (
    <div className="max-w-5xl p-6">
      <h1 className="text-2xl font-bold text-gray-900">Settings</h1>
      <nav className="mt-4 flex gap-6 border-b border-gray-200">
        <NavLink to="/settings/accounts" className={tab}>Accounts</NavLink>
        <NavLink to="/settings/extensions" className={tab}>Connected extensions</NavLink>
        {isAdmin && <NavLink to="/settings/market-data" className={tab}>Market data</NavLink>}
      </nav>
      <div className="mt-5"><Outlet /></div>
    </div>
  )
}
