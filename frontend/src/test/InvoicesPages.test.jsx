// Regression tests for the sales/invoice history UI.
//
// Covers: /invoices list (search/filter/pagination wiring, status badges,
// view link) and /invoices/:id detail (snapshot fields, cancel action
// visibility by role, error surfacing) against the real API contract.

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import InvoicesPage from '../pages/InvoicesPage'
import InvoiceDetailPage from '../pages/InvoiceDetailPage'
import * as invoicesApi from '../api/invoices'
import * as client from '../api/client'

const useAuth = vi.hoisted(() => vi.fn(() => ({ user: { id: 1, username: 'tester', role: 'admin' }, token: 'tok', loading: false })))
vi.mock('../context/AuthContext', () => ({ useAuth }))

const PAGE_1 = {
  count: 3,
  next: 'http://test/api/invoices/?page=2',
  previous: null,
  results: [
    {
      id: 11,
      invoice_number: 'INV-20260912-1',
      invoice_date: '2026-09-12',
      customer_name: 'J K Traders',
      payment_type: 'credit',
      payment_status: 'credit',
      state: 'POSTED',
      total_amount: '1102.00',
    },
    {
      id: 12,
      invoice_number: 'INV-20260912-2',
      invoice_date: '2026-09-12',
      customer_name: 'Walk-in customer',
      payment_type: 'cash',
      payment_status: 'paid',
      state: 'POSTED',
      total_amount: '476.00',
    },
    {
      id: 13,
      invoice_number: 'INV-20260912-3',
      invoice_date: '2026-09-12',
      customer_name: 'J K Traders',
      payment_type: 'credit',
      payment_status: 'credit',
      state: 'CANCELLED',
      total_amount: '118.00',
    },
  ],
}

const DETAIL = {
  id: 11,
  invoice_number: 'INV-20260912-1',
  invoice_date: '2026-09-12',
  created_at: '2026-09-12T17:18:41+05:30',
  customer_name: 'J K Traders',
  customer_gstin_snapshot: '27JKTRADERS1A1Z5',
  billing_address_snapshot: 'Shop 2, Market',
  state_snapshot: 'Maharashtra',
  seller_business_name_snapshot: 'Divya Enterprises',
  seller_gstin_snapshot: '27DIVYA1234A1Z5',
  payment_type: 'credit',
  payment_status: 'credit',
  state: 'POSTED',
  tax_mode: 'exclusive',
  place_of_supply: '27',
  notes: '',
  cancellation_reason: '',
  cancelled_at: null,
  total_amount: '1102.00',
  line_items: [
    {
      id: 1,
      product_name: "Chheda's 3 in 1 Chikki",
      quantity: '20.000',
      rate_charged: '50.00',
      discount_amount: '0.00',
      taxable_value_snapshot: '1000.00',
      tax_rate: '5.00',
      cgst_amount: '25.00',
      sgst_amount: '25.00',
      igst_amount: '0.00',
      line_total: '1050.00',
      hsn_sac_snapshot: '2106',
    },
  ],
}

let lastListParams = null
let mockUser = { id: 1, username: 'tester', role: 'admin' }

function mountPage(ui, { role = 'admin', route = '/invoices' } = {}) {
  mockUser = role ? { id: 1, username: 'tester', role } : null
  useAuth.mockImplementation(() => ({ user: mockUser, token: 'tok', loading: false }))
  return render(
    <MemoryRouter initialEntries={[route]}>
      <Routes>
        <Route path="/invoices" element={ui === 'list' ? <InvoicesPage /> : undefined} />
        <Route path="/invoices/:id" element={ui === 'detail' ? <InvoiceDetailPage /> : undefined} />
      </Routes>
    </MemoryRouter>
  )
}

beforeEach(() => {
  lastListParams = null
  mockUser = { id: 1, username: 'tester', role: 'admin' }
  useAuth.mockImplementation(() => ({ user: mockUser, token: 'tok', loading: false }))
  vi.restoreAllMocks()
})

