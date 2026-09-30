import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import OpeningStockListPage from '../pages/OpeningStockListPage'
import NewOpeningStockPage from '../pages/NewOpeningStockPage'
import OpeningStockDetailPage from '../pages/OpeningStockDetailPage'
import * as openingStockApi from '../api/openingStock'
import * as inventoryApi from '../api/inventory'
import * as warehousesApi from '../api/warehouses'

const useAuth = vi.hoisted(() => vi.fn(() => ({
  user: { id: 1, username: 'admin_user', role: 'admin' },
  token: 'mock-token',
  loading: false,
})))
vi.mock('../context/AuthContext', () => ({ useAuth }))

const SAMPLE_LIST = {
  count: 2,
  next: null,
  previous: null,
  results: [
    {
      id: 1,
      opening_stock_number: 'OS/26-27/0001',
      product: 10,
      product_name: 'Chheda Mix 192',
      product_sku: 'MIX-192',
      warehouse: 1,
      warehouse_name: 'Main Warehouse',
      warehouse_code: 'MAIN',
      quantity: '5.000',
      unit: 'master box',
      conversion_factor: '192.000',
      base_quantity: '960.000',
      cost_per_piece: '7.10',
      opening_value: '6816.00',
      effective_date: '2026-10-01',
      reason: 'Pre-existing Stock',
      note: 'Verified count',
      created_by_username: 'admin_user',
      created_at: '2026-10-01T10:00:00Z',
    },
    {
      id: 2,
      opening_stock_number: 'OS/26-27/0002',
      product: 11,
      product_name: 'Yellow Banana Chips',
      product_sku: 'BAN-01',
      warehouse: 1,
      warehouse_name: 'Main Warehouse',
      quantity: '100.000',
      unit: 'piece',
      conversion_factor: '1.000',
      base_quantity: '100.000',
      cost_per_piece: '15.00',
      opening_value: '1500.00',
      effective_date: '2026-10-01',
      reason: 'Physical Count',
      note: '',
      created_by_username: 'admin_user',
      created_at: '2026-10-01T11:00:00Z',
    },
  ],
}

const SAMPLE_PRODUCTS = [
  {
    id: 10,
    name: 'Chheda Mix 192',
    sku: 'MIX-192',
    mrp: '10.00',
    attributes: { units_per_master_box: 192 },
  },
  {
    id: 11,
    name: 'Yellow Banana Chips',
    sku: 'BAN-01',
    mrp: '20.00',
    attributes: {},
  },
]

const SAMPLE_WAREHOUSES = [
  { id: 1, name: 'Main Warehouse', code: 'MAIN', is_active: true },
]

