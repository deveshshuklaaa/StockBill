import api from '../api/client'

export function rows(data) { return Array.isArray(data) ? data : data?.results || [] }

export async function fetchCategories() {
  return rows((await api.get('/categories/')).data)
}

export async function fetchCategorySchema(categoryId) {
  if (!categoryId) return []
  const { data } = await api.get(`/categories/${categoryId}/attributes/`)
  return Array.isArray(data) ? data : []
}

export async function fetchAttributeDefinitions() {
  return rows((await api.get('/attributes/')).data)
}

export async function fetchCategoryAssignments(categoryId) {
  if (!categoryId) return []
  return rows((await api.get(`/categories/${categoryId}/attribute-assignments/`)).data)
}

export async function fetchTaxRates() {
  return rows((await api.get('/tax-rates/')).data)
}
