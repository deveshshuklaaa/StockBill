import { render, screen, waitFor } from '@testing-library/react'
import { AxiosError } from 'axios'
import { useEffect } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import api, { SESSION_EXPIRED_EVENT, resolveApiBaseUrl } from '../api/client'
import ProtectedRoute from '../components/ProtectedRoute'
import { AuthProvider } from '../context/AuthContext'

describe('resolveApiBaseUrl', () => {
  it('uses the same-origin /api in a production build', () => {
    expect(resolveApiBaseUrl({ PROD: true, DEV: false })).toBe('/api')
  })

  it('uses the local Django server in development', () => {
    expect(resolveApiBaseUrl({ PROD: false, DEV: true })).toBe('http://localhost:8000/api')
  })

  it('lets VITE_API_BASE_URL override both', () => {
    expect(resolveApiBaseUrl({ PROD: true, VITE_API_BASE_URL: 'http://127.0.0.1:8000/api' })).toBe('http://127.0.0.1:8000/api')
  })
})

function respondWith(status) {
  return async (config) => {
    const response = { status, data: { detail: 'Your session has expired. Please log in again.' }, headers: {}, config }
    throw new AxiosError(`Request failed with status code ${status}`, 'ERR_BAD_REQUEST', config, null, response)
  }
}

function CustomersProbe() {
  useEffect(() => {
    api.get('/customers/').catch(() => {})
  }, [])
  return <div>Customers page</div>
}

describe('expired session', () => {
  let originalAdapter

  beforeEach(() => {
    originalAdapter = api.defaults.adapter
    sessionStorage.setItem('stockbill_token', 'old-token')
    sessionStorage.setItem('stockbill_user', JSON.stringify({ id: 1, username: 'clerk', role: 'staff' }))
  })

  afterEach(() => {
    api.defaults.adapter = originalAdapter
    sessionStorage.clear()
    vi.restoreAllMocks()
  })

  it('a 401 from any API call clears the session and lands on the login page', async () => {
    api.defaults.adapter = respondWith(401)

    render(
      <AuthProvider>
        <MemoryRouter initialEntries={['/customers']}>
          <Routes>
            <Route path="/login" element={<div>Login page</div>} />
            <Route element={<ProtectedRoute />}>
              <Route path="/customers" element={<CustomersProbe />} />
            </Route>
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    )

    expect(await screen.findByText('Login page')).toBeInTheDocument()
    expect(sessionStorage.getItem('stockbill_token')).toBeNull()
    expect(sessionStorage.getItem('stockbill_user')).toBeNull()
  })

  it('a 403 (wrong role) does not sign the user out', async () => {
    api.defaults.adapter = respondWith(403)
    const listener = vi.fn()
    window.addEventListener(SESSION_EXPIRED_EVENT, listener)

    await expect(api.get('/users/')).rejects.toMatchObject({ response: { status: 403 } })
    window.removeEventListener(SESSION_EXPIRED_EVENT, listener)
    expect(listener).not.toHaveBeenCalled()
    expect(sessionStorage.getItem('stockbill_token')).toBe('old-token')
  })

  it('a 401 from the login request itself does not fire the session-expired event', async () => {
    api.defaults.adapter = respondWith(401)
    const listener = vi.fn()
    window.addEventListener(SESSION_EXPIRED_EVENT, listener)

    await expect(api.post('/auth/token/', { username: 'x', password: 'y' })).rejects.toBeTruthy()
    await expect(api.get('/customers/')).rejects.toBeTruthy()
    window.removeEventListener(SESSION_EXPIRED_EVENT, listener)
    await waitFor(() => expect(listener).toHaveBeenCalledTimes(1))
  })
})
