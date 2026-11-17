import { createContext, useContext, useEffect, useState } from 'react'
import api, { LOGOUT_PATH, SESSION_EXPIRED_EVENT, apiErrorMessage } from '../api/client'

const AuthContext = createContext(null)
const TOKEN_KEY = 'stockbill_token'
const USER_KEY = 'stockbill_user'

function normalizeUser(data) {
  return data ? { ...data, role: (data.role || '').toLowerCase() } : null
}

export function AuthProvider({ children }) {
  const [token, setToken] = useState(() => sessionStorage.getItem(TOKEN_KEY))
  const [user, setUser] = useState(() => {
    const stored = sessionStorage.getItem(USER_KEY)
    return normalizeUser(stored ? JSON.parse(stored) : null)
  })
  const [loading, setLoading] = useState(Boolean(token && !user))
  const [authError, setAuthError] = useState('')

  useEffect(() => {
    if (!token || user) return
    api.get('/auth/me/')
      .then(({ data }) => {
        setUser(normalizeUser(data))
        sessionStorage.setItem(USER_KEY, JSON.stringify(data))
      })
      .catch(() => clearSession())
      .finally(() => setLoading(false))
  }, [token, user])

  // Any API call answered with 401 (token expired or revoked) signs out;
  // ProtectedRoute then redirects to /login.
  useEffect(() => {
    window.addEventListener(SESSION_EXPIRED_EVENT, clearSession)
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, clearSession)
  }, [])

  async function login(username, password) {
    setAuthError('')
    try {
      const { data } = await api.post('/auth/token/', { username, password })
      sessionStorage.setItem(TOKEN_KEY, data.token)
      setToken(data.token)
      const me = await api.get('/auth/me/')
      sessionStorage.setItem(USER_KEY, JSON.stringify(me.data))
      setUser(normalizeUser(me.data))
    } catch (error) {
      setAuthError(apiErrorMessage(error) || 'Login failed. Check your credentials.')
      throw error
    }
  }

  // Sign out on this device: revoke this device's token on the server
  // (other devices stay signed in), then clear the session locally. The
  // local sign-out never waits for, or depends on, the server answering.
  function logout() {
    const current = sessionStorage.getItem(TOKEN_KEY)
    if (current) {
      api.post(LOGOUT_PATH, null, { headers: { Authorization: `Token ${current}` } }).catch(() => {})
    }
    clearSession()
  }

  function clearSession() {
    sessionStorage.removeItem(TOKEN_KEY)
    sessionStorage.removeItem(USER_KEY)
    setToken(null)
    setUser(null)
    setLoading(false)
  }

  return (
    <AuthContext.Provider value={{ token, user, loading, authError, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
