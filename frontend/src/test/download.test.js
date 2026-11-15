import { afterEach, describe, expect, it, vi } from 'vitest'
import { defaultCsvName, filenameFromDisposition, saveBlobResponse } from '../api/download'

describe('CSV download helper', () => {
  afterEach(() => vi.restoreAllMocks())

  it('reads the server filename from Content-Disposition', () => {
    expect(filenameFromDisposition('attachment; filename="stockbill-inventory-20261116-1030.csv"')).toBe('stockbill-inventory-20261116-1030.csv')
    expect(filenameFromDisposition('')).toBe('')
  })

  it('builds an IST-stamped fallback name', () => {
    expect(defaultCsvName('customers')).toMatch(/^stockbill-customers-\d{8}-\d{4}\.csv$/)
  })

  it('downloads with the server filename and revokes the object URL', () => {
    URL.createObjectURL = vi.fn(() => 'blob:x')
    URL.revokeObjectURL = vi.fn()
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    const name = saveBlobResponse(
      { data: new Blob(['a,b']), headers: { 'content-disposition': 'attachment; filename="server.csv"' } },
      'fallback.csv',
      'text/csv',
    )
    expect(name).toBe('server.csv')
    expect(click).toHaveBeenCalled()
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:x')
  })

  it('falls back when the header is not exposed', () => {
    URL.createObjectURL = vi.fn(() => 'blob:y')
    URL.revokeObjectURL = vi.fn()
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    expect(saveBlobResponse({ data: new Blob(['x']), headers: {} }, 'fallback.csv', 'text/csv')).toBe('fallback.csv')
  })
})
