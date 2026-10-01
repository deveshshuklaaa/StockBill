import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import SalesGstReportPage from '../pages/reports/SalesGstReportPage'
import * as reportsApi from '../api/reports'

const useAuth = vi.hoisted(() =>
  vi.fn(() => ({ user: { id: 1, username: 'tester', role: 'admin' }, token: 'tok', loading: false }))
)
vi.mock('../context/AuthContext', () => ({ useAuth }))

const SAMPLE_REPORT = {
  from: '2026-08-01',
  to: '2026-08-31',
  seller: {
    business_name: 'DIVYA ENTERPRISES',
    gstin: '27DIVYA1234A1Z5',
  },
  columns: [
    'DATE',
    'BILL NO.',
    'PARTY NAME',
    'GSTIN',
    'HSN',
    'BILL AMT.',
    'TAXABLE',
    'TAX',
    'SGST',
    'CGST',
    'IGST',
    'TOTAL GST',
    'SUR.',
    'TAX FREE',
    'EXEMPTED',
    'R.OFF',
  ],
  rows: [
    {
      date: '10-08-2026',
      bill_no: 'A000001',
      party_name: 'NEW SAGAR STATIONERS',
      gstin: '27AAAAA1111A1Z1',
      hsn: '21069099',
      bill_amt: '2601.00',
      taxable: '2203.80',
      tax: '396.70',
      sgst: '198.35',
      cgst: '198.35',
      igst: '0.00',
      total_gst: '396.70',
      sur: '0.00',
      tax_free: '0.00',
      exempted: '0.00',
      r_off: '0.50',
    },
    {
      date: '12-08-2026',
      bill_no: 'A000002',
      party_name: 'HEMANT MADICAL',
      gstin: '27BBBBB2222B1Z2',
      hsn: '30049099',
      bill_amt: '625.00',
      taxable: '583.00',
      tax: '42.12',
      sgst: '21.06',
      cgst: '21.06',
      igst: '0.00',
      total_gst: '42.12',
      sur: '0.00',
      tax_free: '0.00',
      exempted: '0.00',
      r_off: '-0.12',
    },
  ],
  totals: {
    invoice_count: 2,
    bill_amt: '3226.00',
    taxable: '2786.80',
    tax: '438.82',
    sgst: '219.41',
    cgst: '219.41',
    igst: '0.00',
    total_gst: '438.82',
    sur: '0.00',
    tax_free: '0.00',
    exempted: '0.00',
    r_off: '0.38',
  },
}

const EMPTY_REPORT = {
  from: '2026-08-01',
  to: '2026-08-31',
  seller: { business_name: 'DIVYA ENTERPRISES', gstin: '27DIVYA1234A1Z5' },
  columns: [
    'DATE',
    'BILL NO.',
    'PARTY NAME',
    'GSTIN',
    'HSN',
    'BILL AMT.',
    'TAXABLE',
    'TAX',
    'SGST',
    'CGST',
    'IGST',
    'TOTAL GST',
    'SUR.',
    'TAX FREE',
    'EXEMPTED',
    'R.OFF',
  ],
  rows: [],
  totals: {
    invoice_count: 0,
    bill_amt: '0.00',
    taxable: '0.00',
    tax: '0.00',
    sgst: '0.00',
    cgst: '0.00',
    igst: '0.00',
    total_gst: '0.00',
    sur: '0.00',
    tax_free: '0.00',
    exempted: '0.00',
    r_off: '0.00',
  },
}

function mount() {
  return render(
    <MemoryRouter>
      <SalesGstReportPage />
    </MemoryRouter>
  )
}

