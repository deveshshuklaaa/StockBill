import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import InvoicesPage from '../pages/InvoicesPage'
import InvoiceItemSummaryModal from '../components/InvoiceItemSummaryModal'
import * as invoicesApi from '../api/invoices'

const useAuth = vi.hoisted(() => vi.fn(() => ({ user: { id: 1, username: 'tester', role: 'admin' }, token: 'tok', loading: false })))
vi.mock('../context/AuthContext', () => ({ useAuth }))

const MOCK_INVOICES_P1 = {
  count: 4,
  next: 'http://test/api/invoices/?page=2',
  previous: null,
  results: [
    {
      id: 101,
      invoice_number: 'INV-001',
      invoice_date: '2026-09-12',
      customer_name: 'Customer A',
      payment_type: 'credit',
      payment_status: 'credit',
      state: 'POSTED',
      total_amount: '100.00',
    },
    {
      id: 102,
      invoice_number: 'INV-002',
      invoice_date: '2026-09-12',
      customer_name: 'Customer B',
      payment_type: 'cash',
      payment_status: 'paid',
      state: 'POSTED',
      total_amount: '200.00',
    },
    {
      id: 103,
      invoice_number: 'INV-003',
      invoice_date: '2026-09-12',
      customer_name: 'Customer C',
      payment_type: 'credit',
      payment_status: 'credit',
      state: 'CANCELLED',
      total_amount: '50.00',
    },
    {
      id: 104,
      invoice_number: 'INV-004',
      invoice_date: '2026-09-12',
      customer_name: 'Customer D',
      payment_type: 'credit',
      payment_status: 'credit',
      state: 'DRAFT',
      total_amount: '75.00',
    },
  ],
}

const MOCK_INVOICES_P2 = {
  count: 4,
  next: null,
  previous: 'http://test/api/invoices/?page=1',
  results: [
    {
      id: 105,
      invoice_number: 'INV-005',
      invoice_date: '2026-09-13',
      customer_name: 'Customer E',
      payment_type: 'credit',
      payment_status: 'credit',
      state: 'POSTED',
      total_amount: '150.00',
    },
  ],
}

const MOCK_SUMMARY = {
  invoice_count: 2,
  selected_invoice_count: 2,
  invoice_numbers: ['INV-001', 'INV-002'],
  selected_invoice_numbers: ['INV-001', 'INV-002'],
  total_products: 4,
  total_base_quantity: '73.000',
  items: [
    {
      product_id: 1,
      product_name: 'Yellow Banana Chips',
      name: 'Yellow Banana Chips',
      sku: 'YBC-25G',
      mrp: '10.00',
      base_unit: 'piece',
      unit_type: 'piece',
      total_base_quantity: '16.000',
      invoice_count: 2,
      number_of_selected_invoices: 2,
      variant_summary: '25 g · MRP ₹10.00 · SKU: YBC-25G',
      attributes: { net_weight: 0.025, units_per_master_box: 192 },
    },
    {
      product_id: 2,
      product_name: 'Classic Salted',
      name: 'Classic Salted',
      sku: 'CS-25G',
      mrp: '10.00',
      base_unit: 'piece',
      unit_type: 'piece',
      total_base_quantity: '38.000',
      invoice_count: 2,
      number_of_selected_invoices: 2,
      variant_summary: '25 g · MRP ₹10.00 · SKU: CS-25G',
      attributes: { net_weight: 0.025 },
    },
    {
      product_id: 3,
      product_name: 'Manglori Mix',
      name: 'Manglori Mix',
      sku: 'MM-25G',
      mrp: '10.00',
      base_unit: 'piece',
      unit_type: 'piece',
      total_base_quantity: '15.000',
      invoice_count: 1,
      number_of_selected_invoices: 1,
      variant_summary: '25 g · MRP ₹10.00 · SKU: MM-25G',
      attributes: {},
    },
    {
      product_id: 4,
      product_name: 'Tasty Nuts',
      name: 'Tasty Nuts',
      sku: 'TN-20G',
      mrp: '10.00',
      base_unit: 'piece',
      unit_type: 'piece',
      total_base_quantity: '4.000',
      invoice_count: 1,
      number_of_selected_invoices: 1,
      variant_summary: '20 g · MRP ₹10.00 · SKU: TN-20G',
      attributes: {},
    },
  ],
}

