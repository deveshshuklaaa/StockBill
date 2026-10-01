import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as inventoryApi from '../api/inventory'
import * as purchasesApi from '../api/purchases'
import * as transfersApi from '../api/transfers'
import NewWarehouseTransferPage from '../pages/NewWarehouseTransferPage'
import WarehouseTransferDetailPage from '../pages/WarehouseTransferDetailPage'
import WarehouseTransfersPage from '../pages/WarehouseTransfersPage'

const useAuth = vi.hoisted(() =>
  vi.fn(() => ({
    user: { id: 1, username: 'admin', role: 'admin' },
    token: 'tok',
    loading: false,
  }))
)
vi.mock('../context/AuthContext', () => ({ useAuth }))

const SAMPLE_PRODUCT_192 = {
  id: 181,
  name: "Chheda's Soya Snax",
  sku: 'TEST-SKU-192',
  mrp: '10.00',
  current_stock: '1000.000',
  cost_price: '6.20',
  base_unit: 'piece',
  attributes: {
    units_per_master_box: 192,
    net_weight: 0.038,
  },
}

const SAMPLE_PRODUCT_PIECE = {
  id: 182,
  name: 'Parle-G 100g',
  sku: 'PARLE-100',
  mrp: '10.00',
  current_stock: '500.000',
  cost_price: '7.50',
  base_unit: 'piece',
  attributes: {},
}

const SAMPLE_WAREHOUSES = [
  { id: 1, name: 'Main Hub', code: 'HUB' },
  { id: 2, name: 'Branch Store', code: 'BRANCH' },
]

const SAMPLE_TRANSFERS = [
  {
    id: 10,
    transfer_number: 'TRF/26-27/000001',
    effective_date: '2026-10-01',
    product: 181,
    product_name: "Chheda's Soya Snax",
    product_sku: 'TEST-SKU-192',
    source_warehouse: 1,
    source_warehouse_name: 'Main Hub',
    source_warehouse_code: 'HUB',
    destination_warehouse: 2,
    destination_warehouse_name: 'Branch Store',
    destination_warehouse_code: 'BRANCH',
    quantity: '2.000',
    unit: 'master box',
    conversion_factor: '192.000',
    base_quantity: '384.000',
    unit_cost_snapshot: '6.20',
    transfer_value: '2380.80',
    reason: 'Stock Replenishment',
    note: '',
    created_by_username: 'admin',
    created_at: '2026-10-01T10:00:00Z',
  },
]