describe('SalesGstReportPage', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('1. renders page header, title, and initial controls', async () => {
    vi.spyOn(reportsApi, 'fetchSalesGstReport').mockResolvedValue(SAMPLE_REPORT)
    mount()

    expect(screen.getByRole('heading', { level: 1, name: /Sales GST Report/i })).toBeInTheDocument()
    expect(screen.getByLabelText(/From Date/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/To Date/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Generate/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Export Excel/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Print/i })).toBeInTheDocument()
  })

  it('2. date filters are editable and trigger generate on form submit', async () => {
    const user = userEvent.setup()
    const fetchSpy = vi.spyOn(reportsApi, 'fetchSalesGstReport').mockResolvedValue(SAMPLE_REPORT)
    mount()

    const fromInput = screen.getByLabelText(/From Date/i)
    const toInput = screen.getByLabelText(/To Date/i)
    const generateBtn = screen.getByRole('button', { name: /Generate/i })

    await user.clear(fromInput)
    await user.type(fromInput, '2026-08-01')
    await user.clear(toInput)
    await user.type(toInput, '2026-08-31')
    await user.click(generateBtn)

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith({ from: '2026-08-01', to: '2026-08-31' })
    })
  })

  it('3. renders correct 16-column table and exact row values', async () => {
    vi.spyOn(reportsApi, 'fetchSalesGstReport').mockResolvedValue(SAMPLE_REPORT)
    mount()

    // Wait for data to arrive
    await screen.findAllByText('NEW SAGAR STATIONERS')

    // Verify all 16 headers exist
    expect(screen.getAllByText('DATE').length).toBeGreaterThan(0)
    expect(screen.getAllByText('BILL NO.').length).toBeGreaterThan(0)
    expect(screen.getAllByText('PARTY NAME').length).toBeGreaterThan(0)
    expect(screen.getAllByText('GSTIN').length).toBeGreaterThan(0)
    expect(screen.getAllByText('HSN').length).toBeGreaterThan(0)
    expect(screen.getAllByText('BILL AMT.').length).toBeGreaterThan(0)
    expect(screen.getAllByText('TAXABLE').length).toBeGreaterThan(0)
    expect(screen.getAllByText('TAX').length).toBeGreaterThan(0)
    expect(screen.getAllByText('SGST').length).toBeGreaterThan(0)
    expect(screen.getAllByText('CGST').length).toBeGreaterThan(0)
    expect(screen.getAllByText('IGST').length).toBeGreaterThan(0)
    expect(screen.getAllByText('TOTAL GST').length).toBeGreaterThan(0)
    expect(screen.getAllByText('SUR.').length).toBeGreaterThan(0)
    expect(screen.getAllByText('TAX FREE').length).toBeGreaterThan(0)
    expect(screen.getAllByText('EXEMPTED').length).toBeGreaterThan(0)
    expect(screen.getAllByText('R.OFF').length).toBeGreaterThan(0)

    // Verify row 1 values including new GST fields
    expect(screen.getAllByText('A000001').length).toBeGreaterThan(0)
    expect(screen.getAllByText('10-08-2026').length).toBeGreaterThan(0)
    expect(screen.getAllByText('27AAAAA1111A1Z1').length).toBeGreaterThan(0)
    expect(screen.getAllByText('21069099').length).toBeGreaterThan(0)
    expect(screen.getAllByText('₹2,601.00').length).toBeGreaterThan(0)
    expect(screen.getAllByText('₹2,203.80').length).toBeGreaterThan(0)
    expect(screen.getAllByText('₹396.70').length).toBeGreaterThan(0)
    expect(screen.getAllByText('₹198.35').length).toBeGreaterThan(0)
    expect(screen.getAllByText('+0.50').length).toBeGreaterThan(0)

    // Verify row 2 values
    expect(screen.getAllByText('HEMANT MADICAL').length).toBeGreaterThan(0)
    expect(screen.getAllByText('A000002').length).toBeGreaterThan(0)
    expect(screen.getAllByText('27BBBBB2222B1Z2').length).toBeGreaterThan(0)
    expect(screen.getAllByText('30049099').length).toBeGreaterThan(0)
    expect(screen.getAllByText('12-08-2026').length).toBeGreaterThan(0)
    expect(screen.getAllByText('₹625.00').length).toBeGreaterThan(0)
    expect(screen.getAllByText('-0.12').length).toBeGreaterThan(0)
  })

  it('4. renders bold totals in table footer', async () => {
    vi.spyOn(reportsApi, 'fetchSalesGstReport').mockResolvedValue(SAMPLE_REPORT)
    mount()

    await screen.findAllByText(/TOTAL \(2 Invoices\)/i)
    expect(screen.getAllByText('₹3,226.00').length).toBeGreaterThan(0)
    expect(screen.getAllByText('₹2,786.80').length).toBeGreaterThan(0)
    expect(screen.getAllByText('₹438.82').length).toBeGreaterThan(0)
    expect(screen.getAllByText('₹219.41').length).toBeGreaterThan(0)
    expect(screen.getAllByText('+0.38').length).toBeGreaterThan(0)
  })

  it('5. renders empty state when no invoices exist for date range', async () => {
    vi.spyOn(reportsApi, 'fetchSalesGstReport').mockResolvedValue(EMPTY_REPORT)
    mount()

    await screen.findByText('No posted sales invoices found for the selected period.')
    expect(screen.getByRole('button', { name: /Export Excel/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /Print/i })).toBeDisabled()
  })

  it('6. surfaces API error message', async () => {
    vi.spyOn(reportsApi, 'fetchSalesGstReport').mockRejectedValue({
      response: { data: { detail: 'from must be on or before to.' } },
    })
    mount()

    await screen.findByText('from must be on or before to.')
  })

  it('7. export excel button triggers export API call with correct dates', async () => {
    const user = userEvent.setup()
    vi.spyOn(reportsApi, 'fetchSalesGstReport').mockResolvedValue(SAMPLE_REPORT)
    const exportSpy = vi.spyOn(reportsApi, 'exportSalesGstReportXlsx').mockResolvedValue(new Blob())
    mount()

    await screen.findAllByText('NEW SAGAR STATIONERS')
    const exportBtn = screen.getByRole('button', { name: /Export Excel/i })
    expect(exportBtn).not.toBeDisabled()

    await user.click(exportBtn)
    expect(exportSpy).toHaveBeenCalledWith({ from: SAMPLE_REPORT.from, to: SAMPLE_REPORT.to })
  })

  it('8. print button invokes window.print', async () => {
    const user = userEvent.setup()
    vi.spyOn(reportsApi, 'fetchSalesGstReport').mockResolvedValue(SAMPLE_REPORT)
    const printSpy = vi.spyOn(window, 'print').mockImplementation(() => {})
    mount()

    await screen.findAllByText('NEW SAGAR STATIONERS')
    const printBtn = screen.getByRole('button', { name: /Print/i })
    expect(printBtn).not.toBeDisabled()

    await user.click(printBtn)
    expect(printSpy).toHaveBeenCalled()
  })

  it('9. renders dedicated print layout document', async () => {
    vi.spyOn(reportsApi, 'fetchSalesGstReport').mockResolvedValue(SAMPLE_REPORT)
    mount()

    await screen.findAllByText('NEW SAGAR STATIONERS')
    const printDoc = screen.getByTestId('sales-gst-print-doc')
    expect(printDoc).toBeInTheDocument()
    expect(printDoc).toHaveClass('printable-sales-gst')
  })
})