function mountInvoicesPage() {
  return render(
    <MemoryRouter initialEntries={['/invoices']}>
      <Routes>
        <Route path="/invoices" element={<InvoicesPage />} />
      </Routes>
    </MemoryRouter>
  )
}

describe('Item-wise Summary Frontend Feature', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(invoicesApi, 'fetchInvoices').mockResolvedValue(MOCK_INVOICES_P1)
    vi.spyOn(invoicesApi, 'fetchInvoiceItemSummary').mockResolvedValue(MOCK_SUMMARY)
  })

  it('1. renders checkboxes for invoices', async () => {
    mountInvoicesPage()
    await waitFor(() => {
      expect(screen.getByText('INV-001')).toBeInTheDocument()
    })
    const check1 = screen.getByLabelText('Select invoice INV-001')
    const check2 = screen.getByLabelText('Select invoice INV-002')
    expect(check1).toBeInTheDocument()
    expect(check2).toBeInTheDocument()
  })

  it('2. toggles invoice selection', async () => {
    const user = userEvent.setup()
    mountInvoicesPage()
    await waitFor(() => {
      expect(screen.getByText('INV-001')).toBeInTheDocument()
    })

    const check1 = screen.getByLabelText('Select invoice INV-001')
    await user.click(check1)
    expect(check1).toBeChecked()

    await user.click(check1)
    expect(check1).not.toBeChecked()
  })

  it('3. updates selection count display', async () => {
    const user = userEvent.setup()
    mountInvoicesPage()
    await waitFor(() => {
      expect(screen.getByText('INV-001')).toBeInTheDocument()
    })

    const check1 = screen.getByLabelText('Select invoice INV-001')
    await user.click(check1)
    expect(screen.getByText('Selected: 1 invoice')).toBeInTheDocument()

    const check2 = screen.getByLabelText('Select invoice INV-002')
    await user.click(check2)
    expect(screen.getByText('Selected: 2 invoices')).toBeInTheDocument()
  })

  it('4. Item-wise Summary button is disabled when no invoices are selected', async () => {
    mountInvoicesPage()
    await waitFor(() => {
      expect(screen.getByText('INV-001')).toBeInTheDocument()
    })
    const summaryBtn = screen.getByRole('button', { name: /item-wise summary/i })
    expect(summaryBtn).toBeDisabled()
  })

  it('5. Item-wise Summary button is enabled when at least one invoice is selected', async () => {
    const user = userEvent.setup()
    mountInvoicesPage()
    await waitFor(() => {
      expect(screen.getByText('INV-001')).toBeInTheDocument()
    })

    const summaryBtn = screen.getByRole('button', { name: /item-wise summary/i })
    expect(summaryBtn).toBeDisabled()

    const check1 = screen.getByLabelText('Select invoice INV-001')
    await user.click(check1)

    expect(summaryBtn).not.toBeDisabled()
    expect(screen.getByRole('button', { name: /item-wise summary \(1\)/i })).toBeInTheDocument()
  })

  it('6. sends correct API request with selected IDs', async () => {
    const user = userEvent.setup()
    mountInvoicesPage()
    await waitFor(() => {
      expect(screen.getByText('INV-001')).toBeInTheDocument()
    })

    await user.click(screen.getByLabelText('Select invoice INV-001'))
    await user.click(screen.getByLabelText('Select invoice INV-002'))

    const summaryBtn = screen.getByRole('button', { name: /item-wise summary/i })
    await user.click(summaryBtn)

    await waitFor(() => {
      expect(invoicesApi.fetchInvoiceItemSummary).toHaveBeenCalledWith([101, 102])
    })
  })

  it('7. renders summary modal and details correctly', async () => {
    const user = userEvent.setup()
    mountInvoicesPage()
    await waitFor(() => {
      expect(screen.getByText('INV-001')).toBeInTheDocument()
    })

    await user.click(screen.getByLabelText('Select invoice INV-001'))
    await user.click(screen.getByLabelText('Select invoice INV-002'))

    const summaryBtn = screen.getByRole('button', { name: /item-wise summary/i })
    await user.click(summaryBtn)

    await waitFor(() => {
      expect(screen.getByRole('dialog')).toBeInTheDocument()
    })
    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText('Item-wise Summary')).toBeInTheDocument()
    expect(within(dialog).getByText('INV-001, INV-002')).toBeInTheDocument()
    expect(within(dialog).getByText('Authoritative aggregation across all selected posted invoices. Quantities reflect base inventory units.')).toBeInTheDocument()
  })

  it('8. aggregates and renders product rows correctly with quantities and invoice counts', async () => {
    const user = userEvent.setup()
    mountInvoicesPage()
    await waitFor(() => {
      expect(screen.getByText('INV-001')).toBeInTheDocument()
    })

    await user.click(screen.getByLabelText('Select invoice INV-001'))
    await user.click(screen.getByLabelText('Select invoice INV-002'))
    await user.click(screen.getByRole('button', { name: /item-wise summary/i }))

    await waitFor(() => {
      expect(screen.getByRole('dialog')).toBeInTheDocument()
    })

    const dialog = screen.getByRole('dialog')
    expect(within(dialog).getByText('Yellow Banana Chips')).toBeInTheDocument()
    expect(within(dialog).getByText('Classic Salted')).toBeInTheDocument()
    expect(within(dialog).getByText('Manglori Mix')).toBeInTheDocument()
    expect(within(dialog).getByText('Tasty Nuts')).toBeInTheDocument()

    // 16 pcs for Yellow Banana Chips
    expect(within(dialog).getByText('16 pcs')).toBeInTheDocument()
    // 38 pcs for Classic Salted
    expect(within(dialog).getByText('38 pcs')).toBeInTheDocument()
    // 73 pcs total base quantity
    expect(within(dialog).getByText('73 pcs')).toBeInTheDocument()
  })

  it('9. handles empty result and error state gracefully in modal', async () => {
    const { rerender } = render(
      <InvoiceItemSummaryModal isOpen={true} onClose={() => {}} selectedIds={[999]} />
    )

    // Initially resolves to empty
    vi.spyOn(invoicesApi, 'fetchInvoiceItemSummary').mockResolvedValueOnce({
      invoice_count: 0,
      invoice_numbers: [],
      total_products: 0,
      total_base_quantity: '0.000',
      items: [],
    })

    rerender(<InvoiceItemSummaryModal isOpen={true} onClose={() => {}} selectedIds={[998]} />)
    await waitFor(() => {
      expect(screen.getByText('No items found in selected invoices.')).toBeInTheDocument()
    })

    // Error state
    vi.spyOn(invoicesApi, 'fetchInvoiceItemSummary').mockRejectedValueOnce({
      response: { data: { detail: 'Server aggregation failed' } },
    })

    rerender(<InvoiceItemSummaryModal isOpen={true} onClose={() => {}} selectedIds={[997]} />)
    await waitFor(() => {
      expect(screen.getByText('Server aggregation failed')).toBeInTheDocument()
    })
  })

  it('10. pagination does not lose selected IDs', async () => {
    const user = userEvent.setup()
    vi.spyOn(invoicesApi, 'fetchInvoices').mockImplementation(async (params = {}) => {
      if (params.page === 2) return MOCK_INVOICES_P2
      return MOCK_INVOICES_P1
    })

    mountInvoicesPage()
    await waitFor(() => {
      expect(screen.getByText('INV-001')).toBeInTheDocument()
    })

    // Select INV-001 on page 1
    await user.click(screen.getByLabelText('Select invoice INV-001'))
    expect(screen.getByText('Selected: 1 invoice')).toBeInTheDocument()

    // Navigate to page 2
    const nextBtn = screen.getByRole('button', { name: 'Next →' })
    await user.click(nextBtn)

    await waitFor(() => {
      expect(screen.getByText('INV-005')).toBeInTheDocument()
    })

    // Selected count is preserved!
    expect(screen.getByText('Selected: 1 invoice')).toBeInTheDocument()

    // Select INV-005 on page 2
    await user.click(screen.getByLabelText('Select invoice INV-005'))
    expect(screen.getByText('Selected: 2 invoices')).toBeInTheDocument()

    // Navigate back to page 1
    const prevBtn = screen.getByRole('button', { name: '← Previous' })
    await user.click(prevBtn)

    await waitFor(() => {
      expect(screen.getByText('INV-001')).toBeInTheDocument()
    })

    // Both are still selected!
    expect(screen.getByLabelText('Select invoice INV-001')).toBeChecked()
    expect(screen.getByText('Selected: 2 invoices')).toBeInTheDocument()
  })

  it('11. draft and cancelled invoices cannot be selected in the UI', async () => {
    mountInvoicesPage()
    await waitFor(() => {
      expect(screen.getByText('INV-003')).toBeInTheDocument()
    })

    const cancelCheck = screen.getByLabelText('Select invoice INV-003')
    const draftCheck = screen.getByLabelText('Select invoice INV-004')

    expect(cancelCheck).toBeDisabled()
    expect(draftCheck).toBeDisabled()
  })

  it('12. renders Print button and printable report layout with authoritative data', async () => {
    const user = userEvent.setup()
    const printSpy = vi.spyOn(window, 'print').mockImplementation(() => {})
    mountInvoicesPage()

    await waitFor(() => {
      expect(screen.getByText('INV-001')).toBeInTheDocument()
    })

    await user.click(screen.getByLabelText('Select invoice INV-001'))
    await user.click(screen.getByLabelText('Select invoice INV-002'))

    await user.click(screen.getByRole('button', { name: /Item-wise Summary/i }))

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /Item-wise Summary/i })).toBeInTheDocument()
    })

    const printDoc = screen.getByTestId('item-summary-print-doc')
    expect(within(printDoc).getByText('DIVYA ENTERPRISES')).toBeInTheDocument()
    expect(within(printDoc).getByText('INV-001, INV-002')).toBeInTheDocument()
    expect(within(printDoc).getByText('Yellow Banana Chips')).toBeInTheDocument()
    expect(within(printDoc).getByText('73 pcs')).toBeInTheDocument()
    expect(
      within(printDoc).getByText(/Authoritative aggregation across all selected posted invoices/i)
    ).toBeInTheDocument()

    const printBtn = screen.getByRole('button', { name: /Print item-wise summary/i })
    expect(printBtn).toBeInTheDocument()
    await user.click(printBtn)
    expect(printSpy).toHaveBeenCalled()
  })

  it('13. renders Export Excel button and downloads authoritative XLSX file', async () => {
    const user = userEvent.setup()
    const exportSpy = vi
      .spyOn(invoicesApi, 'exportInvoiceItemSummaryXlsx')
      .mockResolvedValue(new Blob(['mock-xlsx']))

    mountInvoicesPage()

    await waitFor(() => {
      expect(screen.getByText('INV-001')).toBeInTheDocument()
    })

    await user.click(screen.getByLabelText('Select invoice INV-001'))
    await user.click(screen.getByLabelText('Select invoice INV-002'))

    await user.click(screen.getByRole('button', { name: /Item-wise Summary/i }))

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /Item-wise Summary/i })).toBeInTheDocument()
    })

    const exportBtn = screen.getByRole('button', { name: /Export Excel/i })
    expect(exportBtn).toBeInTheDocument()

    await user.click(exportBtn)

    await waitFor(() => {
      expect(exportSpy).toHaveBeenCalledWith([101, 102])
    })
  })

  it('14. multi-page print layout renders all 17+ products sequentially without repetition or controls', async () => {
    const SEVENTEEN_PRODUCTS = Array.from({ length: 17 }, (_, i) => ({
      product_id: 200 + i,
      product_name: `Product Batch Item ${i + 1}`,
      name: `Product Batch Item ${i + 1}`,
      sku: `SKU-P${200 + i}`,
      mrp: (15 + i * 2).toFixed(2),
      base_unit: 'piece',
      unit_type: 'piece',
      total_base_quantity: `${(i + 1) * 10}.000`,
      invoice_count: (i % 3) + 1,
      variant_summary: `${100 + i * 10} g · MRP ₹${(15 + i * 2).toFixed(2)}`,
      attributes: {},
    }))

    const MULTI_PAGE_SUMMARY = {
      invoice_count: 5,
      invoice_numbers: ['INV-001', 'INV-002', 'INV-003', 'INV-004', 'INV-005'],
      total_products: 17,
      total_base_quantity: '1530.000',
      items: SEVENTEEN_PRODUCTS,
    }

    vi.spyOn(invoicesApi, 'fetchInvoiceItemSummary').mockResolvedValue(MULTI_PAGE_SUMMARY)

    render(
      <InvoiceItemSummaryModal
        isOpen={true}
        onClose={() => {}}
        selectedIds={[101, 102, 103, 104, 105]}
      />
    )

    await waitFor(() => {
      expect(screen.getByTestId('item-summary-print-doc')).toBeInTheDocument()
    })

    const printDoc = screen.getByTestId('item-summary-print-doc')

    // 1. All 17 products appear exactly once in the printable document
    SEVENTEEN_PRODUCTS.forEach((p) => {
      const occurrences = within(printDoc).getAllByText(p.product_name)
      expect(occurrences).toHaveLength(1)
    })

    // 2. Table rows remain in exact order with row numbers 1 to 17
    const rows = printDoc.querySelectorAll('tbody tr')
    expect(rows).toHaveLength(17)
    rows.forEach((row, idx) => {
      expect(row.cells).toHaveLength(4)
      expect(row.cells[0].textContent.trim()).toBe(String(idx + 1))
      expect(row.cells[1].textContent).toContain(SEVENTEEN_PRODUCTS[idx].product_name)
      expect(row.cells[2].textContent).toBe(`₹${Number(SEVENTEEN_PRODUCTS[idx].mrp).toFixed(2)}`)
      expect(row.cells[3].textContent).toContain(`${(idx + 1) * 10} pcs`)
    })

    // Verify removed columns are absent from print headers
    const ths = printDoc.querySelectorAll('thead th')
    const headerTexts = Array.from(ths).map((th) => th.textContent.trim().toUpperCase())
    expect(headerTexts).toEqual(['#', 'PRODUCT NAME', 'MRP', 'TOTAL QUANTITY'])
    expect(headerTexts).not.toContain('SKU')
    expect(headerTexts).not.toContain('VARIANT / PACK')
    expect(headerTexts).not.toContain('BASE QTY (PCS)')
    expect(headerTexts).not.toContain('INVOICES')

    // 3. Totals appear exactly once in the footer
    const footer = printDoc.querySelector('footer')
    expect(within(footer).getByText('Total Products:')).toBeInTheDocument()
    expect(within(footer).getByText('17')).toBeInTheDocument()
    expect(within(footer).getByText('1,530 pcs')).toBeInTheDocument()

    // 4. Header elements appear exactly once
    expect(within(printDoc).getAllByText('DIVYA ENTERPRISES')).toHaveLength(1)
    expect(within(printDoc).getAllByText('ITEM-WISE SUMMARY')).toHaveLength(1)

    // 5. The print table uses table-header-group in styles for natural repeating
    const table = printDoc.querySelector('table')
    expect(table).toHaveClass('print-table')
    expect(printDoc.querySelector('thead')).toBeInTheDocument()

    // 6. No scrollbars or overflow styling on the print container or table
    expect(printDoc.style.overflow).not.toBe('auto')
    expect(printDoc.style.overflowY).not.toBe('auto')
    expect(printDoc.style.maxHeight).toBe('')

    // 7. No interactive modal controls or buttons exist inside the printable document
    expect(printDoc.querySelectorAll('button')).toHaveLength(0)

    // 8. Signature verification placeholder is present
    expect(within(printDoc).getByText(/Verified By \/ Signature/i)).toBeInTheDocument()
  })
})
