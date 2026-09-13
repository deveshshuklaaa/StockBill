// Regression tests for the customers + customer financial account UI.
//
// Covers: /customers list (server-side search wiring, active filter,
// authoritative outstanding from backend, pagination, empty/error states)
// and /customers/:id detail (identity/GST/credit info, invoice history
// links to the existing /invoices/:id route, payment history, backend-
// computed statement rows rendered verbatim, record-payment flow,
// reversal visibility by role) against the real API contract.
//
// The UI must never compute outstanding/available credit itself: these
// tests assert the exact backend values flow through unchanged.

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CustomersPage from '../pages/CustomersPage'
import CustomerDetailPage from '../pages/CustomerDetailPage'
import * as customersApi from '../api/customers'
import * as client from '../api/client'

const useAuth = vi.hoisted(() => vi.fn(() => ({ user: { id: 1, username: 'tester', role: 'admin' }, token: 'tok', loading: false })))
vi.mock('../context/AuthContext', () => ({ useAuth }))

const LIST_PAGE_1 = {
  count: 2,
  next: null,
  previous: null,
  results: [
    {
      id: 21,
      name: 'J K Traders',
      contact_info: '9820011122',
      gstin: '27JKTRADERS1A1Z5',
      state: 'Maharashtra',
      state_code: '27',
      customer_type: 'B2B',
      is_regular: true,
      is_active: true,
      credit_limit: '5000.00',
      outstanding_balance: '1102.00',
      available_credit: '3898.00',
    },
    {
      id: 22,
      name: 'Archived Store',
      contact_info: '',
      gstin: '',
      state: '',
      state_code: '',
      customer_type: 'B2C',
      is_regular: false,
      is_active: false,
      credit_limit: '0.00',
      outstanding_balance: '0.00',
      available_credit: '0.00',
    },
  ],
}

const DETAIL = {
  id: 21,
  name: 'J K Traders',
  contact_info: '9820011122',
  billing_address: 'Shop 2, Market',
  shipping_address: 'Shop 2, Market',
  state: 'Maharashtra',
  state_code: '27',
  pincode: '400001',
  customer_type: 'B2B',
  gst_registration_type: 'registered',
  gstin: '27JKTRADERS1A1Z5',
  credit_limit: '5000.00',
  credit_days: 15,
  opening_balance: '0.00',
  is_regular: true,
  is_active: true,
  outstanding_balance: '952.00',
  available_credit: '4048.00',
}

const REPORT = {
  customer_id: 21,
  customer_name: 'J K Traders',
  is_active: true,
  credit_limit: '5000.00',
  outstanding_balance: '952.00',
  available_credit: '4048.00',
  invoices: [
    {
      id: 11,
      invoice_number: 'INV-20260912-1',
      invoice_date: '2026-09-12',
      payment_status: 'partially_paid',
      total_amount: '1102.00',
      state: 'POSTED',
      payment_type: 'credit',
    },
  ],
  payments: [
    {
      id: 31,
      invoice_id: 11,
      invoice_number: 'INV-20260912-1',
      amount: '150.00',
      reversed_amount: '0.00',
      payment_date: '2026-09-13',
      notes: '',
    },
  ],
  statement: [
    { date: '2026-09-12', reference: 'INV-20260912-1', type: 'INVOICE', debit: '1102.00', credit: null, balance: '1102.00' },
    { date: '2026-09-13', reference: 'INV-20260912-1', type: 'PAYMENT', debit: null, credit: '150.00', balance: '952.00' },
    { date: '2026-09-13', reference: 'Reversal of payment #31', type: 'PAYMENT_REVERSAL', debit: '0.00', credit: null, balance: '952.00' },
  ],
  statement_closing_balance: '952.00',
}

let lastListParams = null
let mockUser = { id: 1, username: 'tester', role: 'admin' }

