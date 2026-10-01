import api from './client'

// All report endpoints are read-only GETs; totals come from backend
// aggregation, never computed in React.

export async function fetchSalesReport({ from, to, customer = '', paymentType = '' } = {}) {
  const params = { from, to }
  if (customer) params.customer = customer
  if (paymentType) params.payment_type = paymentType
  const { data } = await api.get('/reports/sales/', { params })
  return data
}

export async function fetchPurchaseReport({ from, to, supplier = '' } = {}) {
  const params = { from, to }
  if (supplier) params.supplier = supplier
  const { data } = await api.get('/reports/purchases/', { params })
  return data
}

export async function fetchInventoryReport({ warehouse = '', category = '', isActive = '', search = '' } = {}) {
  const params = {}
  if (warehouse) params.warehouse = warehouse
  if (category) params.category = category
  if (isActive) params.is_active = isActive
  if (search) params.search = search
  const { data } = await api.get('/reports/inventory/', { params })
  return data
}

export async function fetchStockMovementReport({ product = '', warehouse = '', movementType = '', from = '', to = '', reference = '' } = {}) {
  const params = {}
  if (product) params.product = product
  if (warehouse) params.warehouse = warehouse
  if (movementType) params.movement_type = movementType
  if (from) params.from = from
  if (to) params.to = to
  if (reference) params.reference = reference
  const { data } = await api.get('/reports/stock-movement/', { params })
  return data
}

export async function fetchProductSalesReport({ from, to }) {
  const { data } = await api.get('/reports/products/', { params: { from, to } })
  return data
}

export async function fetchCustomerSalesReport({ from, to }) {
  const { data } = await api.get('/reports/customers/', { params: { from, to } })
  return data
}

export async function fetchTaxReport({ from, to }) {
  const { data } = await api.get('/reports/tax/', { params: { from, to } })
  return data
}

export async function fetchProfitReport({ from, to }) {
  const { data } = await api.get('/reports/profit/', { params: { from, to } })
  return data
}

export async function fetchTopProductsReport({ from, to, sortBy = 'quantity', limit = 10 }) {
  const { data } = await api.get('/reports/top-products/', {
    params: { from, to, sort_by: sortBy, limit },
  })
  return data
}

export async function fetchDashboard({ from, to } = {}) {
  const params = {}
  if (from) params.from = from
  if (to) params.to = to
  const { data } = await api.get('/reports/dashboard/', { params })
  return data
}

export async function fetchSalesGstReport({ from, to }) {
  const { data } = await api.get('/reports/sales-gst/', { params: { from, to } })
  return data
}

export async function exportSalesGstReportXlsx({ from, to }) {
  const response = await api.get('/reports/sales-gst/export/', {
    params: { from, to },
    responseType: 'blob',
  })
  const blob = new Blob([response.data], {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  const fromClean = (from || '').replace(/-/g, '')
  const toClean = (to || '').replace(/-/g, '')
  link.download = `sales-gst-report-${fromClean}-${toClean}.xlsx`
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
  return blob
}
