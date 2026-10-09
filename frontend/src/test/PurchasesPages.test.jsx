import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import PurchasesPage from '../pages/PurchasesPage'
import NewPurchasePage from '../pages/NewPurchasePage'
import PurchaseDetailPage from '../pages/PurchaseDetailPage'
import * as purchasesApi from '../api/purchases'
import * as suppliersApi from '../api/suppliers'
import api from '../api/client'

const useAuth = vi.hoisted(() => vi.fn(() => ({ user: { id: 1, username: 'admin', role: 'admin' }, token: 'tok', loading: false })))
vi.mock('../context/AuthContext', () => ({ useAuth }))

const SAMPLE_SUPPLIER = {
  id: 10,
  name: 'Chheda Agro Food Park Pvt. Ltd.',
  gstin: '27ABECS9815P1ZI',
  state: 'Maharashtra',
  state_code: '27',
  is_active: true,
}

const SAMPLE_PRODUCT = {
  id: 181,
  name: "Chheda's Soya Snax",
  mrp: '10.00',
  current_stock: '100.000',
  base_unit: 'piece',
  tax_rate: '5.00',
  sku: 'CH-SOYA-192',
  attributes: {
    units_per_master_box: 192,
    net_weight: 0.038,
  },
}

const SAMPLE_DRAFT_PURCHASE = {
  id: 42,
  purchase_number: null,
  supplier: 10,
  supplier_name: 'Chheda Agro Food Park Pvt. Ltd.',
  supplier_name_snapshot: 'Chheda Agro Food Park Pvt. Ltd.',
  supplier_gstin_snapshot: '27ABECS9815P1ZI',
  supplier_state_snapshot: 'Maharashtra',
  supplier_state_code_snapshot: '27',
  warehouse: 1,
  warehouse_name: 'Main Warehouse',
  supplier_invoice_no: 'BILL-42-DRAFT',
  invoice_date: '2026-10-08',
  state: 'DRAFT',
  tax_mode: 'exclusive',
  notes: 'Draft order for stock receipt',
  taxable_total: '1280.00',
  total_amount: '1344.00',
  line_items: [
    {
      id: 101,
      product: 181,
      product_name: "Chheda's Soya Snax",
      product_name_snapshot: "Chheda's Soya Snax",
      sku_snapshot: 'CH-SOYA-192',
      hsn_sac_snapshot: '21069099',
      base_unit_snapshot: 'piece',
      quantity: '200.000',
      purchase_unit_name: 'piece',
      conversion_factor: '1.000',
      base_quantity: '200.000',
      rate: '6.40',
      discount_amount: '0.00',
      tax_rate: '5.00',
      cgst_rate: '2.50',
      cgst_amount: '16.00',
      sgst_rate: '2.50',
      sgst_amount: '16.00',
      igst_rate: '0.00',
      igst_amount: '0.00',
      taxable_value: '1280.00',
      line_total: '1344.00',
      unit_cost_snapshot: '6.40',
    },
  ],
}

const SAMPLE_POSTED_PURCHASE = {
  id: 43,
  purchase_number: 'PI/26-27/000001',
  supplier: 10,
  supplier_name: 'Chheda Agro Food Park Pvt. Ltd.',
  warehouse: 1,
  warehouse_name: 'Main Warehouse',
  supplier_invoice_no: 'BILL-43-POSTED',
  invoice_date: '2026-10-08',
  state: 'POSTED',
  tax_mode: 'exclusive',
  taxable_total: '1280.00',
  total_amount: '1344.00',
  line_items: [],
}

const SAMPLE_CANCELLED_PURCHASE = {
  id: 44,
  purchase_number: 'PI/26-27/000002',
  supplier: 10,
  supplier_name: 'Chheda Agro Food Park Pvt. Ltd.',
  warehouse: 1,
  warehouse_name: 'Main Warehouse',
  supplier_invoice_no: 'BILL-44-CANCELLED',
  invoice_date: '2026-10-08',
  state: 'CANCELLED',
  tax_mode: 'exclusive',
  taxable_total: '1280.00',
  total_amount: '1344.00',
  line_items: [],
}

