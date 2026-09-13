import api from './client'

export function rows(data) { return Array.isArray(data) ? data : data?.results || [] }

export async function fetchSuppliers({ page = 1, search = '', isActive = '' } = {}) {
  const params = { page }
  if (search) params.search = search
  if (isActive) params.is_active = isActive
  const { data } = await api.get('/suppliers/', { params })
  return data
}

// Active suppliers only: the backend rejects inactive suppliers for new
// purchases, so the picker never offers them.
export async function fetchActiveSuppliers(search = '') {
  const params = { is_active: 'true' }
  if (search) params.search = search
  return rows((await api.get('/suppliers/', { params })).data)
}

export async function fetchSupplier(id) {
  const { data } = await api.get(`/suppliers/${id}/`)
  return data
}

export async function createSupplier(payload) {
  const { data } = await api.post('/suppliers/', payload)
  return data
}

export async function updateSupplier(id, payload) {
  const { data } = await api.patch(`/suppliers/${id}/`, payload)
  return data
}

// DELETE archives; the backend never hard-deletes suppliers referenced by
// purchases or products, so history stays intact.
export async function archiveSupplier(id) {
  await api.delete(`/suppliers/${id}/`)
}

export async function reactivateSupplier(id) {
  const { data } = await api.patch(`/suppliers/${id}/`, { is_active: true })
  return data
}

// Purchase history scoped server-side to one supplier.
export async function fetchSupplierPurchases({ supplier, page = 1 } = {}) {
  const { data } = await api.get('/purchase-invoices/', { params: { supplier, page } })
  return data
}
