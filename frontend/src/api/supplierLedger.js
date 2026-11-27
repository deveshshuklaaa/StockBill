import api from './client'
import { defaultExportName, saveBlobResponse, XLSX_TYPE } from './download'

export function rows(data) { return Array.isArray(data) ? data : data?.results || [] }

// Sign convention (same as the server): balance > 0 = Payable (we owe the
// supplier); balance < 0 = Advance (we have paid ahead).
export function balanceLabel(balance) {
  const value = Number(balance || 0)
  if (value > 0) return 'Payable'
  if (value < 0) return 'Advance'
  return 'Settled'
}

export const PAYMENT_MODES = [
  { value: 'BANK_TRANSFER', label: 'Bank transfer' },
  { value: 'CASH', label: 'Cash' },
  { value: 'UPI', label: 'UPI' },
]

export async function fetchSupplierLedger(supplierId, { from = '', to = '' } = {}) {
  const params = {}
  if (from) params.from = from
  if (to) params.to = to
  const { data } = await api.get(`/suppliers/${supplierId}/ledger/`, { params })
  return data
}

export async function exportSupplierStatement(supplierId, { from = '', to = '' } = {}) {
  const params = {}
  if (from) params.from = from
  if (to) params.to = to
  const response = await api.get(`/suppliers/${supplierId}/ledger/export/`, { params, responseType: 'blob' })
  return saveBlobResponse(response, defaultExportName('supplier-statement'), XLSX_TYPE)
}

export async function fetchSupplierPayments({ supplier = '', from = '', to = '' } = {}) {
  const params = {}
  if (supplier) params.supplier = supplier
  if (from) params.from = from
  if (to) params.to = to
  return rows((await api.get('/supplier-payments/', { params })).data)
}

export async function createSupplierPayment(payload) {
  const { data } = await api.post('/supplier-payments/', payload)
  return data
}

export async function reverseSupplierPayment(id, { amount, reason }) {
  const { data } = await api.post(`/supplier-payments/${id}/reverse/`, { amount, reason })
  return data
}
