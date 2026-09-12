import api from './client'

export function rows(data) { return Array.isArray(data) ? data : data?.results || [] }

export async function fetchInvoices({ page = 1, search = '', state = '', paymentType = '', from = '', to = '' } = {}) {
  const params = { page }
  if (search) params.search = search
  if (state) params.state = state
  if (paymentType) params.payment_type = paymentType
  if (from) params.from = from
  if (to) params.to = to
  const { data } = await api.get('/invoices/', { params })
  return data
}

export async function fetchInvoice(id) {
  const { data } = await api.get(`/invoices/${id}/`)
  return data
}

export async function cancelInvoice(id, reason) {
  const { data } = await api.post(`/invoices/${id}/cancel/`, { reason })
  return data
}
