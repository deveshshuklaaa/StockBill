// Warehouses a sale can be billed from, besides the default Main (which is
// what an empty selection means, exactly as before the selector existed).
// Inactive and non-sellable (e.g. Damaged / Quarantine) warehouses are left out.
export function saleSourceOptions(warehouses) {
  return (warehouses || []).filter(
    (w) => w.is_active !== false && w.is_sellable !== false && String(w.code || '').toUpperCase() !== 'MAIN'
  )
}
