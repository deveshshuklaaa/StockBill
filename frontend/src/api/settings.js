import api from './client'

export function rows(data) { return Array.isArray(data) ? data : data?.results || [] }

export async function fetchBusinessProfile() {
  const { data } = await api.get('/business-profile/')
  return data
}

export async function updateBusinessProfile(profileData) {
  const { data } = await api.patch('/business-profile/', profileData)
  return data
}

export async function fetchTaxRates() {
  return rows((await api.get('/tax-rates/admin/')).data)
}

export async function fetchTaxRate(id) {
  const { data } = await api.get(`/tax-rates/admin/${id}/`)
  return data
}

export async function createTaxRate(taxData) {
  const { data } = await api.post('/tax-rates/admin/', taxData)
  return data
}

export async function updateTaxRate(id, taxData) {
  const { data } = await api.patch(`/tax-rates/admin/${id}/`, taxData)
  return data
}

export async function fetchAuditLogs({ page = 1, search = '', entity_type = '', action = '', from = '', to = '' } = {}) {
  const params = { page }
  if (search) params.search = search
  if (entity_type) params.entity_type = entity_type
  if (action) params.action = action
  if (from) params.from = from
  if (to) params.to = to
  const { data } = await api.get('/audit-logs/', { params })
  return data
}

// Shop logo for invoices (stored in the database; served as a PNG).
export async function fetchBusinessLogoBlob() {
  const { data } = await api.get('/business-profile/logo/', { responseType: 'blob' })
  return data
}

export async function uploadBusinessLogo(file) {
  const form = new FormData()
  form.append('logo', file)
  const { data } = await api.post('/business-profile/logo/', form, { headers: { 'Content-Type': 'multipart/form-data' } })
  return data
}

export async function deleteBusinessLogo() {
  await api.delete('/business-profile/logo/')
}
