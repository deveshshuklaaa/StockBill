import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import NewInvoicePage from '../pages/NewInvoicePage'
import * as customersApi from '../api/customers'
import api from '../api/client'

const useAuth = vi.hoisted(() => vi.fn(() => ({ user: { id: 1, username: 'admin', role: 'admin' }, token: 'tok', loading: false })))
vi.mock('../context/AuthContext', () => ({ useAuth }))

const SAMPLE_CUSTOMER = {
  id: 42,
  name: 'ABC Traders',
  customer_type: 'B2B',
  contact_info: '9820098200',
  gstin: '27AABCU9603R1ZM',
  state: 'Maharashtra',
  state_code: '27',
  is_active: true,
}

const SAMPLE_PRODUCT = {
  id: 101,
  name: "Chheda's Salt-n-Pepper Banana Chips",
  mrp: '10.00',
  current_stock: '500.000',
  base_unit: 'piece',
  tax_rate: '5.00',
  attributes: {
    units_per_master_box: 100,
    net_weight: 0.045,
  },
}

describe('NewInvoicePage Line Item Layout and Functionality', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.spyOn(api, 'get').mockImplementation((url, config) => {
      if (url === '/customers/') {
        return Promise.resolve({ data: { results: [SAMPLE_CUSTOMER] } })
      }
      if (url === `/customers/${SAMPLE_CUSTOMER.id}/report/`) {
        return Promise.resolve({ data: { outstanding_balance: '1500.00' } })
      }
      if (url === '/products/') {
        return Promise.resolve({ data: { results: [SAMPLE_PRODUCT] } })
      }
      return Promise.resolve({ data: {} })
    })

    vi.spyOn(customersApi, 'fetchCustomerMRPPricing').mockResolvedValue({
      pricing: [
        {
          mrp: '10.00',
          rate_per_piece: '8.10',
          is_active: true,
        },
      ],
    })
  })

  it('renders line item with visible MRP, auto-filled customer rate, editable rate, compact discount %, and line total', async () => {
    const user = userEvent.setup()

    render(
      <MemoryRouter>
        <NewInvoicePage />
      </MemoryRouter>
    )

    // Wait for customer list to load
    await waitFor(() => {
      expect(screen.getByText('Walk-in (no account)')).toBeInTheDocument()
    })

    // Search and select customer
    const customerSearch = screen.getByLabelText('Search customer')
    await user.type(customerSearch, 'ABC')
    await waitFor(() => {
      expect(screen.getByText('ABC Traders')).toBeInTheDocument()
    })
    await user.click(screen.getByText('ABC Traders'))

    // Search and add product
    const productSearch = screen.getByLabelText('Search products')
    await user.type(productSearch, 'Banana')
    await waitFor(() => {
      expect(screen.getByText("Chheda's Salt-n-Pepper Banana Chips")).toBeInTheDocument()
    })
    await user.click(screen.getByText("Chheda's Salt-n-Pepper Banana Chips"))

    // 1. Verify product name is in line item
    await waitFor(() => {
      expect(screen.getByText("Chheda's Salt-n-Pepper Banana Chips")).toBeInTheDocument()
    })

    // 2. Verify selected product MRP is rendered read-only
    const mrpInput = screen.getByLabelText(/MRP for Chheda's Salt-n-Pepper Banana Chips/i)
    expect(mrpInput).toBeInTheDocument()
    expect(mrpInput).toHaveValue('₹10.00')
    expect(mrpInput).toHaveAttribute('readonly')

    // 3. Verify Rate / Piece input is present with auto-filled customer rate ₹8.10
    const rateInput = screen.getByLabelText(/Selling rate per piece for Chheda's Salt-n-Pepper Banana Chips/i)
    expect(rateInput).toBeInTheDocument()
    expect(rateInput).toHaveValue(8.1)

    // 4. Verify compact customer rate indicator is present
    expect(screen.getByText(/✓ Customer MRP rate \(₹8.10\/pc\)/i)).toBeInTheDocument()

    // 5. Verify Discount input and % indicator
    const discInput = screen.getByLabelText(/Discount for Chheda's Salt-n-Pepper Banana Chips/i)
    expect(discInput).toBeInTheDocument()
    expect(discInput).toHaveValue(0)
    expect(screen.getByText('%')).toBeInTheDocument()

    // 6. Verify GST slab and line total calculation (1 pc @ 8.10 with 5% GST = 8.10 * 1.05 = 8.505)
    expect(screen.getAllByText('5%').length).toBeGreaterThan(0)
    expect(screen.getAllByText('₹8.505').length).toBe(2) // in line item and grand total
  })

  it('allows manual rate override and updates calculations accordingly', async () => {
    const user = userEvent.setup()

    render(
      <MemoryRouter>
        <NewInvoicePage />
      </MemoryRouter>
    )

    // Add product directly (walk-in customer has no customer MRP pricing)
    const productSearch = screen.getByLabelText('Search products')
    await user.type(productSearch, 'Banana')
    await waitFor(() => {
      expect(screen.getByText("Chheda's Salt-n-Pepper Banana Chips")).toBeInTheDocument()
    })
    await user.click(screen.getByText("Chheda's Salt-n-Pepper Banana Chips"))

    // Verify rate input is empty for walk-in with no customer pricing
    const rateInput = screen.getByLabelText(/Selling rate per piece for Chheda's Salt-n-Pepper Banana Chips/i)
    expect(rateInput).toHaveValue(null)
    expect(screen.getByText(/No MRP rate configured/i)).toBeInTheDocument()

    // Manually enter rate 12.50
    await user.type(rateInput, '12.50')
    expect(rateInput).toHaveValue(12.5)
    expect(screen.getByText('(manual override)')).toBeInTheDocument()

    // Verify calculation: 1 pc @ 12.50 + 5% GST = 12.50 * 1.05 = 13.125
    expect(screen.getAllByText('₹13.125').length).toBe(2) // line total + grand total

    // Update quantity to 10
    const qtyInput = screen.getByLabelText(/Quantity for Chheda's Salt-n-Pepper Banana Chips/i)
    await user.clear(qtyInput)
    await user.type(qtyInput, '10')

    // 10 pcs @ 12.50 = 125.00 + 5% GST (6.25) = 131.25
    await waitFor(() => {
      expect(screen.getAllByText('₹131.25').length).toBe(2)
    })

    // Apply discount of 5.00
    const discInput = screen.getByLabelText(/Discount for Chheda's Salt-n-Pepper Banana Chips/i)
    await user.clear(discInput)
    await user.type(discInput, '5')

    // Net taxable: 125.00 - 5.00 = 120.00, GST 5% = 6.00, total = 126.00
    await waitFor(() => {
      expect(screen.getAllByText('₹126.00').length).toBe(2)
    })
  })
})
