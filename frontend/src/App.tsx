// frontend/src/App.tsx
import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom'
import { DashboardPage } from './pages/DashboardPage'
import { TradesPage } from './pages/TradesPage'
import { TradeDetailPage } from './pages/TradeDetailPage'
import { ScannerPage } from './pages/ScannerPage'

function NavItem({ to, label }: { to: string; label: string }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        `px-4 py-2 text-sm font-medium rounded ${isActive ? 'bg-blue-600 text-white' : 'text-gray-600 hover:bg-gray-100'}`
      }
    >
      {label}
    </NavLink>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen bg-gray-50">
        <nav className="bg-white border-b border-gray-200 px-6 py-3 flex items-center gap-2">
          <span className="font-bold text-gray-900 mr-4">TradeMinder</span>
          <NavItem to="/" label="Dashboard" />
          <NavItem to="/trades" label="Trades" />
          <NavItem to="/scanner" label="Scanner" />
        </nav>
        <main>
          <Routes>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/trades" element={<TradesPage />} />
            <Route path="/trades/:id" element={<TradeDetailPage />} />
            <Route path="/scanner" element={<ScannerPage />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  )
}
