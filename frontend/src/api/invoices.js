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

export async function fetchInvoicePdf(id, { copy = 'original', disposition = 'inline' } = {}) {
  const response = await api.get(`/invoices/${id}/pdf/`, {
    params: { copy, disposition },
    responseType: 'blob',
  })
  return response.data
}

export async function printInvoicePdf(id, { copy = 'original', invoiceNumber = '' } = {}) {
  const blob = await fetchInvoicePdf(id, { copy, disposition: 'inline' })
  const blobUrl = URL.createObjectURL(blob)
  const win = window.open(blobUrl, '_blank')
  if (!win) {
    const link = document.createElement('a')
    link.href = blobUrl
    link.download = `invoice-${invoiceNumber || id}-${copy}.pdf`
    document.body.appendChild(link)
    link.click()
    link.remove()
  }
  return blobUrl
}
