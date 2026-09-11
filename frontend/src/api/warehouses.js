import api from './client'

export function rows(data) { return Array.isArray(data) ? data : data?.results || [] }

export async function fetchWarehouses() {
  return rows((await api.get('/warehouses/')).data)
}

export async function fetchWarehouse(id) {
  const { data } = await api.get(`/warehouses/${id}/`)
  return data
}

export async function fetchWarehouseSummary() {
  const { data } = await api.get('/warehouses/summary/')
  return rows(data)
}

export async function createWarehouse(warehouseData) {
  const { data } = await api.post('/warehouses/', warehouseData)
  return data
}

export async function updateWarehouse(id, warehouseData) {
  const { data } = await api.patch(`/warehouses/${id}/`, warehouseData)
  return data
}
