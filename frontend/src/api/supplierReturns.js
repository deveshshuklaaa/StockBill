import api from './client'

export function rows(data) { return Array.isArray(data) ? data : data?.results || [] }

// Damaged goods sent back to a supplier for 1:1 replacement, and the
// replacement receipts against them.
export async function fetchSupplierReturns(supplierId) {
  return rows((await api.get('/supplier-returns/', { params: { supplier: supplierId } })).data)
}

export async function createSupplierReturn(payload) {
  const { data } = await api.post('/supplier-returns/', payload)
  return data
}

export async function receiveReplacement(returnId, payload) {
  const { data } = await api.post(`/supplier-returns/${returnId}/replacements/`, payload)
  return data
}
