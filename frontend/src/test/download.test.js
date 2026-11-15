import { afterEach, describe, expect, it, vi } from 'vitest'
import { XLSX_TYPE, defaultExportName, filenameFromDisposition, saveBlobResponse } from '../api/download'

describe('CSV download helper', () => {
  afterEach(() => vi.restoreAllMocks())

  it('reads the server filename from Content-Disposition', () => {
    expect(filenameFromDisposition('attachment; filename="stockbill-inventory-20261116-1030.xlsx"')).toBe('stockbill-inventory-20261116-1030.xlsx')
    expect(filenameFromDisposition('')).toBe('')
  })

  it('builds an IST-stamped fallback name', () => {
    expect(defaultExportName('customers')).toMatch(/^stockbill-customers-\d{8}-\d{4}\.xlsx$/)
  })

  it('downloads with the server filename and revokes the object URL', () => {
    URL.createObjectURL = vi.fn(() => 'blob:x')
    URL.revokeObjectURL = vi.fn()
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    const name = saveBlobResponse(
      { data: new Blob(['x']), headers: { 'content-disposition': 'attachment; filename="server.xlsx"' } },
      'fallback.xlsx',
      XLSX_TYPE,
    )
    expect(name).toBe('server.xlsx')
    expect(click).toHaveBeenCalled()
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:x')
  })

  it('falls back when the header is not exposed', () => {
    URL.createObjectURL = vi.fn(() => 'blob:y')
    URL.revokeObjectURL = vi.fn()
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    expect(saveBlobResponse({ data: new Blob(['x']), headers: {} }, 'fallback.xlsx', XLSX_TYPE)).toBe('fallback.xlsx')
  })
})
