import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import SupplierDetailPage from '../pages/SupplierDetailPage'
import NewPurchasePage from '../pages/NewPurchasePage'
import * as suppliersApi from '../api/suppliers'
import * as purchasesApi from '../api/purchases'

const useAuth = vi.hoisted(() => vi.fn(() => ({
  user: { id: 1, username: 'admin_user', role: 'admin' },
  token: 'mock-token',
  loading: false,
})))
vi.mock('../context/AuthContext', () => ({ useAuth }))

const SAMPLE_SUPPLIER_A = {
  id: 10,
  name: 'Supplier Alpha Traders',
  contact_info: '9820098200',
  gstin: '27AABCU9603R1ZM',
  state: 'Maharashtra',
  state_code: '27',
  is_active: true,
  address: 'Mumbai',
}

const SAMPLE_PRICING_A = {
  supplier_id: 10,
  supplier_name: 'Supplier Alpha Traders',
  is_active: true,
  pricing: [
    {
      id: 101,
      supplier: 10,
      supplier_name: 'Supplier Alpha Traders',
      mrp: '5.00',
      rate_per_piece: '3.20',
      is_active: true,
    },
    {
      id: 102,
      supplier: 10,
      supplier_name: 'Supplier Alpha Traders',
      mrp: '10.00',
      rate_per_piece: '6.40',
      is_active: true,
    },
  ],
  available_mrps: ['5.00', '10.00', '20.00'],
}

const SAMPLE_PRODUCT_A = {
  id: 101,
  name: 'Product A (Chips 20g)',
  mrp: '5.00',
  current_stock: '100.000',
  base_unit: 'piece',
  tax_rate: '5.00',
  sku: 'CHIPS-5',
}

const SAMPLE_PRODUCT_B = {
  id: 102,
  name: 'Product B (Sev 20g)',
  mrp: '5.00',
  current_stock: '80.000',
  base_unit: 'piece',
  tax_rate: '5.00',
  sku: 'SEV-5',
}

const SAMPLE_PRODUCT_C = {
  id: 103,
  name: 'Product C (Mix 100g)',
  mrp: '10.00',
  current_stock: '50.000',
  base_unit: 'piece',
  tax_rate: '5.00',
  sku: 'MIX-10',
  attributes: {
    units_per_master_box: 24,
  },
}

const SAMPLE_PRODUCT_UNCONFIGURED = {
  id: 104,
  name: 'Product D (Special 400g)',
  mrp: '20.00',
  current_stock: '30.000',
  base_unit: 'piece',
  tax_rate: '5.00',
  sku: 'SPEC-20',
}

