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
  let win = null
  try {
    win = window.open('', '_blank')
    if (win && win.document) {
      win.document.title = 'Loading invoice...'
    }
  } catch {
    win = null
  }

  try {
    const data = await fetchInvoicePdf(id, { copy, disposition: 'inline' })
    const pdfBlob = data instanceof Blob && data.type === 'application/pdf'
      ? data
      : new Blob([data], { type: 'application/pdf' })
    const blobUrl = URL.createObjectURL(pdfBlob)
    const copyLabel = copy.charAt(0).toUpperCase() + copy.slice(1)
    const title = `Invoice ${invoiceNumber || id} - ${copyLabel}`

    if (win && !win.closed && win.document) {
      win.document.open()
      win.document.write(`<!DOCTYPE html><html><head><title>${title}</title><style>html,body{margin:0;padding:0;width:100%;height:100%;overflow:hidden;background:#525659;}embed{width:100%;height:100%;border:none;}</style></head><body><embed src="${blobUrl}" type="application/pdf" width="100%" height="100%" /></body></html>`)
      win.document.close()
    } else {
      const link = document.createElement('a')
      link.href = blobUrl
      link.download = `invoice-${invoiceNumber || id}-${copy}.pdf`
      document.body.appendChild(link)
      link.click()
      link.remove()
    }
    return blobUrl
  } catch (err) {
    if (win && !win.closed) {
      try { win.close() } catch {}
    }
    throw err
  }
}
