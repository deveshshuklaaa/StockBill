import { describe, expect, it } from 'vitest'
import { sortProductsByMrpForSameName } from '../utils/productSearch'

describe('sortProductsByMrpForSameName', () => {
  it('returns empty array or invalid inputs safely', () => {
    expect(sortProductsByMrpForSameName([])).toEqual([])
    expect(sortProductsByMrpForSameName(null)).toEqual([])
    expect(sortProductsByMrpForSameName(undefined)).toEqual([])
  })

  it('leaves single product or distinct products untouched', () => {
    const single = [{ id: 1, name: 'Single Item', mrp: '20.00' }]
    expect(sortProductsByMrpForSameName(single)).toEqual(single)

    const distinct = [
      { id: 1, name: 'Alpha Item', mrp: '50.00' },
      { id: 2, name: 'Beta Item', mrp: '10.00' },
    ]
    expect(sortProductsByMrpForSameName(distinct)).toEqual(distinct)
  })

  it('sorts same-name products by ascending numeric MRP', () => {
    const products = [
      { id: 1, name: 'Example Snack', mrp: '20.00' },
      { id: 2, name: 'Example Snack', mrp: '5.00' },
      { id: 3, name: 'Example Snack', mrp: '10.00' },
    ]

    const result = sortProductsByMrpForSameName(products)
    expect(result.map((p) => p.mrp)).toEqual(['5.00', '10.00', '20.00'])
    expect(result.map((p) => p.id)).toEqual([2, 3, 1])
  })

  it('handles case-insensitivity and whitespace in duplicate product names', () => {
    const products = [
      { id: 1, name: 'Chheda Soya Snax ', mrp: 20 },
      { id: 2, name: 'chheda soya snax', mrp: 5 },
      { id: 3, name: 'CHHEDA SOYA SNAX', mrp: 10 },
    ]

    const result = sortProductsByMrpForSameName(products)
    expect(result.map((p) => p.mrp)).toEqual([5, 10, 20])
  })

  it('preserves the relative positions of unrelated search results', () => {
    const products = [
      { id: 10, name: 'Banana Chips', mrp: '15.00' },
      { id: 1, name: 'Example Snack', mrp: '20.00' },
      { id: 2, name: 'Example Snack', mrp: '5.00' },
      { id: 30, name: 'Chilli Sticks', mrp: '12.00' },
    ]

    const result = sortProductsByMrpForSameName(products)
    // Banana Chips stays at index 0
    expect(result[0].id).toBe(10)
    // Example Snack items occupy index 1 and 2, sorted by MRP
    expect(result[1].id).toBe(2)
    expect(result[1].mrp).toBe('5.00')
    expect(result[2].id).toBe(1)
    expect(result[2].mrp).toBe('20.00')
    // Chilli Sticks stays at index 3
    expect(result[3].id).toBe(30)
  })

  it('handles products with null or missing MRP by placing them after priced variants', () => {
    const products = [
      { id: 1, name: 'Loose Dry Fruit', mrp: null },
      { id: 2, name: 'Loose Dry Fruit', mrp: '100.00' },
      { id: 3, name: 'Loose Dry Fruit', mrp: '50.00' },
    ]

    const result = sortProductsByMrpForSameName(products)
    expect(result.map((p) => p.id)).toEqual([3, 2, 1])
  })
})
