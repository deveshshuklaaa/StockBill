import axios from 'axios'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api',
  headers: { 'Content-Type': 'application/json' },
})

api.interceptors.request.use((config) => {
  const token = sessionStorage.getItem('stockbill_token')
  if (token) config.headers.Authorization = `Token ${token}`
  return config
})

export function apiErrorMessage(error) {
  const data = error?.response?.data
  if (!data) return 'The server could not be reached. Check that Django is running.'
  if (data instanceof Blob) {
    if (error.response?.status === 503) return 'PDF generation is unavailable because the server is missing its WeasyPrint native libraries.'
    return 'The server returned an unreadable error response.'
  }
  if (typeof data.detail === 'string') return data.detail
  return Object.entries(data)
    .map(([key, value]) => `${key}: ${Array.isArray(value) ? value.join(', ') : value}`)
    .join(' | ')
}

export default api
