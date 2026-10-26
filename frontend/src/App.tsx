import { BrowserRouter, Routes, Route, Navigate, useLocation, Outlet } from 'react-router-dom'
import { AuthProvider, useAuth } from '@/contexts/AuthContext'
import { ToastProvider } from '@/contexts/ToastContext'
import { RecorderProvider } from '@/contexts/RecorderContext'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import AppShell from '@/components/layout/AppShell'
import LoginPage from '@/pages/LoginPage'
import ForcePasswordChangePage from '@/pages/ForcePasswordChangePage'
import RecordingsListPage from '@/pages/RecordingsListPage'
import RecordingDetailPage from '@/pages/RecordingDetailPage'
import UploadPage from '@/pages/UploadPage'
import RecordPage from '@/pages/RecordPage'
import SearchPage from '@/pages/SearchPage'
import AdminPage from '@/pages/AdminPage'
import NotFoundPage from '@/pages/NotFoundPage'
import { Spinner } from '@/components/ui/Spinner'

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth()
  const location = useLocation()
  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Spinner className="h-8 w-8" />
      </div>
    )
  }
  if (!user) return <Navigate to="/login" replace />
  if (user.must_change_password && location.pathname !== '/force-password-change') {
    return <Navigate to="/force-password-change" replace />
  }
  return <>{children}</>
}

function AdminRoute({ children }: { children: React.ReactNode }) {
  const { user } = useAuth()
  if (!user?.is_admin) return <Navigate to="/" replace />
  return <>{children}</>
}

// Animated page wrapper — re-mounts on route change, triggering page-in animation
function AnimatedPage() {
  const location = useLocation()
  return (
    <div key={location.pathname} className="animate-page-in">
      <Outlet />
    </div>
  )
}

// Protected layout with AppShell
// RecorderProvider stă deasupra paginilor: înregistrarea din browser continuă la navigare
function ProtectedLayout() {
  return (
    <ProtectedRoute>
      <RecorderProvider>
        <AppShell>
          <AnimatedPage />
        </AppShell>
      </RecorderProvider>
    </ProtectedRoute>
  )
}

function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/force-password-change"
        element={
          <ProtectedRoute>
            <ForcePasswordChangePage />
          </ProtectedRoute>
        }
      />
      <Route element={<ProtectedLayout />}>
        <Route path="/" element={<RecordingsListPage />} />
        <Route path="/recordings/upload" element={<UploadPage />} />
        <Route path="/recordings/record" element={<RecordPage />} />
        {/* adresa veche, din semne de carte */}
        <Route path="/recordings/new" element={<Navigate to="/recordings/upload" replace />} />
        <Route path="/recordings/:id" element={<RecordingDetailPage />} />
        <Route path="/search" element={<SearchPage />} />
        <Route
          path="/admin"
          element={
            <AdminRoute>
              <AdminPage />
            </AdminRoute>
          }
        />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  )
}

export default function App() {
  return (
    <ErrorBoundary>
      <BrowserRouter>
        <AuthProvider>
          <ToastProvider>
            <AppRoutes />
          </ToastProvider>
        </AuthProvider>
      </BrowserRouter>
    </ErrorBoundary>
  )
}
