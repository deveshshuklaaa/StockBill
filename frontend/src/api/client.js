import axios from 'axios'

const api = axios.create({
  baseURL: import.meta.env?.VITE_API_BASE_URL || 'http://localhost:8000/api',
  headers: { 'Content-Type': 'application/json' },
})

api.interceptors.request.use((config) => {
  const token = sessionStorage.getItem('stockbill_token')
  if (token) config.headers.Authorization = `Token ${token}`
  return config
})

// A request that never got a response: server down, refused, or blocked by
// the browser (CORS). err.response is undefined in all of these cases.
function isNetworkFailure(error) {
  return !error?.response
}

function validationMessage(data) {
  if (typeof data?.detail === 'string') return data.detail
  return Object.entries(data || {})
    .map(([key, value]) => `${key}: ${Array.isArray(value) ? value.join(', ') : value}`)
    .join(' | ')
}

export function apiErrorMessage(error, { action = 'processing request' } = {}) {
  if (isNetworkFailure(error)) {
    return 'Django server could not be reached.'
  }
  const status = error.response?.status
  const data = error.response?.data
  if (data instanceof Blob) {
    if (status === 503) return 'PDF generation is unavailable because the server is missing its WeasyPrint native libraries.'
    return 'The server returned an unreadable error response.'
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
