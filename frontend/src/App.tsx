// frontend/src/App.tsx
import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom'
import { DashboardPage } from './pages/DashboardPage'
import { TradesPage } from './pages/TradesPage'
import { TradeDetailPage } from './pages/TradeDetailPage'
import { MarginDashboardPage } from './pages/MarginDashboardPage'
import { ScannerPage } from './pages/ScannerPage'
import { WheelDashboardPage } from './pages/WheelDashboardPage'
import { SpreadsDashboardPage } from './pages/SpreadsDashboardPage'
import { ScreenerPage } from './pages/ScreenerPage'

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
          <NavItem to="/wheel" label="WHEEL" />
          <NavItem to="/spreads" label="Spreads" />
          <NavItem to="/margin" label="Margin" />
          <NavItem to="/scanner" label="Scanner" />
          <NavItem to="/screener" label="Screener" />
        </nav>
        <main>
          <Routes>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/trades" element={<TradesPage />} />
            <Route path="/trades/:id" element={<TradeDetailPage />} />
            <Route path="/wheel" element={<WheelDashboardPage />} />
            <Route path="/spreads" element={<SpreadsDashboardPage />} />
            <Route path="/margin" element={<MarginDashboardPage />} />
            <Route path="/scanner" element={<ScannerPage />} />
            <Route path="/screener" element={<ScreenerPage />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  )
}
