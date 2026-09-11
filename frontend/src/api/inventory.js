import api from './client'

export function rows(data) { return Array.isArray(data) ? data : data?.results || [] }

export async function fetchInventoryBalances({ page = 1, product = '', warehouse = '', search = '' } = {}) {
  const params = { page }
  if (product) params.product = product
  if (warehouse) params.warehouse = warehouse
  if (search) params.search = search
  const { data } = await api.get('/inventory-balances/', { params })
  return data
}

export async function fetchStockLedger({ page = 1, product = '', warehouse = '', movement_type = '', from = '', to = '', reference = '' } = {}) {
  const params = { page }
  if (product) params.product = product
  if (warehouse) params.warehouse = warehouse
  if (movement_type) params.movement_type = movement_type
  if (from) params.from = from
  if (to) params.to = to
  if (reference) params.reference = reference
  const { data } = await api.get('/stock-ledger/', { params })
  return data
}

export async function fetchProductInventory(productId) {
  const { data } = await api.get('/inventory-balances/', { params: { product: productId } })
  return rows(data)
}
