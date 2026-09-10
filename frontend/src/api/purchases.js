import api from '../api/client'

export function rows(data) { return Array.isArray(data) ? data : data?.results || [] }

export async function fetchSuppliers(search = '') {
  const params = {}
  if (search) params.search = search
  return rows((await api.get('/suppliers/', { params })).data)
}

export async function fetchWarehouses() {
  return rows((await api.get('/warehouses/')).data)
}

export async function fetchPurchases({ page = 1, state = '', supplier = '', search = '' } = {}) {
  const params = { page }
  if (state) params.state = state
  if (supplier) params.supplier = supplier
  if (search) params.search = search
  const { data } = await api.get('/purchase-invoices/', { params })
  return data
}

export async function fetchPurchase(id) {
  const { data } = await api.get(`/purchase-invoices/${id}/`)
  return data
}

export async function fetchNextPurchaseNumber(invoiceDate) {
  const { data } = await api.get('/purchase-invoices/next-number/', {
    params: invoiceDate ? { date: invoiceDate } : {},
  })
  return data.next_number
}

export function searchPurchaseProducts(query) {
  return api.get('/products/', { params: { search: query, is_active: 'true', page: 1 } })
}
