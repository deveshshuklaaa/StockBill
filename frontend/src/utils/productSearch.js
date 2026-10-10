/**
 * Utility for sorting product search results.
 *
 * When two or more products share the same product name (case-insensitive, trimmed)
 * but have different MRPs, sort those same-name products in ascending order by
 * numeric MRP (lowest MRP first), while preserving the overall search relevance
 * and positions of unrelated products.
 *
 * @param {Array} products - Array of product objects from search API
 * @returns {Array} - Reordered products array with same-name products sorted by MRP asc
 */
export function sortProductsByMrpForSameName(products) {
  if (!Array.isArray(products) || products.length <= 1) return products || []

  const nameGroups = new Map()
  products.forEach((p, idx) => {
    const key = String(p?.name || '').trim().toLowerCase()
    if (!nameGroups.has(key)) {
      nameGroups.set(key, { indices: [], items: [] })
    }
    const group = nameGroups.get(key)
    group.indices.push(idx)
    group.items.push(p)
  })

  const result = [...products]
  for (const { indices, items } of nameGroups.values()) {
    if (items.length > 1) {
      const sorted = [...items].sort((a, b) => {
        const mrpA = a?.mrp != null ? Number(a.mrp) : Infinity
        const mrpB = b?.mrp != null ? Number(b.mrp) : Infinity
        if (mrpA !== mrpB) return mrpA - mrpB
        return 0
      })
      indices.forEach((origIdx, i) => {
        result[origIdx] = sorted[i]
      })
    }
  }
  return result
}
