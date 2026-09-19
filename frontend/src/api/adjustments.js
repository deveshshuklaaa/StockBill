import api from './client'

export function rows(data) {
  return Array.isArray(data) ? data : data?.results || []
}

export async function fetchAdjustments({
  page = 1,
  type = '',
  product = '',
  warehouse = '',
  reason = '',
  from = '',
  to = '',
  search = '',
} = {}) {
  const params = { page }
  if (type) params.type = type
  if (product) params.product = product
  if (warehouse) params.warehouse = warehouse
  if (reason) params.reason = reason
  if (from) params.from = from
  if (to) params.to = to
  if (search) params.search = search

  const { data } = await api.get('/inventory/adjustments/', { params })
  return data
}

export async function fetchAdjustment(id) {
  const { data } = await api.get(`/inventory/adjustments/${id}/`)
  return data
}

export async function fetchNextAdjustmentNumber(date) {
  const params = date ? { date } : {}
  const { data } = await api.get('/inventory/adjustments/next-number/', { params })
  return data.next_number
}

export async function createAdjustment(payload, { idempotencyKey } = {}) {
  const headers = {}
  if (idempotencyKey) {
    headers['Idempotency-Key'] = idempotencyKey
  }
  const { data } = await api.post('/inventory/adjustments/', payload, { headers })
  return data
}