describe('Opening Stock Frontend Flow', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.spyOn(openingStockApi, 'fetchOpeningStocks').mockResolvedValue(SAMPLE_LIST)
    vi.spyOn(openingStockApi, 'fetchOpeningStock').mockResolvedValue(SAMPLE_LIST.results[0])
    vi.spyOn(openingStockApi, 'fetchNextOpeningStockNumber').mockResolvedValue('OS/26-27/0003')
    vi.spyOn(openingStockApi, 'previewOpeningStock').mockResolvedValue({
      product_name: 'Chheda Mix 192',
      warehouse_name: 'Main Warehouse',
      unit: 'master box',
      conversion_factor: 192,
      base_quantity: '960.000',
      cost_per_piece: '7.10',
      opening_value: '6816.00',
    })
    vi.spyOn(openingStockApi, 'createOpeningStock').mockResolvedValue({
      id: 3,
      opening_stock_number: 'OS/26-27/0003',
      base_quantity: '960.000',
      opening_value: '6816.00',
    })
    vi.spyOn(inventoryApi, 'fetchProducts').mockResolvedValue(SAMPLE_PRODUCTS)
    vi.spyOn(warehousesApi, 'fetchWarehouses').mockResolvedValue(SAMPLE_WAREHOUSES)

    useAuth.mockReturnValue({
      user: { id: 1, username: 'admin_user', role: 'admin' },
      token: 'mock-token',
      loading: false,
    })
  })

  it('renders opening stock list with correct entries and stats', async () => {
    render(
      <MemoryRouter>
        <OpeningStockListPage />
      </MemoryRouter>
    )

    expect(screen.getByRole('heading', { level: 1, name: 'Opening Stock' })).toBeInTheDocument()
    await waitFor(() => {
      expect(screen.getByText('OS/26-27/0001')).toBeInTheDocument()
      expect(screen.getByText('OS/26-27/0002')).toBeInTheDocument()
    })

    expect(screen.getByText('Chheda Mix 192')).toBeInTheDocument()
    expect(screen.getByText('Yellow Banana Chips')).toBeInTheDocument()
    expect(screen.getAllByText('Pre-existing Stock').length).toBeGreaterThan(0)
    expect(screen.getByText('₹6,816.00')).toBeInTheDocument()
  })

  it('hides + New Opening Stock button for staff role on list page', async () => {
    useAuth.mockReturnValue({
      user: { id: 2, username: 'staff_user', role: 'staff' },
      token: 'mock-token',
      loading: false,
    })

    render(
      <MemoryRouter>
        <OpeningStockListPage />
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByText('OS/26-27/0001')).toBeInTheDocument()
    })

    expect(screen.queryByRole('link', { name: /\+ New Opening Stock/i })).not.toBeInTheDocument()
  })

  it('calculates preview and allows admin to create opening stock', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/inventory/opening-stock/new']}>
        <Routes>
          <Route path="/inventory/opening-stock/new" element={<NewOpeningStockPage />} />
          <Route path="/inventory/opening-stock" element={<div>Opening Stock List Page Mock</div>} />
        </Routes>
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByRole('heading', { level: 1, name: 'New Opening Stock Entry' })).toBeInTheDocument()
    })

    // Fill form
    const whSelect = screen.getByLabelText(/Warehouse \*/i)
    await user.selectOptions(whSelect, '1')

    const productSelect = screen.getByLabelText(/Product \*/i)
    await user.selectOptions(productSelect, '10')

    const unitSelect = screen.getByLabelText(/Unit of Entry \*/i)
    await user.selectOptions(unitSelect, 'master box')

    const qtyInput = screen.getByLabelText(/Entered Quantity \*/i)
    fireEvent.change(qtyInput, { target: { value: '5' } })

    const costInput = screen.getByLabelText(/Cost per Piece/i)
    fireEvent.change(costInput, { target: { value: '7.10' } })

    await waitFor(() => {
      expect(openingStockApi.previewOpeningStock).toHaveBeenCalledWith(
        expect.objectContaining({
          product: 10,
          warehouse: 1,
          quantity: 5,
          unit: 'master box',
          cost_per_piece: 7.1,
        })
      )
    })

    // Submit form
    const submitBtn = screen.getByRole('button', { name: /Post Opening Stock/i })
    await user.click(submitBtn)

    await waitFor(() => {
      expect(openingStockApi.createOpeningStock).toHaveBeenCalledWith(
        expect.objectContaining({
          product: 10,
          warehouse: 1,
          quantity: 5,
          unit: 'master box',
          cost_per_piece: 7.1,
          reason: 'Inventory Initialization',
        }),
        expect.anything()
      )
    })
  })

  it('renders immutable detail page with full snapshot information', async () => {
    render(
      <MemoryRouter initialEntries={['/inventory/opening-stock/1']}>
        <Routes>
          <Route path="/inventory/opening-stock/:id" element={<OpeningStockDetailPage />} />
        </Routes>
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByText('OS/26-27/0001')).toBeInTheDocument()
    })

    expect(screen.getByText('Chheda Mix 192')).toBeInTheDocument()
    expect(screen.getByText(/Main Warehouse/i)).toBeInTheDocument()
    expect(screen.getByText(/960 pcs/i)).toBeInTheDocument()
    expect(screen.getByText('₹7.10')).toBeInTheDocument()
    expect(screen.getByText('₹6,816.00')).toBeInTheDocument()
    expect(screen.getByText(/Immutable Historical Record/i)).toBeInTheDocument()
  })
})
