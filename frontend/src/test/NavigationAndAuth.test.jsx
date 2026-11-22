import { render, screen } from '@testing-library/react'
import api from '../api/client'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import LoginPage from '../pages/LoginPage'
import ProtectedRoute from '../components/ProtectedRoute'
import AppShell from '../components/AppShell'

const mockNavigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  }
})

const mockLogin = vi.fn()
const mockLogout = vi.fn()
let authContextState = {
  token: null,
  user: null,
  loading: false,
  authError: '',
  login: mockLogin,
  logout: mockLogout,
}

vi.mock('../context/AuthContext', () => ({
  useAuth: () => authContextState,
}))

vi.mock('../api/client', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
  },
  apiErrorMessage: vi.fn((err) => err?.response?.data?.detail || 'Login failed.'),
}))

describe('Authentication and Navigation Improvements', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    authContextState = {
      token: null,
      user: null,
      loading: false,
      authError: '',
      login: mockLogin,
      logout: mockLogout,
    }
  })

  describe('Post-Login Redirect to Dashboard', () => {
    it('redirects Admin user to /dashboard after successful login by default', async () => {
      const user = userEvent.setup()
      mockLogin.mockResolvedValueOnce({
        token: 'token-admin',
        user: { id: 1, username: 'admin', role: 'admin' },
      })

      render(
        <MemoryRouter initialEntries={['/login']}>
          <LoginPage />
        </MemoryRouter>
      )

      await user.type(screen.getByLabelText(/username/i), 'admin')
      await user.type(screen.getByLabelText(/password/i), 'secret123')
      await user.click(screen.getByRole('button', { name: /sign in/i }))

      expect(mockLogin).toHaveBeenCalledWith('admin', 'secret123')
      expect(mockNavigate).toHaveBeenCalledWith('/dashboard', { replace: true })
    })

    it('redirects Staff user to /dashboard after successful login by default', async () => {
      const user = userEvent.setup()
      mockLogin.mockResolvedValueOnce({
        token: 'token-staff',
        user: { id: 2, username: 'staff1', role: 'staff' },
      })

      render(
        <MemoryRouter initialEntries={['/login']}>
          <LoginPage />
        </MemoryRouter>
      )

      await user.type(screen.getByLabelText(/username/i), 'staff1')
      await user.type(screen.getByLabelText(/password/i), 'secret123')
      await user.click(screen.getByRole('button', { name: /sign in/i }))

      expect(mockLogin).toHaveBeenCalledWith('staff1', 'secret123')
      expect(mockNavigate).toHaveBeenCalledWith('/dashboard', { replace: true })
    })

    it('lands on /dashboard even if the user was trying to access a specific page', async () => {
      const user = userEvent.setup()
      mockLogin.mockResolvedValueOnce({
        token: 'token-admin',
        user: { id: 1, username: 'admin', role: 'admin' },
      })

      const locationState = { from: { pathname: '/customers' } }

      render(
        <MemoryRouter initialEntries={[{ pathname: '/login', state: locationState }]}>
          <LoginPage />
        </MemoryRouter>
      )

      await user.type(screen.getByLabelText(/username/i), 'admin')
      await user.type(screen.getByLabelText(/password/i), 'secret123')
      await user.click(screen.getByRole('button', { name: /sign in/i }))

      expect(mockNavigate).toHaveBeenCalledWith('/dashboard', { replace: true })
      expect(mockNavigate).not.toHaveBeenCalledWith('/customers', expect.anything())
    })

    it('does not redirect when login credentials are invalid', async () => {
      const user = userEvent.setup()
      mockLogin.mockRejectedValueOnce(new Error('Invalid credentials'))
      authContextState.authError = 'Invalid credentials'

      render(
        <MemoryRouter initialEntries={['/login']}>
          <LoginPage />
        </MemoryRouter>
      )

      await user.type(screen.getByLabelText(/username/i), 'admin')
      await user.type(screen.getByLabelText(/password/i), 'wrongpass')
      await user.click(screen.getByRole('button', { name: /sign in/i }))

      expect(mockLogin).toHaveBeenCalledWith('admin', 'wrongpass')
      expect(mockNavigate).not.toHaveBeenCalled()
      expect(screen.getByText(/invalid credentials/i)).toBeInTheDocument()
    })
  })

  describe('ProtectedRoute Behavior', () => {
    it('redirects unauthenticated users to /login preserving from state', () => {
      authContextState.token = null

      render(
        <MemoryRouter initialEntries={['/products']}>
          <Routes>
            <Route element={<ProtectedRoute />}>
              <Route path="/products" element={<div>Products Content</div>} />
            </Route>
            <Route path="/login" element={<div>Login Page</div>} />
          </Routes>
        </MemoryRouter>
      )

      expect(screen.getByText('Login Page')).toBeInTheDocument()
      expect(screen.queryByText('Products Content')).not.toBeInTheDocument()
    })

    it('renders protected child routes when authenticated', () => {
      authContextState.token = 'valid-token'
      authContextState.user = { id: 1, username: 'admin', role: 'admin' }

      render(
        <MemoryRouter initialEntries={['/products']}>
          <Routes>
            <Route element={<ProtectedRoute />}>
              <Route path="/products" element={<div>Products Content</div>} />
            </Route>
            <Route path="/login" element={<div>Login Page</div>} />
          </Routes>
        </MemoryRouter>
      )

      expect(screen.getByText('Products Content')).toBeInTheDocument()
    })
  })

  describe('StockBill logo as Home Button', () => {
    it('renders the StockBill lockup and the shop name as a link to /dashboard', async () => {
      authContextState.token = 'valid-token'
      authContextState.user = { id: 1, username: 'admin', role: 'admin' }
      api.get.mockImplementation((url) => Promise.resolve(
        url === '/meta/' ? { data: { environment: 'production', business_name: 'Sharma General Store' } } : { data: {} }
      ))

      render(
        <MemoryRouter initialEntries={['/products']}>
          <AppShell />
        </MemoryRouter>
      )

      const logoLink = screen.getByRole('link', { name: /go to dashboard/i })
      expect(logoLink).toBeInTheDocument()
      expect(logoLink).toHaveAttribute('href', '/dashboard')
      expect(logoLink).toHaveAttribute('title', 'Go to Dashboard')
      expect(logoLink).toHaveClass('brand-home-link')
      expect(logoLink).toHaveTextContent('StockBill')
      expect(await screen.findByTestId('shop-name')).toHaveTextContent('Sharma General Store')
      expect(api.get).toHaveBeenCalledWith('/meta/')
      expect(logoLink).not.toHaveTextContent(/divya/i)
    })

    it('works correctly for staff users without showing admin-only nav links', () => {
      authContextState.token = 'valid-token'
      authContextState.user = { id: 2, username: 'staff1', role: 'staff' }

      render(
        <MemoryRouter initialEntries={['/invoices']}>
          <AppShell />
        </MemoryRouter>
      )

      const logoLink = screen.getByRole('link', { name: /go to dashboard/i })
      expect(logoLink).toBeInTheDocument()
      expect(logoLink).toHaveAttribute('href', '/dashboard')

      // Staff should see general operational links in navigation
      const nav = screen.getByRole('navigation', { name: /primary navigation/i })
      expect(nav).toHaveTextContent(/dashboard/i)
      expect(nav).toHaveTextContent(/invoices/i)

      // Staff should not see admin-only links
      expect(nav).not.toHaveTextContent(/purchases/i)
      expect(nav).not.toHaveTextContent(/suppliers/i)
    })
  })
})
