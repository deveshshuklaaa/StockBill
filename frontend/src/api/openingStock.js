import api from './client'

export function rows(data) {
  return Array.isArray(data) ? data : data?.results || []
}

export async function fetchOpeningStocks({
  page = 1,
  product = '',
  warehouse = '',
  reason = '',
  from = '',
  to = '',
  search = '',
} = {}) {
  const params = { page }
  if (product) params.product = product
  if (warehouse) params.warehouse = warehouse
  if (reason) params.reason = reason
  if (from) params.from = from
  if (to) params.to = to
  if (search) params.search = search

  const { data } = await api.get('/inventory/opening-stock/', { params })
  return data
}

export async function fetchOpeningStock(id) {
  const { data } = await api.get(`/inventory/opening-stock/${id}/`)
  return data
}

export async function fetchNextOpeningStockNumber(date) {
  const params = date ? { date } : {}
  const { data } = await api.get('/inventory/opening-stock/next-number/', { params })
  return data.next_number
}

export async function previewOpeningStock(payload) {
  const { data } = await api.post('/inventory/opening-stock/preview/', payload)
  return data
}

export async function createOpeningStock(payload, { idempotencyKey } = {}) {
  const headers = {}
  if (idempotencyKey) {
    headers['Idempotency-Key'] = idempotencyKey
  }
  const { data } = await api.post('/inventory/opening-stock/', payload, { headers })
  return data
}