describe('Warehouse Transfers Frontend Suite', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useAuth.mockReturnValue({
      user: { id: 1, username: 'admin', role: 'admin' },
      token: 'tok',
      loading: false,
    })
    vi.spyOn(purchasesApi, 'fetchWarehouses').mockResolvedValue(SAMPLE_WAREHOUSES)
    vi.spyOn(transfersApi, 'fetchNextTransferNumber').mockResolvedValue('TRF/26-27/000001')
    vi.spyOn(inventoryApi, 'fetchProductInventory').mockResolvedValue([
      {
        id: 10,
        product: 181,
        warehouse: 1,
        quantity_on_hand: '1000.000',
        average_cost: '6.20',
      },
      {
        id: 11,
        product: 181,
        warehouse: 2,
        quantity_on_hand: '50.000',
        average_cost: '5.00',
      },
    ])
  })

  describe('WarehouseTransfersPage', () => {
    it('renders list of transfers and handles filters', async () => {
      vi.spyOn(transfersApi, 'fetchTransfers').mockResolvedValue({
        count: 1,
        next: null,
        previous: null,
        results: SAMPLE_TRANSFERS,
      })

      render(
        <MemoryRouter>
          <WarehouseTransfersPage />
        </MemoryRouter>
      )

      await waitFor(() => {
        expect(screen.getByText('TRF/26-27/000001')).toBeInTheDocument()
      })
      expect(screen.getByText("Chheda's Soya Snax")).toBeInTheDocument()
      expect(screen.getByText('+ New Transfer')).toBeInTheDocument()
    })

    it('hides "+ New Transfer" button for staff users', async () => {
      useAuth.mockReturnValue({
        user: { id: 2, username: 'staff1', role: 'staff' },
        token: 'tok',
        loading: false,
      })
      vi.spyOn(transfersApi, 'fetchTransfers').mockResolvedValue({
        count: 0,
        results: [],
      })

      render(
        <MemoryRouter>
          <WarehouseTransfersPage />
        </MemoryRouter>
      )

      await waitFor(() => {
        expect(screen.queryByText('+ New Transfer')).not.toBeInTheDocument()
      })
    })
  })

  describe('NewWarehouseTransferPage', () => {
    it('warns when source and destination warehouses are the same', async () => {
      const user = userEvent.setup()
      render(
        <MemoryRouter>
          <NewWarehouseTransferPage />
        </MemoryRouter>
      )

      await waitFor(() => {
        expect(screen.getByLabelText(/Source Warehouse/i)).toBeInTheDocument()
      })

      // Set destination to same as source (Main Hub = 1)
      const destSelect = screen.getByLabelText(/Destination Warehouse/i)
      await user.selectOptions(destSelect, '1')

      expect(
        screen.getByText(/Source and destination warehouses must be different/i)
      ).toBeInTheDocument()
    })

    it('handles piece vs master box conversion and live calculations', async () => {
      const user = userEvent.setup()
      vi.spyOn(purchasesApi, 'searchPurchaseProducts').mockResolvedValue({
        data: { results: [SAMPLE_PRODUCT_192] },
      })
      const createSpy = vi.spyOn(transfersApi, 'createTransfer').mockResolvedValue({
        id: 10,
        transfer_number: 'TRF/26-27/000001',
      })

      render(
        <MemoryRouter initialEntries={['/inventory/transfers/new']}>
          <Routes>
            <Route path="/inventory/transfers/new" element={<NewWarehouseTransferPage />} />
            <Route path="/inventory/transfers/:id" element={<div>Transfer Detail</div>} />
          </Routes>
        </MemoryRouter>
      )

      // Search and pick product
      const searchInput = screen.getByLabelText(/Product to Transfer/i)
      await user.type(searchInput, 'Chheda')

      await waitFor(() => {
        expect(screen.getByText("Chheda's Soya Snax")).toBeInTheDocument()
      })
      await user.click(screen.getByText("Chheda's Soya Snax"))

      // Enter quantity 2 and choose Master Box
      const qtyInput = screen.getByLabelText(/^Quantity \*/i)
      await user.type(qtyInput, '2')

      const unitSelect = screen.getByLabelText(/^Unit \*/i)
      await user.selectOptions(unitSelect, 'master box')

      // Check authoritative base quantity = 2 * 192 = 384 pcs
      const baseQtyInput = screen.getByLabelText(/Total Base Quantity/i)
      expect(baseQtyInput).toHaveValue('384 pcs')

      // Click Execute Transfer
      const submitBtn = screen.getByRole('button', { name: /Execute Transfer/i })
      expect(submitBtn).toBeEnabled()
      await user.click(submitBtn)

      await waitFor(() => {
        expect(createSpy).toHaveBeenCalledWith(
          expect.objectContaining({
            product: 181,
            source_warehouse: 1,
            destination_warehouse: 2,
            quantity: '2',
            unit: 'master box',
            conversion_factor: '192',
          }),
          expect.objectContaining({
            idempotencyKey: expect.stringMatching(/^trf-/),
          })
        )
      })
    })

    it('disables submit if quantity exceeds source available stock', async () => {
      const user = userEvent.setup()
      vi.spyOn(purchasesApi, 'searchPurchaseProducts').mockResolvedValue({
        data: { results: [SAMPLE_PRODUCT_PIECE] },
      })
      vi.spyOn(inventoryApi, 'fetchProductInventory').mockResolvedValue([
        {
          id: 10,
          product: 182,
          warehouse: 1,
          quantity_on_hand: '10.000',
          average_cost: '7.50',
        },
      ])

      render(
        <MemoryRouter>
          <NewWarehouseTransferPage />
        </MemoryRouter>
      )

      const searchInput = screen.getByLabelText(/Product to Transfer/i)
      await user.type(searchInput, 'Parle')

      await waitFor(() => {
        expect(screen.getByText('Parle-G 100g')).toBeInTheDocument()
      })
      await user.click(screen.getByText('Parle-G 100g'))

      const qtyInput = screen.getByLabelText(/^Quantity \*/i)
      await user.type(qtyInput, '15')

      await waitFor(() => {
        expect(screen.getByText(/Requested quantity \(15 pcs\) exceeds source available stock \(10 pcs\)/i)).toBeInTheDocument()
      })
      expect(screen.getByRole('button', { name: /Execute Transfer/i })).toBeDisabled()
    })
  })

  describe('WarehouseTransferDetailPage', () => {
    it('renders transfer details, route, and accounting movements', async () => {
      vi.spyOn(transfersApi, 'fetchTransfer').mockResolvedValue(SAMPLE_TRANSFERS[0])

      render(
        <MemoryRouter initialEntries={['/inventory/transfers/10']}>
          <Routes>
            <Route path="/inventory/transfers/:id" element={<WarehouseTransferDetailPage />} />
          </Routes>
        </MemoryRouter>
      )

      await waitFor(() => {
        expect(screen.getByText('TRF/26-27/000001')).toBeInTheDocument()
      })

      expect(screen.getByText('Main Hub (HUB)')).toBeInTheDocument()
      expect(screen.getByText('Branch Store (BRANCH)')).toBeInTheDocument()
      expect(screen.getByText('384 pcs')).toBeInTheDocument()
      expect(screen.getByText('Append-Only Record:')).toBeInTheDocument()
      expect(screen.getByText(/WAREHOUSE_TRANSFER_OUT/i)).toBeInTheDocument()
      expect(screen.getByText(/WAREHOUSE_TRANSFER_IN/i)).toBeInTheDocument()
    })
  })
})
