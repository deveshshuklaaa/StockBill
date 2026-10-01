import api from './client'

export function rows(data) {
  return Array.isArray(data) ? data : data?.results || []
}

export async function fetchTransfers({
  page = 1,
  product = '',
  warehouse = '',
  source_warehouse = '',
  destination_warehouse = '',
  reason = '',
  from = '',
  to = '',
  search = '',
} = {}) {
  const params = { page }
  if (product) params.product = product
  if (warehouse) params.warehouse = warehouse
  if (source_warehouse) params.source_warehouse = source_warehouse
  if (destination_warehouse) params.destination_warehouse = destination_warehouse
  if (reason) params.reason = reason
  if (from) params.from = from
  if (to) params.to = to
  if (search) params.search = search

  const { data } = await api.get('/inventory/transfers/', { params })
  return data
}

export async function fetchTransfer(id) {
  const { data } = await api.get(`/inventory/transfers/${id}/`)
  return data
}

export async function fetchNextTransferNumber(date) {
  const params = date ? { date } : {}
  const { data } = await api.get('/inventory/transfers/next-number/', { params })
  return data.next_number
}

export async function createTransfer(payload, { idempotencyKey } = {}) {
  const headers = {}
  if (idempotencyKey) {
    headers['Idempotency-Key'] = idempotencyKey
  }
  const { data } = await api.post('/inventory/transfers/', payload, { headers })
  return data
}
