// Warehouses a sale can be billed from, besides the default Main (which is
// what an empty selection means, exactly as before the selector existed).
// Inactive and non-sellable (e.g. Damaged / Quarantine) warehouses are left out.
export function isMainWarehouse(warehouse) {
  return String(warehouse?.code || '').toUpperCase() === 'MAIN'
}

/**
 * On-hand quantity of `product` in the warehouse a sale draws from.
 *
 * balances: the product's InventoryBalance rows ({ warehouse, quantity_on_hand })
 * or undefined while not loaded / on error. warehouseId: the effective source
 * (the chosen one, else Main's id; null if Main's id is unknown).
 *
 * Falls back to product.current_stock (the old hint) whenever the per-warehouse
 * figure can't be known, and for a product with no balance rows at all when
 * selling from Main: the server bootstraps such legacy stock into Main.
 */
export function availableInWarehouse(product, balances, { warehouseId, isMain }) {
  if (!Array.isArray(balances) || warehouseId == null) return product?.current_stock
  if (balances.length === 0) return isMain ? product?.current_stock : 0
  const row = balances.find((b) => String(b.warehouse) === String(warehouseId))
  return row ? row.quantity_on_hand : 0
}

export function saleSourceOptions(warehouses) {
  return (warehouses || []).filter(
    (w) => w.is_active !== false && w.is_sellable !== false && String(w.code || '').toUpperCase() !== 'MAIN'
  )
}
