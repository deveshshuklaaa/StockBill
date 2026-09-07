import { createContext, useContext, useEffect, useState } from 'react'
import api, { apiErrorMessage } from '../api/client'

const AuthContext = createContext(null)
const TOKEN_KEY = 'stockbill_token'
const USER_KEY = 'stockbill_user'

export function AuthProvider({ children }) {
  const [token, setToken] = useState(() => sessionStorage.getItem(TOKEN_KEY))
  const [user, setUser] = useState(() => {
    const stored = sessionStorage.getItem(USER_KEY)
    return stored ? JSON.parse(stored) : null
  })
  const [loading, setLoading] = useState(Boolean(token && !user))
  const [authError, setAuthError] = useState('')

  useEffect(() => {
    if (!token || user) return
    api.get('/auth/me/')
      .then(({ data }) => {
        setUser(data)
        sessionStorage.setItem(USER_KEY, JSON.stringify(data))
      })
      .catch(() => logout())
      .finally(() => setLoading(false))
  }, [token, user])

  async function login(username, password) {
    setAuthError('')
    try {
      const { data } = await api.post('/auth/token/', { username, password })
      sessionStorage.setItem(TOKEN_KEY, data.token)
      setToken(data.token)
      const me = await api.get('/auth/me/')
      sessionStorage.setItem(USER_KEY, JSON.stringify(me.data))
      setUser(me.data)
    } catch (error) {
      setAuthError(apiErrorMessage(error) || 'Login failed. Check your credentials.')
      throw error
    }
  }

  function logout() {
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
