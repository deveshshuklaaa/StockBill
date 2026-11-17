import axios from 'axios'

// VITE_API_BASE_URL wins when set (dev: http://127.0.0.1:8000/api in
// frontend/.env). A production build otherwise talks to its own origin,
// where nginx proxies /api to Django.
export function resolveApiBaseUrl(env = {}) {
  if (env.VITE_API_BASE_URL) return env.VITE_API_BASE_URL
  return env.PROD ? '/api' : 'http://localhost:8000/api'
}

// Fired when the API rejects the stored token (expired or revoked);
// AuthProvider listens, clears the session and ProtectedRoute sends the
// user to /login.
export const SESSION_EXPIRED_EVENT = 'stockbill:session-expired'
const LOGIN_PATH = '/auth/token/'

const api = axios.create({
  baseURL: resolveApiBaseUrl(import.meta.env),
  headers: { 'Content-Type': 'application/json' },
})

api.interceptors.request.use((config) => {
  const token = sessionStorage.getItem('stockbill_token')
  if (token) config.headers.Authorization = `Token ${token}`
  return config
})

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    // A wrong password on the login form is a 400, but guard the login call
    // anyway so it can never bounce the login page to itself.
    if (error.response?.status === 401 && error.config?.url !== LOGIN_PATH && typeof window !== 'undefined') {
      window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT))
    }
    if (error.response?.data instanceof Blob) {
      try {
        const text = await error.response.data.text()
        try {
          error.response.data = JSON.parse(text)
        } catch {
          if (text) error.response.data = { detail: text }
        }
      } catch {
        // preserve original blob
      }
    }
    return Promise.reject(error)
  }
)

// A request that never got a response: server down, refused, or blocked by
// the browser (CORS). err.response is undefined in all of these cases.
function isNetworkFailure(error) {
  return !error?.response
}

function validationMessage(data) {
  // Handle string detail responses
  if (typeof data?.detail === 'string') return data.detail

  // Handle array responses (malformed backend or unexpected error shape)
  if (Array.isArray(data)) {
    const messages = data
      .map((item) => {
        if (typeof item === 'string') return item
        if (item?.detail) return item.detail
        if (typeof item === 'object') return JSON.stringify(item)
        return String(item)
      })
      .filter(Boolean)
    return messages.join('; ') || 'An error occurred.'
  }

  // Handle object responses (field errors)
  if (typeof data === 'object' && data !== null) {
    const entries = Object.entries(data)
      .filter(([key]) => key !== 'detail') // Skip detail if already checked
      .map(([key, value]) => {
        if (Array.isArray(value)) {
          return `${key}: ${value.join(', ')}`
        }
        if (typeof value === 'object' && value !== null) {
          // Nested errors: flatten without numeric keys
          const nested = Object.entries(value)
            .map(([_k, v]) => (Array.isArray(v) ? v.join(', ') : String(v)))
            .join('; ')
          return `${key}: ${nested}`
        }
        return `${key}: ${value}`
      })
    return entries.join(' | ') || 'An error occurred.'
  }

  // Fallback for unexpected types
  return 'An error occurred.'
}

export function apiErrorMessage(error, { action = 'processing request' } = {}) {
  if (isNetworkFailure(error)) {
    return 'Django server could not be reached.'
  }
  const status = error.response?.status
  const data = error.response?.data
  if (data instanceof Blob) {
    return 'The server returned an unreadable error response.'
  }
  if (status === 503) {
    const message = typeof data?.detail === 'string' ? data.detail : ''
    return message || 'Service is temporarily unavailable.'
  }
  if (status === 400) {
    const message = validationMessage(data)
    return message || 'The submitted values are invalid.'
  }
  if (status === 401) return 'Your session has expired. Please log in again.'
  if (status === 403) return 'You do not have permission to perform this action.'
  if (status === 409) {
    const message = typeof data?.detail === 'string' ? data.detail : ''
    return message
      ? message
      : 'This request conflicts with an existing record (the same Idempotency-Key may have been used with a different payload).'
  }
  if (status >= 500) return `Server error while ${action}.`
  const message = validationMessage(data)
  return message || `The request failed (status ${status}).`
}

// 403 message tailored for a specific action, e.g. purchase posting.
export function apiForbiddenMessage(error, forbiddenAction = 'perform this action', action = forbiddenAction) {
  if (isNetworkFailure(error)) {
    return 'Django server could not be reached.'
  }
  if (error.response?.status === 403) return `You do not have permission to ${forbiddenAction}.`
  return apiErrorMessage(error, { action })
}

export default api