describe('Purchases List and Draft Reopen / Edit Flow', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.spyOn(suppliersApi, 'fetchSuppliers').mockResolvedValue({
      results: [SAMPLE_SUPPLIER],
    })
    vi.spyOn(purchasesApi, 'fetchWarehouses').mockResolvedValue([
      { id: 1, name: 'Main Warehouse', code: 'MAIN' },
    ])
    vi.spyOn(purchasesApi, 'fetchNextPurchaseNumber').mockResolvedValue('PI/26-27/000005')
  })

  it('1. Draft purchase appears in purchase list with View/Edit and Delete actions', async () => {
    vi.spyOn(purchasesApi, 'fetchPurchases').mockResolvedValue({
      count: 3,
      results: [SAMPLE_DRAFT_PURCHASE, SAMPLE_POSTED_PURCHASE, SAMPLE_CANCELLED_PURCHASE],
    })

    render(
      <MemoryRouter>
        <PurchasesPage />
      </MemoryRouter>
    )

    await waitFor(() => expect(screen.getByText('Purchases')).toBeInTheDocument())
    expect(screen.getByText('Draft #42')).toBeInTheDocument()
    expect(screen.getByText('PI/26-27/000001')).toBeInTheDocument()
    expect(screen.getByText('PI/26-27/000002')).toBeInTheDocument()

    // Draft row has View / Edit action
    const viewEditLink = screen.getByRole('link', { name: /View \/ Edit draft purchase/i })
    expect(viewEditLink).toBeInTheDocument()
    expect(viewEditLink.getAttribute('href')).toBe('/purchases/new?edit=42')

    // Posted and Cancelled have View only, not Edit
    const viewLinks = screen.getAllByRole('link', { name: /View purchase/i })
    expect(viewLinks.length).toBe(2)
    expect(screen.queryByRole('link', { name: /View \/ Edit draft purchase 43/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /View \/ Edit draft purchase 44/i })).not.toBeInTheDocument()
  })

  it('2. Reopening a draft loads all previously entered information into the editor', async () => {
    vi.spyOn(purchasesApi, 'fetchPurchase').mockResolvedValue(SAMPLE_DRAFT_PURCHASE)
    vi.spyOn(api, 'get').mockImplementation((url) => {
      if (url === '/suppliers/10/') return Promise.resolve({ data: SAMPLE_SUPPLIER })
      if (url === '/products/181/') return Promise.resolve({ data: SAMPLE_PRODUCT })
      if (url === '/warehouses/') return Promise.resolve({ data: [{ id: 1, name: 'Main Warehouse' }] })
      return Promise.resolve({ data: {} })
    })

    render(
      <MemoryRouter initialEntries={['/purchases/new?edit=42']}>
        <Routes>
          <Route path="/purchases/new" element={<NewPurchasePage />} />
        </Routes>
      </MemoryRouter>
    )

    await waitFor(() => expect(screen.getByText('Edit draft purchase')).toBeInTheDocument())
    expect(screen.getByText(/Editing draft purchase/)).toBeInTheDocument()

    // Supplier is pre-selected
    expect(screen.getAllByText("Chheda Agro Food Park Pvt. Ltd.").length).toBeGreaterThanOrEqual(1)

    // Bill details are populated
    expect(screen.getByDisplayValue('BILL-42-DRAFT')).toBeInTheDocument()
    expect(screen.getByDisplayValue('2026-10-08')).toBeInTheDocument()
    expect(screen.getByDisplayValue('Draft order for stock receipt')).toBeInTheDocument()

    // Preloaded line item
    expect(screen.getByText("Chheda's Soya Snax")).toBeInTheDocument()
    expect(screen.getByDisplayValue('200')).toBeInTheDocument()
    expect(screen.getByDisplayValue('6.4')).toBeInTheDocument()
    expect(screen.getByDisplayValue('₹10.00')).toBeInTheDocument() // MRP
  })

  it('3. Draft can be modified and saved via updatePurchase API', async () => {
    vi.spyOn(purchasesApi, 'fetchPurchase').mockResolvedValue(SAMPLE_DRAFT_PURCHASE)
    const updateSpy = vi.spyOn(purchasesApi, 'updatePurchase').mockResolvedValue({
      ...SAMPLE_DRAFT_PURCHASE,
      supplier_invoice_no: 'BILL-42-UPDATED',
    })

    vi.spyOn(api, 'get').mockImplementation((url) => {
      if (url === '/suppliers/10/') return Promise.resolve({ data: SAMPLE_SUPPLIER })
      if (url === '/products/181/') return Promise.resolve({ data: SAMPLE_PRODUCT })
      if (url === '/warehouses/') return Promise.resolve({ data: [{ id: 1, name: 'Main Warehouse' }] })
      return Promise.resolve({ data: {} })
    })

    render(
      <MemoryRouter initialEntries={['/purchases/new?edit=42']}>
        <Routes>
          <Route path="/purchases/new" element={<NewPurchasePage />} />
          <Route path="/purchases/42" element={<div>Purchase Detail 42</div>} />
        </Routes>
      </MemoryRouter>
    )

    await waitFor(() => expect(screen.getByText('Edit draft purchase')).toBeInTheDocument())

    // Change supplier bill no
    const billNoInput = screen.getByLabelText(/Supplier bill no/i)
    await userEvent.clear(billNoInput)
    await userEvent.type(billNoInput, 'BILL-42-UPDATED')

    // Change line quantity to 250
    const qtyInput = screen.getByLabelText(/Quantity in pieces/i)
    await userEvent.clear(qtyInput)
    await userEvent.type(qtyInput, '250')

    // Click Save changes
    const saveBtn = screen.getByRole('button', { name: /Save changes/i })
    await userEvent.click(saveBtn)

    await waitFor(() => {
      expect(updateSpy).toHaveBeenCalledWith(
        '42',
        expect.objectContaining({
          supplier: 10,
          warehouse: 1,
          supplier_invoice_no: 'BILL-42-UPDATED',
          line_items: [
            expect.objectContaining({
              product: 181,
              quantity: 250,
              rate: 6.4,
            }),
          ],
        })
      )
    })
  })

  it('4. Draft can be posted directly from the reopened editor and receive stock', async () => {
    vi.spyOn(purchasesApi, 'fetchPurchase').mockResolvedValue(SAMPLE_DRAFT_PURCHASE)
    const updateSpy = vi.spyOn(purchasesApi, 'updatePurchase').mockResolvedValue(SAMPLE_DRAFT_PURCHASE)
    const postSpy = vi.spyOn(purchasesApi, 'postPurchase').mockResolvedValue({
      ...SAMPLE_DRAFT_PURCHASE,
      id: 42,
      state: 'POSTED',
      purchase_number: 'PI/26-27/000005',
    })

    vi.spyOn(api, 'get').mockImplementation((url) => {
      if (url === '/suppliers/10/') return Promise.resolve({ data: SAMPLE_SUPPLIER })
      if (url === '/products/181/') return Promise.resolve({ data: SAMPLE_PRODUCT })
      if (url === '/warehouses/') return Promise.resolve({ data: [{ id: 1, name: 'Main Warehouse' }] })
      return Promise.resolve({ data: {} })
    })

    render(
      <MemoryRouter initialEntries={['/purchases/new?edit=42']}>
        <Routes>
          <Route path="/purchases/new" element={<NewPurchasePage />} />
          <Route path="/purchases/42" element={<div>Purchase Detail 42 Posted</div>} />
        </Routes>
      </MemoryRouter>
    )

    await waitFor(() => expect(screen.getByText('Edit draft purchase')).toBeInTheDocument())

    const postBtn = screen.getByRole('button', { name: /Post & receive stock/i })
    await userEvent.click(postBtn)

    await waitFor(() => {
      expect(updateSpy).toHaveBeenCalled()
      expect(postSpy).toHaveBeenCalledWith('42')
    })
  })

  it('5. Detail page exposes Edit Draft and Delete Draft for draft purchases', async () => {
    vi.spyOn(purchasesApi, 'fetchPurchase').mockResolvedValue(SAMPLE_DRAFT_PURCHASE)

    render(
      <MemoryRouter initialEntries={['/purchases/42']}>
        <Routes>
          <Route path="/purchases/:id" element={<PurchaseDetailPage />} />
        </Routes>
      </MemoryRouter>
    )

    await waitFor(() => expect(screen.getByText('Draft #42')).toBeInTheDocument())

    const editDraftLink = screen.getByRole('link', { name: /Edit Draft/i })
    expect(editDraftLink).toBeInTheDocument()
    expect(editDraftLink.getAttribute('href')).toBe('/purchases/new?edit=42')

    const deleteBtn = screen.getByRole('button', { name: /Delete Draft/i })
    expect(deleteBtn).toBeInTheDocument()
  })

  it('6. Non-draft (POSTED) purchase rejects editing and does not show edit controls', async () => {
    vi.spyOn(purchasesApi, 'fetchPurchase').mockResolvedValue(SAMPLE_POSTED_PURCHASE)

    render(
      <MemoryRouter initialEntries={['/purchases/new?edit=43']}>
        <Routes>
          <Route path="/purchases/new" element={<NewPurchasePage />} />
        </Routes>
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByText(/Only draft purchases can be edited/i)).toBeInTheDocument()
    })
  })
})
