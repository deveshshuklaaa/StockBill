import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CustomerDetailPage from '../pages/CustomerDetailPage'
import * as customersApi from '../api/customers'

const useAuth = vi.hoisted(() => vi.fn(() => ({
  user: { id: 1, username: 'admin_user', role: 'admin' },
  token: 'mock-token',
  loading: false,
})))
vi.mock('../context/AuthContext', () => ({ useAuth }))

const SAMPLE_CUSTOMER = {
  id: 42,
  name: 'ABC Traders',
  contact_info: '9820098200',
  gstin: '27AABCU9603R1ZM',
  state: 'Maharashtra',
  state_code: '27',
  is_active: true,
  is_regular: true,
  customer_type: 'B2B',
  credit_limit: '50000.00',
  outstanding_balance: '12000.00',
  available_credit: '38000.00',
}

const SAMPLE_PRICING_RESPONSE = {
  customer_id: 42,
  customer_name: 'ABC Traders',
  pricing: [
    {
      mrp: '10.00',
      rate_per_piece: '7.00',
      pricing_id: 1,
      is_configured: true,
      product_count: 5,
    },
    {
      mrp: '5.00',
      rate_per_piece: null,
      pricing_id: null,
      is_configured: false,
      product_count: 2,
    },
    {
      mrp: '50.00',
      rate_per_piece: '35.00',
      pricing_id: 2,
      is_configured: true,
      product_count: 1,
    },
  ],
}

describe('CustomerMRPPricing Frontend', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.spyOn(customersApi, 'fetchCustomer').mockResolvedValue(SAMPLE_CUSTOMER)
    vi.spyOn(customersApi, 'fetchCustomerReport').mockResolvedValue({
      invoices: [],
      payments: [],
      statement_rows: [],
      totals: { invoiced: '0.00', paid: '0.00', outstanding: '0.00' },
    })
    vi.spyOn(customersApi, 'fetchCustomerMRPPricing').mockResolvedValue(SAMPLE_PRICING_RESPONSE)
    vi.spyOn(customersApi, 'saveCustomerMRPPricing').mockResolvedValue({
      id: 3,
      customer: 42,
      mrp: '5.00',
      rate_per_piece: '3.50',
      is_active: true,
    })

    useAuth.mockReturnValue({
      user: { id: 1, username: 'admin_user', role: 'admin' },
      token: 'mock-token',
      loading: false,
    })
  })

  it('renders Customer Pricing section with active MRP slabs and configured rates', async () => {
    render(
      <MemoryRouter initialEntries={['/customers/42']}>
        <Routes>
          <Route path="/customers/:id" element={<CustomerDetailPage />} />
        </Routes>
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByRole('heading', { level: 1, name: 'ABC Traders' })).toBeInTheDocument()
      expect(screen.getByText(/Customer MRP Pricing/i)).toBeInTheDocument()
    })

    // Verify MRP slabs are displayed
    expect(screen.getByText((_, el) => el?.tagName === 'STRONG' && el.textContent.includes('5.00'))).toBeInTheDocument()
    expect(screen.getByText((_, el) => el?.tagName === 'STRONG' && el.textContent.includes('10.00'))).toBeInTheDocument()
    expect(screen.getByText((_, el) => el?.tagName === 'STRONG' && el.textContent.includes('50.00'))).toBeInTheDocument()

    // Verify configured rate inputs
    expect(screen.getByLabelText(/Rate for MRP ₹10.00/i)).toHaveValue(7)
    expect(screen.getByLabelText(/Rate for MRP ₹50.00/i)).toHaveValue(35)
    expect(screen.getByText(/Rate is per piece/i)).toBeInTheDocument()
  })

  it('allows admin to edit and save pricing for an MRP slab', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/customers/42']}>
        <Routes>
          <Route path="/customers/:id" element={<CustomerDetailPage />} />
        </Routes>
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByText('ABC Traders')).toBeInTheDocument()
    })

    // Type new rate for ₹5.00 slab
    const rateInput = screen.getByLabelText(/Rate for MRP ₹5.00/i)
    await user.clear(rateInput)
    await user.type(rateInput, '3.50')

    const updateBtns = screen.getAllByRole('button', { name: /Update/i })
    await user.click(updateBtns[0])

    await waitFor(() => {
      expect(customersApi.saveCustomerMRPPricing).toHaveBeenCalledWith(
        '42',
        expect.objectContaining({
          mrp: 5,
          rate_per_piece: 3.5,
        })
      )
    })
  })

  it('hides edit and add actions for staff role', async () => {
    useAuth.mockReturnValue({
      user: { id: 2, username: 'staff_user', role: 'staff' },
      token: 'mock-token',
      loading: false,
    })

    render(
      <MemoryRouter initialEntries={['/customers/42']}>
        <Routes>
          <Route path="/customers/:id" element={<CustomerDetailPage />} />
        </Routes>
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByText('ABC Traders')).toBeInTheDocument()
    })

    // Staff cannot edit pricing
    expect(screen.queryByRole('button', { name: /Set Rate/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Edit/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /\+ Custom MRP/i })).not.toBeInTheDocument()
  })
})
