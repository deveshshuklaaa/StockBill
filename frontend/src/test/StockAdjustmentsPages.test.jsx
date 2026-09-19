import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as adjustmentsApi from '../api/adjustments'
import * as inventoryApi from '../api/inventory'
import * as purchasesApi from '../api/purchases'
import NewStockAdjustmentPage from '../pages/NewStockAdjustmentPage'
import StockAdjustmentDetailPage from '../pages/StockAdjustmentDetailPage'
import StockAdjustmentsPage from '../pages/StockAdjustmentsPage'

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
  current_stock: '2388.000',
  cost_price: '6.20',
  base_unit: 'piece',
  attributes: {
    units_per_master_box: 192,
    net_weight: 0.038,
  },
}

const SAMPLE_WAREHOUSES = [
  { id: 1, name: 'Main Warehouse', code: 'MAIN' },
]

describe('Stock Adjustments Frontend Suite', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useAuth.mockReturnValue({
      user: { id: 1, username: 'admin', role: 'admin' },
      token: 'tok',
      loading: false,
    })
    vi.spyOn(purchasesApi, 'fetchWarehouses').mockResolvedValue(SAMPLE_WAREHOUSES)
    vi.spyOn(adjustmentsApi, 'fetchNextAdjustmentNumber').mockResolvedValue('ADJ/26-27/000001')
    vi.spyOn(inventoryApi, 'fetchProductInventory').mockResolvedValue([
      {
        id: 10,
        product: 181,
        warehouse: 1,
        quantity_on_hand: '2388.000',
        average_cost: '6.20',
      },
    ])
  })

  describe('NewStockAdjustmentPage', () => {
    it('shows access restriction banner for staff users', async () => {
      useAuth.mockReturnValue({
        user: { id: 2, username: 'staff1', role: 'staff' },
        token: 'tok',
        loading: false,
      })

      render(
        <MemoryRouter>
          <NewStockAdjustmentPage />
        </MemoryRouter>
      )

      expect(
        screen.getByText(/Only administrators are authorized to post stock adjustments/i)
      ).toBeInTheDocument()
      expect(screen.queryByRole('button', { name: /Post Adjustment/i })).not.toBeInTheDocument()
    })

    it('renders form, searches product, calculates live preview for Master Box IN (+960 pcs @ 6.66)', async () => {
      vi.spyOn(purchasesApi, 'searchPurchaseProducts').mockResolvedValue({
        data: { results: [SAMPLE_PRODUCT_192] },
      })
      const createSpy = vi.spyOn(adjustmentsApi, 'createAdjustment').mockResolvedValue({
        id: 101,
        adjustment_number: 'ADJ/26-27/000001',
      })

      render(
        <MemoryRouter>
          <NewStockAdjustmentPage />
        </MemoryRouter>
      )

      await waitFor(() =>
        expect(screen.getByText('New Stock Adjustment')).toBeInTheDocument()
      )

      // Search product
      const productInput = screen.getByPlaceholderText(/Type product name or SKU/i)
      await userEvent.type(productInput, 'Soya')

      await waitFor(() =>
        expect(screen.getByText("Chheda's Soya Snax")).toBeInTheDocument()
      )
      await userEvent.click(screen.getByText("Chheda's Soya Snax"))

      // Unit should now offer Master Box (192 pcs)
      const unitSelect = screen.getByLabelText(/Quantity Unit/i)
      await userEvent.selectOptions(unitSelect, 'master box')

      // Quantity = 5 boxes
      const qtyInput = screen.getByLabelText(/Quantity in master boxes/i)
      await userEvent.clear(qtyInput)
      await userEvent.type(qtyInput, '5')

      // Cost per piece = 6.66
      const costInput = screen.getByLabelText(/Adjustment Cost \(per Piece\)/i)
      await userEvent.clear(costInput)
      await userEvent.type(costInput, '6.66')

      // Verify live preview calculations:
      // Base pieces = 5 * 192 = 960 pcs
      expect(screen.getByText(/= 960 pcs/i)).toBeInTheDocument()
      // Stock addition
      expect(screen.getByText('+960 pcs')).toBeInTheDocument()
      // New stock: 2,388 + 960 = 3,348 pcs
      expect(screen.getByText('3,348 pcs')).toBeInTheDocument()
      // Adjustment value = 960 * 6.66 = 6,393.60
      expect(screen.getByText('₹6,393.60')).toBeInTheDocument()

      // Submit form
      const submitBtn = screen.getByRole('button', { name: /Post Adjustment/i })
      await userEvent.click(submitBtn)

      await waitFor(() => {
        expect(createSpy).toHaveBeenCalledWith(
          expect.objectContaining({
            product: 181,
            warehouse: 1,
            adjustment_type: 'STOCK_ADJUSTMENT_IN',
            quantity: '5',
            unit: 'master box',
            conversion_factor: '192',
            cost_per_piece: '6.66',
            reason: 'Physical Count Increase',
          }),
          expect.objectContaining({
            idempotencyKey: expect.any(String),
          })
        )
      })
    })

    it('handles OUT adjustment with read-only WAC and blocks insufficient stock', async () => {
      vi.spyOn(purchasesApi, 'searchPurchaseProducts').mockResolvedValue({
        data: { results: [SAMPLE_PRODUCT_192] },
      })

      render(
        <MemoryRouter>
          <NewStockAdjustmentPage />
        </MemoryRouter>
      )

      await waitFor(() =>
        expect(screen.getByText('New Stock Adjustment')).toBeInTheDocument()
      )

      // Search & select product
      const productInput = screen.getByPlaceholderText(/Type product name or SKU/i)
      await userEvent.type(productInput, 'Soya')
      await waitFor(() =>
        expect(screen.getByText("Chheda's Soya Snax")).toBeInTheDocument()
      )
      await userEvent.click(screen.getByText("Chheda's Soya Snax"))

      // Switch to Decrease Stock (- OUT)
      const typeSelect = screen.getByLabelText(/Adjustment Type/i)
      await userEvent.selectOptions(typeSelect, 'STOCK_ADJUSTMENT_OUT')

      // Verify editable cost is replaced by read-only WAC
      expect(screen.queryByLabelText(/Adjustment Cost \(per Piece\)/i)).not.toBeInTheDocument()
      await waitFor(() => {
        expect(screen.getByText(/Current WAC: ₹6.20 \/ piece/i)).toBeInTheDocument()
      })

      // Enter excessive quantity = 5,000 pieces (available is 2,388)
      const qtyInput = screen.getByLabelText(/Quantity in pieces/i)
      await userEvent.clear(qtyInput)
      await userEvent.type(qtyInput, '5000')

      // Check insufficient stock warning is rendered
      expect(
        screen.getByText(/Insufficient stock for this adjustment. Available: 2388 pieces, Requested: 5000 pieces/i)
      ).toBeInTheDocument()

      // Submit button should be disabled
      const submitBtn = screen.getByRole('button', { name: /Post Adjustment/i })
      expect(submitBtn).toBeDisabled()
    })

    it('requires a note when Reason is Other', async () => {
      vi.spyOn(purchasesApi, 'searchPurchaseProducts').mockResolvedValue({
        data: { results: [SAMPLE_PRODUCT_192] },
      })

      render(
        <MemoryRouter>
          <NewStockAdjustmentPage />
        </MemoryRouter>
      )

      // Search & select product
      await userEvent.type(screen.getByPlaceholderText(/Type product name or SKU/i), 'Soya')
      await waitFor(() => screen.getByText("Chheda's Soya Snax"))
      await userEvent.click(screen.getByText("Chheda's Soya Snax"))

      // Enter quantity = 10
      await userEvent.type(screen.getByLabelText(/Quantity in pieces/i), '10')
      await userEvent.type(screen.getByLabelText(/Adjustment Cost \(per Piece\)/i), '6.00')

      // Select Reason = Other
      const reasonSelect = screen.getByLabelText(/Reason/i)
      await userEvent.selectOptions(reasonSelect, 'Other')

      // Submit without note
      await userEvent.click(screen.getByRole('button', { name: /Post Adjustment/i }))

      expect(
        screen.getByText("A note is required when reason is 'Other'.")
      ).toBeInTheDocument()
    })
  })

  describe('StockAdjustmentsPage', () => {
    it('renders adjustments list and shows "+ New Adjustment" button for Admin only', async () => {
      vi.spyOn(adjustmentsApi, 'fetchAdjustments').mockResolvedValue({
        count: 1,
        results: [
          {
            id: 1,
            adjustment_number: 'ADJ/26-27/000001',
            product_name: "Chheda's Soya Snax",
            product_sku: 'TEST-SKU-192',
            warehouse_name: 'Main Warehouse',
            adjustment_type: 'STOCK_ADJUSTMENT_IN',
            quantity: '5.000',
            unit: 'master box',
            base_quantity: '960.000',
            cost_per_base_unit_snapshot: '6.66',
            adjustment_value: '6393.60',
            reason: 'Physical Count Increase',
            effective_date: '2026-09-19',
            created_by_username: 'admin',
          },
        ],
      })

      render(
        <MemoryRouter>
          <StockAdjustmentsPage />
        </MemoryRouter>
      )

      await waitFor(() =>
        expect(screen.getByText('ADJ/26-27/000001')).toBeInTheDocument()
      )
      expect(screen.getByText('+ IN')).toBeInTheDocument()
      expect(screen.getByText("Chheda's Soya Snax")).toBeInTheDocument()
      expect(screen.getByText('+ New Adjustment')).toBeInTheDocument()
    })

    it('hides "+ New Adjustment" button for staff users', async () => {
      useAuth.mockReturnValue({
        user: { id: 2, username: 'staff1', role: 'staff' },
        token: 'tok',
        loading: false,
      })
      vi.spyOn(adjustmentsApi, 'fetchAdjustments').mockResolvedValue({
        count: 0,
        results: [],
      })

      render(
        <MemoryRouter>
          <StockAdjustmentsPage />
        </MemoryRouter>
      )

      await waitFor(() =>
        expect(screen.getByText('Stock Adjustments')).toBeInTheDocument()
      )
      expect(screen.queryByText('+ New Adjustment')).not.toBeInTheDocument()
    })
  })

  describe('StockAdjustmentDetailPage', () => {
    it('renders detailed view and immutability notice', async () => {
      vi.spyOn(adjustmentsApi, 'fetchAdjustment').mockResolvedValue({
        id: 1,
        adjustment_number: 'ADJ/26-27/000001',
        product_name: "Chheda's Soya Snax",
        product_sku: 'TEST-SKU-192',
        warehouse_name: 'Main Warehouse',
        warehouse_code: 'MAIN',
        adjustment_type: 'STOCK_ADJUSTMENT_IN',
        quantity: '5.000',
        unit: 'master box',
        conversion_factor: '192.000',
        base_quantity: '960.000',
        cost_per_base_unit_snapshot: '6.66',
        adjustment_value: '6393.60',
        reason: 'Physical Count Increase',
        note: 'Recount on Shelf A',
        effective_date: '2026-09-19',
        created_by_username: 'admin',
        created_at: '2026-09-19T10:00:00Z',
      })

      render(
        <MemoryRouter initialEntries={['/inventory/adjustments/1']}>
          <Routes>
            <Route
              path="/inventory/adjustments/:id"
              element={<StockAdjustmentDetailPage />}
            />
          </Routes>
        </MemoryRouter>
      )

      await waitFor(() =>
        expect(screen.getByText('ADJ/26-27/000001')).toBeInTheDocument()
      )
      expect(screen.getByText(/Append-Only Record:/i)).toBeInTheDocument()
      expect(screen.getByText('₹6,393.60')).toBeInTheDocument()
      expect(screen.getByText('+960 pcs')).toBeInTheDocument()
      expect(screen.getByText('Recount on Shelf A')).toBeInTheDocument()
    })
  })
})
