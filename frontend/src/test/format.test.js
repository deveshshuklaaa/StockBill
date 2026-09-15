import { describe, it, expect } from 'vitest'
import {
  formatQuantity,
  formatQuantityWithUnit,
  formatNetWeight,
  masterBoxSize,
  formatMasterBoxView,
  formatStockWithBoxes,
  variantSummary,
} from '../utils/format'

describe('formatQuantity', () => {
  it('formats whole discrete quantities as integers', () => {
    expect(formatQuantity(345, 'piece')).toBe('345')
    expect(formatQuantity(1000, 'box')).toBe('1,000')
  })

  it('formats fractional discrete quantities with decimals', () => {
    expect(formatQuantity(345.5, 'piece')).toBe('345.5')
    expect(formatQuantity(345.500, 'piece')).toBe('345.5')
  })

  it('formats measurable quantities with 3 decimals', () => {
    expect(formatQuantity(12.5, 'kg')).toBe('12.500')
    expect(formatQuantity(3.25, 'litre')).toBe('3.250')
  })

  it('handles unknown units by preserving decimals', () => {
    expect(formatQuantity(12.5, 'unknown')).toBe('12.5')
  })

  it('handles zero', () => {
    expect(formatQuantity(0, 'piece')).toBe('0')
  })
})

describe('formatQuantityWithUnit', () => {
  it('appends unit label for discrete units', () => {
    expect(formatQuantityWithUnit(345, 'piece')).toBe('345 pcs')
    expect(formatQuantityWithUnit(1, 'piece')).toBe('1 pcs')
    expect(formatQuantityWithUnit(2, 'box')).toBe('2 boxes')
  })

  it('appends unit label for measurable units', () => {
    expect(formatQuantityWithUnit(12.5, 'kg')).toBe('12.500 kg')
    expect(formatQuantityWithUnit(3.25, 'litre')).toBe('3.250 L')
  })

  it('uses raw unit for unknown units', () => {
    expect(formatQuantityWithUnit(10, 'packet')).toBe('10 packet')
  })
})

describe('formatNetWeight', () => {
  it('converts kg to grams for values < 1', () => {
    expect(formatNetWeight(0.018)).toBe('18 g')
    expect(formatNetWeight(0.025)).toBe('25 g')
    expect(formatNetWeight(0.052)).toBe('52 g')
  })

  it('shows grams with one decimal for fractional grams', () => {
    expect(formatNetWeight(0.0255)).toBe('25.5 g')
  })

  it('shows kg for values >= 1', () => {
    expect(formatNetWeight(1)).toBe('1 kg')
    expect(formatNetWeight(1.5)).toBe('1.5 kg')
    expect(formatNetWeight(2.25)).toBe('2.25 kg')
  })

  it('handles zero and negative', () => {
    expect(formatNetWeight(0)).toBe('')
    expect(formatNetWeight(-1)).toBe('')
  })
})

describe('masterBoxSize', () => {
  it('returns integer from product attributes', () => {
    expect(masterBoxSize({ attributes: { units_per_master_box: 192 } })).toBe(192)
    expect(masterBoxSize({ attributes: { units_per_master_box: 120 } })).toBe(120)
  })

  it('returns null for missing or invalid values', () => {
    expect(masterBoxSize({})).toBeNull()
    expect(masterBoxSize({ attributes: {} })).toBeNull()
    expect(masterBoxSize({ attributes: { units_per_master_box: 0 } })).toBeNull()
    expect(masterBoxSize({ attributes: { units_per_master_box: 'abc' } })).toBeNull()
  })
})

describe('formatMasterBoxView', () => {
  it('shows pieces only when below one box', () => {
    expect(formatMasterBoxView(96, 192)).toBe('96 pcs')
  })

  it('shows whole boxes when exact', () => {
    expect(formatMasterBoxView(192, 192)).toBe('1 box')
    expect(formatMasterBoxView(384, 192)).toBe('2 boxes')
    expect(formatMasterBoxView(960, 192)).toBe('5 boxes')
  })

  it('shows boxes + pieces when remainder exists', () => {
    expect(formatMasterBoxView(200, 192)).toBe('1 box + 8 pcs')
  })

  it('handles zero and invalid inputs', () => {
    expect(formatMasterBoxView(0, 192)).toBe('0 pcs')
    expect(formatMasterBoxView(-1, 192)).toBe('')
    expect(formatMasterBoxView(100, 0)).toBe('')
  })
})

describe('formatStockWithBoxes', () => {
  it('shows base + master box view when product has M.Box and quantity >= box', () => {
    const product = { base_unit: 'piece', attributes: { units_per_master_box: 192 } }
    expect(formatStockWithBoxes(200, product)).toBe('200 pcs · 1 box + 8 pcs')
    expect(formatStockWithBoxes(384, product)).toBe('384 pcs · 2 boxes')
  })

  it('shows only pieces when below one box', () => {
    const product = { base_unit: 'piece', attributes: { units_per_master_box: 192 } }
    expect(formatStockWithBoxes(96, product)).toBe('96 pcs')
  })

  it('shows only pieces when no master box attribute', () => {
    const product = { base_unit: 'piece', attributes: {} }
    expect(formatStockWithBoxes(200, product)).toBe('200 pcs')
  })
})

describe('variantSummary', () => {
  it('includes weight, MRP, SKU, and category', () => {
    const product = {
      attributes: { net_weight: 0.025 },
      mrp: 10,
      sku: 'TEST-001',
      category_name: 'Chips',
      base_unit: 'piece',
    }
    expect(variantSummary(product)).toBe('25 g · MRP ₹10.00 · SKU: TEST-001 · Chips')
  })

  it('omits missing fields', () => {
    const product = { attributes: {}, mrp: null, sku: '', category_name: '' }
    expect(variantSummary(product)).toBe('')
  })
})