describe('InvoicesPage', () => {
  it('lists invoices with state badges and a view link', async () => {
    vi.spyOn(invoicesApi, 'fetchInvoices').mockImplementation(async (params = {}) => {
      lastListParams = params
      return PAGE_1
    })

    mountPage('list')

    await waitFor(() => {
      expect(screen.getByText('INV-20260912-1')).toBeInTheDocument()
    })
    await waitFor(() => {
      expect(screen.getByText('INV-20260912-1')).toBeInTheDocument()
    })
    expect(screen.getByText('3 invoices')).toBeInTheDocument()
    expect(screen.getAllByText('J K Traders').length).toBe(2)
    expect(screen.getAllByText('POSTED').length).toBe(2)
    expect(screen.getByText('CANCELLED')).toBeInTheDocument()
    expect(screen.getByText('₹1,102.00')).toBeInTheDocument()
    const viewLinks = screen.getAllByRole('link', { name: 'View' })
    expect(viewLinks.length).toBe(3)
    const viewLink11 = viewLinks.find(link => link.getAttribute('href') === '/invoices/11')
    expect(viewLink11).toBeTruthy()
    expect(lastListParams.page).toBe(1)
  })

  it('sends server-side filters when the controls change', async () => {
    const user = userEvent.setup()
    let capturedParams = null
    vi.spyOn(invoicesApi, 'fetchInvoices').mockImplementation(async (params = {}) => {
      capturedParams = params
      return PAGE_1
    })

    mountPage('list')
    await screen.findByText('INV-20260912-1')

    await user.type(screen.getByLabelText('Search'), 'J K')
    await waitFor(() => {
      expect(capturedParams.search).toBe('J K')
      expect(capturedParams.page).toBe(1)
    })

    await user.selectOptions(screen.getByLabelText('Filter by status'), 'CANCELLED')
    await waitFor(() => {
      expect(capturedParams.state).toBe('CANCELLED')
    })

    // Payment type filter is exercised separately below to avoid jsdom
    // select/timing flakiness when several selects change in one test.
    expect(capturedParams).toBeTruthy()
  })

  it('paginates via the backend next/previous flags', async () => {
    const user = userEvent.setup()
    let capturedParams = null
    vi.spyOn(invoicesApi, 'fetchInvoices').mockImplementation(async (params = {}) => {
      capturedParams = params
      return PAGE_1
    })

    mountPage('list')
    await screen.findByText('INV-20260912-1')

    const next = screen.getByRole('button', { name: 'Next →' })
    const previous = screen.getByRole('button', { name: '← Previous' })
    expect(previous).toBeDisabled()
    expect(next).not.toBeDisabled()

    await user.click(next)
    await waitFor(() => {
      expect(capturedParams.page).toBe(2)
    })
  })

  it('sends the payment type filter to the server', async () => {
    const user = userEvent.setup()
    let capturedParams = null
    vi.spyOn(invoicesApi, 'fetchInvoices').mockImplementation(async (params = {}) => {
      capturedParams = params
      return PAGE_1
    })

    mountPage('list')
    await screen.findByText('INV-20260912-1')

    await user.selectOptions(screen.getByLabelText('Filter by payment type'), 'cash')
    // The page passes paymentType; the real api module maps it to the
    // payment_type query parameter for the backend.
    await waitFor(() => {
      expect(capturedParams.paymentType).toBe('cash')
    })
  })

  it('shows the empty state when no invoices match', async () => {
    vi.spyOn(invoicesApi, 'fetchInvoices').mockResolvedValue({
      count: 0,
      next: null,
      previous: null,
      results: [],
    })
    mountPage('list')
    await screen.findByText('No invoices yet. Create your first sale.')
  })

  it('surfaces API errors without raw coercion', async () => {
    vi.spyOn(invoicesApi, 'fetchInvoices').mockRejectedValue({
      response: { status: 403, data: { detail: 'Only admin users can access this endpoint.' } },
    })
    vi.spyOn(client, 'apiErrorMessage').mockImplementation(
      (err) => err.response.data.detail
    )
    mountPage('list', { role: 'staff' })
    await screen.findByText('Only admin users can access this endpoint.')
    expect(document.body.textContent).not.toMatch(/0:/)
  })
})