describe('Supplier Purchase Pricing - SupplierDetailPage UI', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.spyOn(suppliersApi, 'fetchSupplier').mockResolvedValue(SAMPLE_SUPPLIER_A)
    vi.spyOn(suppliersApi, 'fetchSupplierPurchases').mockResolvedValue({
      results: [],
      count: 0,
      next: null,
      previous: null,
    })
    vi.spyOn(suppliersApi, 'fetchSupplierPricing').mockResolvedValue(SAMPLE_PRICING_A)
    vi.spyOn(suppliersApi, 'saveSupplierPricing').mockResolvedValue({
      id: 103,
      supplier: 10,
      mrp: '15.00',
      rate_per_piece: '9.60',
      is_active: true,
    })
    vi.spyOn(suppliersApi, 'deleteSupplierPricing').mockResolvedValue({})

    useAuth.mockReturnValue({
      user: { id: 1, username: 'admin_user', role: 'admin' },
      token: 'mock-token',
      loading: false,
    })
  })

  it('renders Supplier Purchase Rates section with MRP slabs from catalogue and configured rates', async () => {
    render(
      <MemoryRouter initialEntries={['/suppliers/10']}>
        <Routes>
          <Route path="/suppliers/:id" element={<SupplierDetailPage />} />
        </Routes>
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByRole('heading', { level: 1, name: 'Supplier Alpha Traders' })).toBeInTheDocument()
      expect(screen.getByText('Supplier Purchase Rates')).toBeInTheDocument()
    })

    // Check MRP slabs displayed
    expect(screen.getByText('₹5.00')).toBeInTheDocument()
    expect(screen.getByText('₹10.00')).toBeInTheDocument()
    expect(screen.getByText('₹20.00')).toBeInTheDocument()

    // Check rate values for MRP slabs
    expect(screen.getByLabelText(/Rate for MRP ₹5.00/i)).toHaveValue(3.2)
    expect(screen.getByLabelText(/Rate for MRP ₹10.00/i)).toHaveValue(6.4)
    expect(screen.getByLabelText(/Rate for MRP ₹20.00/i)).toHaveValue(null)

    // Check status badges
    const configuredBadges = screen.getAllByText('Configured')
    expect(configuredBadges.length).toBe(2)
    expect(screen.getByText('Not Set')).toBeInTheDocument()
  })

  it('allows admin to add a custom MRP slab rate', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/suppliers/10']}>
        <Routes>
          <Route path="/suppliers/:id" element={<SupplierDetailPage />} />
        </Routes>
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByText('Supplier Purchase Rates')).toBeInTheDocument()
    })

    // Click "+ Add Custom MRP Slab"
    const toggleBtn = screen.getByRole('button', { name: /\+ Add Custom MRP Slab/i })
    await user.click(toggleBtn)

    // Custom slab form fields
    const mrpInput = screen.getByLabelText(/Custom MRP/i)
    const rateInput = screen.getByLabelText(/Custom rate per piece/i)
    await user.type(mrpInput, '15.00')
    await user.type(rateInput, '9.60')

    // Submit form
    const addBtn = screen.getByRole('button', { name: 'Add Slab' })
    await user.click(addBtn)

    await waitFor(() => {
      expect(suppliersApi.saveSupplierPricing).toHaveBeenCalledWith(
        '10',
        expect.objectContaining({
          mrp: 15,
          rate_per_piece: 9.6,
        })
      )
    })
  })

  it('allows admin to update an existing MRP slab rate and remove pricing', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/suppliers/10']}>
        <Routes>
          <Route path="/suppliers/:id" element={<SupplierDetailPage />} />
        </Routes>
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByLabelText(/Rate for MRP ₹5.00/i)).toBeInTheDocument()
    })

    // Edit rate for MRP ₹5.00 in table
    const rateInput = screen.getByLabelText(/Rate for MRP ₹5.00/i)
    await user.clear(rateInput)
    await user.type(rateInput, '3.30')

    // Click first Update button (MRP ₹5.00)
    const updateBtns = screen.getAllByRole('button', { name: 'Update' })
    await user.click(updateBtns[0])

    await waitFor(() => {
      expect(suppliersApi.saveSupplierPricing).toHaveBeenCalledWith(
        '10',
        expect.objectContaining({
          mrp: 5,
          rate_per_piece: 3.3,
        })
      )
    })

    // Click first Remove button (MRP ₹5.00)
    const removeBtns = screen.getAllByRole('button', { name: 'Remove' })
    await user.click(removeBtns[0])

    await waitFor(() => {
      expect(suppliersApi.deleteSupplierPricing).toHaveBeenCalledWith('10', 101)
    })
  })

  it('enforces read-only behavior for staff users', async () => {
    useAuth.mockReturnValue({
      user: { id: 2, username: 'staff_user', role: 'staff' },
      token: 'mock-token',
      loading: false,
    })

    render(
      <MemoryRouter initialEntries={['/suppliers/10']}>
        <Routes>
          <Route path="/suppliers/:id" element={<SupplierDetailPage />} />
        </Routes>
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByText('Supplier Purchase Rates')).toBeInTheDocument()
    })

    // "+ Add Custom MRP Slab" should not be rendered
    expect(screen.queryByRole('button', { name: /\+ Add Custom MRP Slab/i })).not.toBeInTheDocument()

    // Editable inputs should not be rendered; rates are displayed as read-only text
    expect(screen.queryByLabelText(/Rate for MRP ₹5.00/i)).not.toBeInTheDocument()
    expect(screen.getByText('₹3.20 / pc')).toBeInTheDocument()
    expect(screen.getByText('₹6.40 / pc')).toBeInTheDocument()
    expect(screen.getByText('Not configured')).toBeInTheDocument()

    // Action buttons should not be present
    expect(screen.queryByRole('button', { name: 'Update' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Remove' })).not.toBeInTheDocument()
  })
})

