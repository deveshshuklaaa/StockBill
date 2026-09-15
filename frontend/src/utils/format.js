// Shared display formatters for quantities, weights, and master-box views.
//
// StockBill stores inventory in BASE UNITS (piece, box, carton, kg, litre).
// These utilities are presentation-only: they never change stored values,
// and master-box conversion is a display representation, never an inventory
// unit. All authoritative conversion/deduction stays on the backend.

const DISCRETE_UNITS = new Set(['piece', 'box', 'carton', 'packet', 'pack'])
const MEASURABLE_UNITS = new Set(['kg', 'kilogram', 'g', 'gram', 'l', 'litre', 'liter', 'ml', 'millilitre', 'm', 'metre', 'cm', 'centimetre', 'mm', 'millimetre'])

// Whole numbers lose their trailing zeros for discrete units (345.000 → 345);
// measurable units (kg, litre, ...) keep their decimals (12.500 kg).
export function formatQuantity(value, unit) {
  const number = Number(value)
  if (!Number.isFinite(number)) return String(value ?? '')
  const normalized = String(unit || '').toLowerCase()
  if (DISCRETE_UNITS.has(normalized)) {
    if (Number.isInteger(number)) return number.toLocaleString('en-IN')
    return number.toLocaleString('en-IN', { maximumFractionDigits: 3 })
  }
  if (normalized && MEASURABLE_UNITS.has(normalized)) {
    // Known measurable units (kg, litre, etc.) keep 3 decimals
    return number.toLocaleString('en-IN', { minimumFractionDigits: 3 })
  }
  // Unknown/no unit: strip trailing zeros (preserve meaningful decimals)
  if (Number.isInteger(number)) return number.toLocaleString('en-IN')
  return number.toLocaleString('en-IN', { maximumFractionDigits: 3 }).replace(/\.?0+$/, '')
}

// Same as formatQuantity but always appends a short unit label, e.g. "345 pcs".
export function formatQuantityWithUnit(value, unit) {
  const label = unitShortLabel(unit)
  const text = formatQuantity(value, unit)
  return label ? `${text} ${label}` : text
}

const UNIT_LABELS = { piece: 'pcs', box: 'boxes', carton: 'cartons', kg: 'kg', litre: 'L', liter: 'L' }

export function unitShortLabel(unit) {
  const key = String(unit || '').toLowerCase()
  return UNIT_LABELS[key] || (unit ? String(unit) : '')
}

// Net weight is stored in kg decimals; display friendly units.
// 0.018 kg → "18 g", 0.025 kg → "25 g", 1.0 kg → "1 kg".
export function formatNetWeight(kgValue) {
  const kg = Number(kgValue)
  if (!Number.isFinite(kg) || kg <= 0) return ''
  if (kg < 1) {
    const grams = kg * 1000
    const rounded = Number.isInteger(grams) ? grams : Number(grams.toFixed(1))
    return `${rounded.toLocaleString('en-IN')} g`
  }
  const whole = Number.isInteger(kg) ? kg : Number(kg.toFixed(3))
  return `${whole.toLocaleString('en-IN')} kg`
}

// Master-box metadata from a product's attributes payload.
// Returns a positive integer or null when not configured/invalid.
export function masterBoxSize(product) {
  const box = Number(product?.attributes?.units_per_master_box)
  return Number.isInteger(box) && box > 0 ? box : null
}

// Purely a display conversion: base pieces → "1 box + 8 pcs".
// Inventory stays in base units; this never touches stored quantities.
export function formatMasterBoxView(baseQuantity, boxSize) {
  const quantity = Number(baseQuantity)
  const box = Number(boxSize)
  if (!Number.isFinite(quantity) || quantity < 0) return ''
  if (quantity === 0) return '0 pcs'
  if (!Number.isInteger(box) || box <= 0) return ''
  const fullBoxes = Math.floor(quantity / box)
  const remaining = quantity - fullBoxes * box
  if (fullBoxes <= 0) return `${quantity} pcs` // below one box: just pieces
  const boxLabel = fullBoxes === 1 ? '1 box' : `${fullBoxes.toLocaleString('en-IN')} boxes`
  if (remaining === 0) return boxLabel
  return `${boxLabel} + ${remaining.toLocaleString('en-IN')} pcs`
}

// Secondary stock line for tables/cards: base quantity plus optional
// master-box representation ("200 pcs · 1 box + 8 pcs"). Sub-box stock
// shows pieces only; the main numeric value is always the base quantity.
export function formatStockWithBoxes(baseQuantity, product) {
  const unit = product?.base_unit || product?.unit_type
  const base = formatQuantityWithUnit(baseQuantity, unit || 'piece')
  const box = masterBoxSize(product)
  if (!box) return base
  const quantity = Number(baseQuantity)
  if (!Number.isFinite(quantity) || quantity < box) return base
  const boxText = formatMasterBoxView(baseQuantity, box)
  return boxText ? `${base} · ${boxText}` : base
}

// Variant identity line: weight + MRP + SKU + category.
// MRP is identification only — the selling rate stays an editable input.
export function variantSummary(product) {
  const parts = []
  const weight = formatNetWeight(product?.attributes?.net_weight)
  if (weight) parts.push(weight)
  if (product.mrp != null) parts.push(`MRP ₹${Number(product.mrp).toFixed(2)}`)
  if (product.sku) parts.push(`SKU: ${product.sku}`)
  if (product.category_name) parts.push(product.category_name)
  if (product.base_unit && product.base_unit !== 'piece') parts.push(product.base_unit)
  return parts.join(' · ')
}