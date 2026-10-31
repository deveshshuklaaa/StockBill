import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

export default function ProtectedRoute() {
  const { token, loading } = useAuth()
  const location = useLocation()
  if (loading) return <div className="loading-screen">Checking your session...</div>
  return token ? <Outlet /> : <Navigate to="/login" state={{ from: location }} replace />
}