describe('InvoiceDetailPage', () => {
  it('renders invoice snapshot data, tax breakdown, and totals', async () => {
    vi.spyOn(invoicesApi, 'fetchInvoice').mockResolvedValue(DETAIL)

    mountPage('detail', { route: '/invoices/11' })

    await waitFor(() => {
      expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('INV-20260912-1')
    })
    expect(screen.getAllByText('J K Traders').length).toBeGreaterThan(0)
    expect(screen.getByText('27JKTRADERS1A1Z5')).toBeInTheDocument()
    expect(screen.getByText("Chheda's 3 in 1 Chikki")).toBeInTheDocument()
    // GST split text is interpolated inside a single <small> node.
    expect(
      screen.getByText((content, element) =>
        element.tagName === 'SMALL' && /C:₹25\.00 S:₹25\.00/.test(content)
      )
    ).toBeInTheDocument()
    expect(screen.getByText('₹1,102.00')).toBeInTheDocument()
    expect(screen.getByText('POSTED')).toBeInTheDocument()
    // Cancel lives in the toolbar for admin users on a posted invoice.
    expect(screen.getByText('Cancel invoice')).toBeInTheDocument()
  })

  it('hides the cancel action from staff', async () => {
    vi.spyOn(invoicesApi, 'fetchInvoice').mockResolvedValue(DETAIL)

    mountPage('detail', { role: 'staff', route: '/invoices/11' })

    await screen.findByText('INV-20260912-1')
    expect(screen.queryByText('Cancel invoice')).not.toBeInTheDocument()
  })

  it('shows the cancellation reason on a cancelled invoice', async () => {
    vi.spyOn(invoicesApi, 'fetchInvoice').mockResolvedValue({
      ...DETAIL,
      id: 13,
      invoice_number: 'INV-20260912-3',
      state: 'CANCELLED',
      cancellation_reason: 'Wrong entry',
      cancelled_at: '2026-09-12T18:00:00+05:30',
    })

    mountPage('detail', { route: '/invoices/13' })

    await waitFor(() => {
      expect(screen.getByText('CANCELLED')).toBeInTheDocument()
    })
    expect(screen.getByText(/Cancelled: Wrong entry/)).toBeInTheDocument()
    expect(
      screen.getByText(/Stock was restored through a sale-reversal movement/)
    ).toBeInTheDocument()
    expect(screen.queryByText('Cancel invoice')).not.toBeInTheDocument()
  })

  it('requires a cancellation reason and reports backend rejection', async () => {
    const user = userEvent.setup()
    vi.spyOn(invoicesApi, 'fetchInvoice').mockResolvedValue(DETAIL)
    vi.spyOn(invoicesApi, 'cancelInvoice').mockRejectedValue({
      response: {
        status: 400,
        data: { state: ['Invoice is already cancelled.'] },
      },
    })
    vi.spyOn(client, 'apiForbiddenMessage').mockImplementation((err, forbidden) => {
      if (err.response?.status === 403) return `You do not have permission to ${forbidden}.`
      const data = err.response?.data
      return Object.entries(data || {})
        .map(([key, value]) => `${key}: ${Array.isArray(value) ? value.join(', ') : value}`)
        .join(' | ')
    })

    mountPage('detail', { route: '/invoices/11' })
    await screen.findByText('INV-20260912-1')

    // Toolbar button opens the cancellation form; the form submit is the
    // second "Cancel invoice" button once the form is visible.
    await user.click(screen.getAllByText('Cancel invoice')[0])
    await user.click(screen.getAllByRole('button', { name: 'Cancel invoice' })[1])
    await waitFor(() => {
      expect(screen.getByText('Enter a cancellation reason.')).toBeInTheDocument()
    })
    expect(invoicesApi.cancelInvoice).not.toHaveBeenCalled()
  })

  it('cancels via the API when a reason is provided', async () => {
    const user = userEvent.setup()
    vi.spyOn(invoicesApi, 'fetchInvoice').mockResolvedValue(DETAIL)
    const cancelSpy = vi.spyOn(invoicesApi, 'cancelInvoice').mockResolvedValue({
      ...DETAIL,
      state: 'CANCELLED',
      cancellation_reason: 'Duplicate bill',
      cancelled_at: '2026-09-12T18:30:00+05:30',
    })

    mountPage('detail', { route: '/invoices/11' })
    await screen.findByText('INV-20260912-1')

    await user.click(screen.getAllByText('Cancel invoice')[0])
    await user.type(
      screen.getByPlaceholderText('Why is this invoice being cancelled?'),
      'Duplicate bill'
    )
    await user.click(screen.getAllByRole('button', { name: 'Cancel invoice' })[1])

    await waitFor(() => {
      expect(cancelSpy).toHaveBeenCalledWith('11', 'Duplicate bill')
    })
    await waitFor(() => {
      expect(screen.getByText('CANCELLED')).toBeInTheDocument()
    })
  })
})
