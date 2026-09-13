import api from './client'

export function rows(data) { return Array.isArray(data) ? data : data?.results || [] }

export async function fetchCustomers({ page = 1, search = '', isActive = '' } = {}) {
  const params = { page }
  if (search) params.search = search
  if (isActive) params.is_active = isActive
  const { data } = await api.get('/customers/', { params })
  return data
}

export async function fetchCustomer(id) {
  const { data } = await api.get(`/customers/${id}/`)
  return data
}

export async function fetchCustomerReport(id) {
  const { data } = await api.get(`/customers/${id}/report/`)
  return data
}

export async function archiveCustomer(id) {
  await api.delete(`/customers/${id}/`)
}

export async function reactivateCustomer(id) {
  const { data } = await api.patch(`/customers/${id}/`, { is_active: true })
  return data
}

export async function fetchPayments({ page = 1, customer = '', paymentMethod = '', from = '', to = '' } = {}) {
  const params = { page }
  if (customer) params.customer = customer
  if (paymentMethod) params.payment_method = paymentMethod
  if (from) params.from = from
  if (to) params.to = to
  const { data } = await api.get('/payments/', { params })
  return data
}

export async function recordPayment({ customer, invoice = null, amount, paymentMethod = 'cash', referenceNumber = '', notes = '' }) {
  const payload = {
    customer,
    amount,
    payment_method: paymentMethod,
  }
  if (invoice) payload.invoice = invoice
  if (referenceNumber) payload.reference_number = referenceNumber
  if (notes) payload.notes = notes
  const { data } = await api.post('/payments/', payload)
  return data
}

export async function reversePayment(id, amount, reason) {
  const { data } = await api.post(`/payments/${id}/reverse/`, { amount, reason })
  return data
}