describe('Supplier Purchase Pricing - NewPurchasePage Integration', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.spyOn(purchasesApi, 'fetchWarehouses').mockResolvedValue([
      { id: 1, name: 'Main Warehouse', code: 'MAIN' },
    ])
    vi.spyOn(purchasesApi, 'fetchNextPurchaseNumber').mockResolvedValue('PI/26-27/000010')
    vi.spyOn(suppliersApi, 'fetchActiveSuppliers').mockResolvedValue([
      SAMPLE_SUPPLIER_A,
    ])
    vi.spyOn(suppliersApi, 'fetchSupplierPricing').mockResolvedValue(SAMPLE_PRICING_A)

    useAuth.mockReturnValue({
      user: { id: 1, username: 'admin', role: 'admin' },
      token: 'tok',
      loading: false,
    })
  })

  it('auto-fills same supplier rate for multiple products with same MRP (MRP 5 -> 3.20) and distinct rate for MRP 10 -> 6.40', async () => {
    vi.spyOn(purchasesApi, 'searchPurchaseProducts').mockResolvedValue({
      data: { results: [SAMPLE_PRODUCT_A, SAMPLE_PRODUCT_B, SAMPLE_PRODUCT_C] },
    })

    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <NewPurchasePage />
      </MemoryRouter>
    )

    await waitFor(() => expect(screen.getByText('New purchase')).toBeInTheDocument())

    // 1. Select Supplier Alpha
    const supplierInput = screen.getByPlaceholderText(/Search active suppliers/i)
    await user.type(supplierInput, 'Alpha')

    await waitFor(() => expect(screen.getByRole('button', { name: new RegExp('Supplier Alpha Traders') })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: new RegExp('Supplier Alpha Traders') }))

    // 2. Add Product A (MRP ₹5.00)
    const productInput = screen.getByPlaceholderText('Search products by name to add...')
    await user.type(productInput, 'Product A')
    await waitFor(() => expect(screen.getByRole('button', { name: new RegExp('Product A \\(Chips 20g\\)') })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: new RegExp('Product A \\(Chips 20g\\)') }))

    // 3. Add Product B (also MRP ₹5.00)
    await user.type(productInput, 'Product B')
    await waitFor(() => expect(screen.getByRole('button', { name: new RegExp('Product B \\(Sev 20g\\)') })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: new RegExp('Product B \\(Sev 20g\\)') }))

    // 4. Add Product C (MRP ₹10.00)
    await user.type(productInput, 'Product C')
    await waitFor(() => expect(screen.getByRole('button', { name: new RegExp('Product C \\(Mix 100g\\)') })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: new RegExp('Product C \\(Mix 100g\\)') }))

    // 5. Verify Product A and Product B both receive ₹3.20/pc, and Product C receives ₹6.40/pc
    const rateInputs = screen.getAllByLabelText(/Purchase rate per piece/i)
    expect(rateInputs[0]).toHaveValue(3.2)
    expect(rateInputs[1]).toHaveValue(3.2)
    expect(rateInputs[2]).toHaveValue(6.4)

    // Badges indicate supplier rate with MRP
    expect(screen.getAllByText('Supplier rate (MRP ₹5.00): ₹3.20/pc').length).toBe(2)
    expect(screen.getByText('Supplier rate (MRP ₹10.00): ₹6.40/pc')).toBeInTheDocument()
  })

  it('leaves rate empty for manual entry when product MRP has no configured supplier rate', async () => {
    vi.spyOn(purchasesApi, 'searchPurchaseProducts').mockResolvedValue({
      data: { results: [SAMPLE_PRODUCT_UNCONFIGURED] },
    })

    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <NewPurchasePage />
      </MemoryRouter>
    )

    await waitFor(() => expect(screen.getByText('New purchase')).toBeInTheDocument())

    // Select Supplier Alpha
    const supplierInput = screen.getByPlaceholderText(/Search active suppliers/i)
    await user.type(supplierInput, 'Alpha')

    await waitFor(() => expect(screen.getByRole('button', { name: new RegExp('Supplier Alpha Traders') })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: new RegExp('Supplier Alpha Traders') }))

    // Add unconfigured product (MRP ₹20.00)
    const productInput = screen.getByPlaceholderText('Search products by name to add...')
    await user.type(productInput, 'Product D')

    await waitFor(() => expect(screen.getByRole('button', { name: new RegExp('Product D \\(Special 400g\\)') })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: new RegExp('Product D \\(Special 400g\\)') }))

    // Rate should be empty
    const rateInput = screen.getByLabelText(/Purchase rate per piece/i)
    expect(rateInput).toHaveValue(null)
    expect(screen.queryByText(/Supplier rate/i)).not.toBeInTheDocument()

    // User can manually enter rate
    await user.type(rateInput, '14.50')
    expect(rateInput).toHaveValue(14.5)
  })

  it('allows manual override of auto-filled rate and marks line as overridden', async () => {
    vi.spyOn(purchasesApi, 'searchPurchaseProducts').mockResolvedValue({
      data: { results: [SAMPLE_PRODUCT_A] },
    })

    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <NewPurchasePage />
      </MemoryRouter>
    )

    await waitFor(() => expect(screen.getByText('New purchase')).toBeInTheDocument())

    // Select Supplier Alpha
    const supplierInput = screen.getByPlaceholderText(/Search active suppliers/i)
    await user.type(supplierInput, 'Alpha')
    await waitFor(() => expect(screen.getByRole('button', { name: new RegExp('Supplier Alpha Traders') })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: new RegExp('Supplier Alpha Traders') }))

    // Add product A (auto-fills ₹3.20)
    const productInput = screen.getByPlaceholderText('Search products by name to add...')
    await user.type(productInput, 'Product A')
    await waitFor(() => expect(screen.getByRole('button', { name: new RegExp('Product A \\(Chips 20g\\)') })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: new RegExp('Product A \\(Chips 20g\\)') }))

    // Overwrite rate with 3.35
    const rateInput = screen.getByLabelText(/Purchase rate per piece/i)
    await user.clear(rateInput)
    await user.type(rateInput, '3.35')

    expect(rateInput).toHaveValue(3.35)
    expect(screen.getByText('Manually overridden')).toBeInTheDocument()
  })
})