function mountPage(ui, { role = 'admin', route = '/customers' } = {}) {
  mockUser = role ? { id: 1, username: 'tester', role } : null
  useAuth.mockImplementation(() => ({ user: mockUser, token: 'tok', loading: false }))
  return render(
    <MemoryRouter initialEntries={[route]}>
      <Routes>
        <Route path="/customers" element={ui === 'list' ? <CustomersPage /> : undefined} />
        <Route path="/customers/:id" element={ui === 'detail' ? <CustomerDetailPage /> : undefined} />
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

describe('CustomersPage', () => {
  it('lists customers with authoritative outstanding and credit limit', async () => {
    vi.spyOn(customersApi, 'fetchCustomers').mockImplementation(async (params = {}) => {
      lastListParams = params
      return LIST_PAGE_1
    })

    mountPage('list')

    await screen.findByText('J K Traders')
    expect(screen.getByText('₹5,000.00')).toBeInTheDocument()
    expect(screen.getByText('₹1,102.00')).toBeInTheDocument()
    expect(screen.getAllByText('Archived').length).toBeGreaterThan(0)
    expect(lastListParams.page).toBe(1)

    const detailLink = screen.getAllByRole('link', { name: /J K Traders/ })[0]
    expect(detailLink.getAttribute('href')).toBe('/customers/21')
  })

  it('sends server-side search and status filters', async () => {
    const user = userEvent.setup()
    let capturedParams = null
    vi.spyOn(customersApi, 'fetchCustomers').mockImplementation(async (params = {}) => {
      capturedParams = params
      return LIST_PAGE_1
    })

    mountPage('list')
    await screen.findByText('J K Traders')

    await user.type(screen.getByLabelText('Search customers'), 'J K')
    await waitFor(() => {
      expect(capturedParams.search).toBe('J K')
      expect(capturedParams.page).toBe(1)
    })

    await user.selectOptions(screen.getByLabelText('Filter by status'), 'false')
    await waitFor(() => {
      expect(capturedParams.isActive).toBe('false')
    })
  })

  it('shows the empty state when no customers match', async () => {
    vi.spyOn(customersApi, 'fetchCustomers').mockResolvedValue({
      count: 0, next: null, previous: null, results: [],
    })
    mountPage('list')
    await screen.findByText('No customers yet.')
  })

  it('surfaces API errors without raw coercion', async () => {
    vi.spyOn(customersApi, 'fetchCustomers').mockRejectedValue({
      response: { status: 403, data: { detail: 'Only admin users can access this endpoint.' } },
    })
    vi.spyOn(client, 'apiErrorMessage').mockImplementation((err) => err.response.data.detail)

    mountPage('list', { role: 'staff' })
    await screen.findByText('Only admin users can access this endpoint.')
    expect(document.body.textContent).not.toMatch(/0:/)
  })
})

describe('CustomerDetailPage', () => {
  it('renders identity, GST, credit, invoice history links, and the backend statement verbatim', async () => {
    vi.spyOn(customersApi, 'fetchCustomer').mockResolvedValue(DETAIL)
    vi.spyOn(customersApi, 'fetchCustomerReport').mockResolvedValue(REPORT)

    mountPage('detail', { route: '/customers/21' })

    await screen.findByText('J K Traders')
    expect(screen.getByText('27JKTRADERS1A1Z5')).toBeInTheDocument()
    expect(screen.getByText('Shop 2, Market')).toBeInTheDocument()
    expect(screen.getByText('Maharashtra (27) · 400001')).toBeInTheDocument()
    // Outstanding/balances appear in the credit summary and statement
    // closing rows; assert the authoritative value is present.
    expect(screen.getAllByText('₹952.00').length).toBeGreaterThan(0)
    expect(screen.getByText(/Limit ₹5,000\.00/)).toBeInTheDocument()
    expect(screen.getByText(/Available ₹4,048\.00/)).toBeInTheDocument()

    // Invoice history reuses the existing invoice detail route.
    const invoiceLink = screen.getByRole('link', { name: 'View' })
    expect(invoiceLink.getAttribute('href')).toBe('/invoices/11')

    // Statement rows are the backend's exact values, never recomputed.
    expect(screen.getAllByText('₹1,102.00').length).toBeGreaterThan(0)
    expect(screen.getByText('Payment Reversal')).toBeInTheDocument()
    expect(screen.getAllByText('INV-20260912-1').length).toBeGreaterThan(0)

    const view = screen.getAllByText('J K Traders')
    expect(view.length).toBeGreaterThan(0)
  })

  it('records a payment through the backend API and refreshes the report', async () => {
    const user = userEvent.setup()
    vi.spyOn(customersApi, 'fetchCustomer').mockResolvedValue(DETAIL)
    const reportSpy = vi.spyOn(customersApi, 'fetchCustomerReport')
      .mockResolvedValue(REPORT)
    const recordSpy = vi.spyOn(customersApi, 'recordPayment').mockResolvedValue({
      id: 32, amount: '500.00', payment_method: 'cash',
    })

    mountPage('detail', { route: '/customers/21' })
    await screen.findByText('J K Traders')

    await user.click(screen.getByRole('button', { name: 'Record payment' }))
    await user.type(screen.getByPlaceholderText('e.g. 5000'), '500')
    await user.click(screen.getByRole('button', { name: 'Save payment' }))

    await waitFor(() => {
      expect(recordSpy).toHaveBeenCalledWith({
        customer: 21,
        invoice: null,
        amount: '500',
        paymentMethod: 'cash',
        referenceNumber: '',
        notes: '',
      })
    })
    // Report is re-fetched so outstanding comes from the backend again.
    await waitFor(() => {
      expect(reportSpy.mock.calls.length).toBeGreaterThan(1)
    })
  })

  it('requires a positive amount before calling the API', async () => {
    const user = userEvent.setup()
    vi.spyOn(customersApi, 'fetchCustomer').mockResolvedValue(DETAIL)
    vi.spyOn(customersApi, 'fetchCustomerReport').mockResolvedValue(REPORT)
    const recordSpy = vi.spyOn(customersApi, 'recordPayment')

    mountPage('detail', { route: '/customers/21' })
    await screen.findByText('J K Traders')

    await user.click(screen.getByRole('button', { name: 'Record payment' }))
    await user.click(screen.getByRole('button', { name: 'Save payment' }))

    await waitFor(() => {
      expect(screen.getByText('Enter a payment amount greater than zero.')).toBeInTheDocument()
    })
    expect(recordSpy).not.toHaveBeenCalled()
  })

  it('exposes payment reversal for admins only, with reason and amount', async () => {
    const user = userEvent.setup()
    vi.spyOn(customersApi, 'fetchCustomer').mockResolvedValue(DETAIL)
    vi.spyOn(customersApi, 'fetchCustomerReport').mockResolvedValue(REPORT)
    const reverseSpy = vi.spyOn(customersApi, 'reversePayment').mockResolvedValue({ id: 9 })

    mountPage('detail', { route: '/customers/21' })
    await screen.findByText('J K Traders')

    await user.click(screen.getByRole('button', { name: 'Reverse' }))
    await user.type(screen.getByLabelText('Reversal reason'), 'Entered twice')
    await user.type(screen.getByLabelText('Reversal amount'), '50')
    await user.click(screen.getByRole('button', { name: 'Reverse payment' }))

    await waitFor(() => {
      expect(reverseSpy).toHaveBeenCalledWith(31, '50', 'Entered twice')
    })
  })

  it('hides the reversal action from staff', async () => {
    vi.spyOn(customersApi, 'fetchCustomer').mockResolvedValue(DETAIL)
    vi.spyOn(customersApi, 'fetchCustomerReport').mockResolvedValue(REPORT)

    mountPage('detail', { role: 'staff', route: '/customers/21' })
    await screen.findByText('J K Traders')
    expect(screen.queryByText('Reverse')).not.toBeInTheDocument()
  })

  it('shows the empty states when there is no history', async () => {
    vi.spyOn(customersApi, 'fetchCustomer').mockResolvedValue(DETAIL)
    vi.spyOn(customersApi, 'fetchCustomerReport').mockResolvedValue({
      ...REPORT,
      invoices: [],
      payments: [],
      statement: [],
      statement_closing_balance: '0.00',
    })

    mountPage('detail', { route: '/customers/21' })
    await screen.findByText('J K Traders')
    expect(screen.getByText('No invoices for this customer yet.')).toBeInTheDocument()
    expect(screen.getByText('No payments recorded for this customer yet.')).toBeInTheDocument()
    expect(screen.getByText('No transactions yet.')).toBeInTheDocument()
  })
})
