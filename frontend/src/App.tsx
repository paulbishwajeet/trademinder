// frontend/src/App.tsx
import { BrowserRouter, Navigate, Outlet, Route, Routes } from 'react-router-dom'
import { AccountsProvider } from './context/AccountsContext'
import { Sidebar } from './components/Layout/Sidebar'
import { AccountLayout } from './components/Layout/AccountLayout'
import { NotFound } from './components/Layout/NotFound'
import { DashboardPage } from './pages/DashboardPage'
import { TradesPage } from './pages/TradesPage'
import { TradeDetailPage } from './pages/TradeDetailPage'
import { MarginDashboardPage } from './pages/MarginDashboardPage'
import { ScannerPage } from './pages/ScannerPage'
import { WheelDashboardPage } from './pages/WheelDashboardPage'
import { SpreadsDashboardPage } from './pages/SpreadsDashboardPage'
import { ScreenerPage } from './pages/ScreenerPage'
import { ChainPage } from './pages/ChainPage'
import { SettingsAccountsPage } from './pages/SettingsAccountsPage'
import { LegacyAccountRedirect, LegacyResearchRedirect, LegacyTradeRedirect } from './pages/LegacyRedirects'

function AppShell() {
  return (
    <div className="flex min-h-screen bg-gray-50">
      <Sidebar />
      <main className="min-w-0 flex-1">
        <Outlet />
      </main>
    </div>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <AccountsProvider>
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<DashboardPage />} />

            {/* Account container: every page shows exactly one account, taken from the URL. */}
            <Route path="accounts/:accountId" element={<AccountLayout />}>
              <Route index element={<Navigate to="wheel" replace />} />
              <Route path="trades" element={<TradesPage />} />
              <Route path="trades/:id" element={<TradeDetailPage />} />
              <Route path="wheel" element={<WheelDashboardPage />} />
              <Route path="spreads" element={<SpreadsDashboardPage />} />
              <Route path="margin" element={<MarginDashboardPage />} />
              <Route path="screener" element={<ScreenerPage />} />
              <Route path="chain" element={<ChainPage />} />
              <Route path="scanner" element={<ScannerPage />} />
              <Route path="*" element={<NotFound />} />
            </Route>

            {/* Research: not tied to an account. */}
            <Route path="research">
              <Route index element={<Navigate to="screener" replace />} />
              <Route path="screener" element={<ScreenerPage />} />
              <Route path="chain" element={<ChainPage />} />
              <Route path="scanner" element={<ScannerPage />} />
            </Route>

            <Route path="settings">
              <Route index element={<Navigate to="accounts" replace />} />
              <Route path="accounts" element={<SettingsAccountsPage />} />
            </Route>

            {/* Legacy flat URLs */}
            <Route path="trades" element={<LegacyAccountRedirect page="trades" />} />
            <Route path="trades/:tradeId" element={<LegacyTradeRedirect />} />
            <Route path="wheel" element={<LegacyAccountRedirect page="wheel" />} />
            <Route path="spreads" element={<LegacyAccountRedirect page="spreads" />} />
            <Route path="margin" element={<LegacyAccountRedirect page="margin" />} />
            <Route path="screener" element={<LegacyResearchRedirect page="screener" />} />
            <Route path="chain" element={<LegacyResearchRedirect page="chain" />} />
            <Route path="scanner" element={<LegacyResearchRedirect page="scanner" />} />

            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
      </AccountsProvider>
    </BrowserRouter>
  )
}
