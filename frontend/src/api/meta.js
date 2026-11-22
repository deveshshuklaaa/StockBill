import api from './client'

// GET /api/meta/: {"environment"} for everyone; plus "database" outside
// production and "business_name" for signed-in users.
export async function fetchMeta() {
  const { data } = await api.get('/meta/')
  return data
}
