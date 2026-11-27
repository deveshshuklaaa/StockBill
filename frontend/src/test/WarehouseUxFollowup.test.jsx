// Follow-up UX fixes after PR #1: per-warehouse "available" hint, corrected
// supplier-settlement copy, no purchases into Damaged, ledger table scroll.

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import api from '../api/client'
import * as customersApi from '../api/customers'
import * as purchasesApi from '../api/purchases'
import * as reportsApi from '../api/reports'
import * as ledgerApi from '../api/supplierLedger'
import * as suppliersApi from '../api/suppliers'
import DashboardPage from '../pages/DashboardPage'
import NewInvoicePage from '../pages/NewInvoicePage'
import NewPurchasePage from '../pages/NewPurchasePage'
import SupplierLedgerPage from '../pages/SupplierLedgerPage'
import SuppliersPage from '../pages/SuppliersPage'
import { availableInWarehouse } from '../utils/warehouses'

const useAuth = vi.hoisted(() => vi.fn(() => ({ user: { id: 1, username: 'boss', role: 'admin' }, token: 'tok', loading: false })))
vi.mock('../context/AuthContext', () => ({ useAuth }))

const MAIN = { id: 1, code: 'MAIN', name: 'Main Warehouse', is_active: true, is_sellable: true }
const DAMAGED = { id: 2, code: 'DAMAGED', name: 'Damaged / Quarantine', is_active: true, is_sellable: false }
const VAN = { id: 3, code: 'VAN1', name: 'Van 1', is_active: true, is_sellable: true }

describe('availableInWarehouse', () => {
  const product = { current_stock: '200.000' }
  const balances = [
    { warehouse: 1, quantity_on_hand: '160.000' },
    { warehouse: 3, quantity_on_hand: '40.000' },
  ]

  it('uses the chosen warehouse balance', () => {
    expect(availableInWarehouse(product, balances, { warehouseId: 3, isMain: false })).toBe('40.000')
    expect(availableInWarehouse(product, balances, { warehouseId: 1, isMain: true })).toBe('160.000')
  })

  it('is zero in a warehouse with no balance row', () => {
    expect(availableInWarehouse(product, [{ warehouse: 1, quantity_on_hand: '5' }], { warehouseId: 3, isMain: false })).toBe(0)
  })

  it('falls back to current_stock when balances or Main are unknown, and for legacy stock in Main', () => {
    expect(availableInWarehouse(product, undefined, { warehouseId: 3, isMain: false })).toBe('200.000')
    expect(availableInWarehouse(product, balances, { warehouseId: null, isMain: true })).toBe('200.000')
    expect(availableInWarehouse(product, [], { warehouseId: 1, isMain: true })).toBe('200.000')
    expect(availableInWarehouse(product, [], { warehouseId: 3, isMain: false })).toBe(0)
  })
})

describe('NewInvoicePage available hint follows the source warehouse', () => {
  const PRODUCT = { id: 101, name: 'Banana Chips', mrp: '20.00', current_stock: '200.000', base_unit: 'piece', tax_rate: '5.00', attributes: {} }

  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(api, 'get').mockImplementation((url, config) => {
      if (url === '/warehouses/') return Promise.resolve({ data: { results: [MAIN, DAMAGED, VAN] } })
      if (url === '/customers/') return Promise.resolve({ data: { results: [] } })
      if (url === '/products/') return Promise.resolve({ data: { results: [PRODUCT] } })
      if (url === '/inventory-balances/' && config?.params?.product === 101) {
        return Promise.resolve({ data: { results: [
          { warehouse: 1, quantity_on_hand: '160.000' },
          { warehouse: 3, quantity_on_hand: '40.000' },
        ] } })
      }
      return Promise.resolve({ data: {} })
    })
    vi.spyOn(customersApi, 'fetchCustomerMRPPricing').mockResolvedValue({ pricing: [] })
  })

  it('shows Main, then Van 1, then Main again', async () => {
    const user = userEvent.setup()
    render(<MemoryRouter><NewInvoicePage /></MemoryRouter>)
    await screen.findByLabelText('Source warehouse')
    await user.type(screen.getByLabelText('Search products'), 'Banana')
    await user.click(await screen.findByText('Banana Chips'))
    expect(await screen.findByText('160 pcs available')).toBeInTheDocument()

    await user.selectOptions(screen.getByLabelText('Source warehouse'), 'Van 1 (VAN1)')
    expect(await screen.findByText('40 pcs available in Van 1')).toBeInTheDocument()

    await user.selectOptions(screen.getByLabelText('Source warehouse'), 'Main (default)')
    expect(await screen.findByText('160 pcs available')).toBeInTheDocument()
  })

  it('warns against the source warehouse stock, not the product total', async () => {
    const user = userEvent.setup()
    render(<MemoryRouter><NewInvoicePage /></MemoryRouter>)
    await user.selectOptions(await screen.findByLabelText('Source warehouse'), 'Van 1 (VAN1)')
    await user.type(screen.getByLabelText('Search products'), 'Banana')
    await user.click(await screen.findByText('Banana Chips'))
    const quantity = await screen.findByLabelText('Quantity for Banana Chips')
    await user.clear(quantity)
    await user.type(quantity, '45')
    await waitFor(() => expect(quantity).toHaveClass('input-warning'))
    await user.clear(quantity)
    await user.type(quantity, '40')
    await waitFor(() => expect(quantity).not.toHaveClass('input-warning'))
  })
})

describe('supplier settlement copy', () => {
  beforeEach(() => vi.restoreAllMocks())

  it('dashboard points to the supplier ledger instead of saying settlement is outside StockBill', async () => {
    vi.spyOn(reportsApi, 'fetchDashboard').mockResolvedValue({
      from: '2026-11-27', to: '2026-11-27',
      today: { invoice_count: 0, net_sales: '0', purchase_count: 0, purchase_value: '0' },
      inventory: { product_count: 0, total_value: '0' },
      held_stock: { product_count: 0, quantity: '0', total_value: '0' },
      customer_outstanding_total: '0', active_customers: 0, active_suppliers: 2,
      period: { revenue: '0', cogs: '0', gross_profit: '0' },
      low_stock: [], recent_sales: [], recent_purchases: [], top_products: [],
    })
    render(<MemoryRouter><DashboardPage /></MemoryRouter>)
    expect(await screen.findByText("Payments and balances in each supplier's ledger")).toBeInTheDocument()
    expect(screen.queryByText(/outside StockBill/)).not.toBeInTheDocument()
  })

  it('suppliers page subtitle no longer says settlement happens outside StockBill', async () => {
    vi.spyOn(suppliersApi, 'fetchSuppliers').mockResolvedValue({ count: 0, results: [] })
    render(<MemoryRouter><SuppliersPage /></MemoryRouter>)
    expect(await screen.findByText(/Open a supplier for its ledger/)).toBeInTheDocument()
    expect(screen.queryByText(/outside StockBill/)).not.toBeInTheDocument()
  })
})

describe('NewPurchasePage receiving warehouse', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(purchasesApi, 'fetchNextPurchaseNumber').mockResolvedValue('PI/26-27/000004')
    vi.spyOn(suppliersApi, 'fetchActiveSuppliers').mockResolvedValue([])
  })

  it('never offers Damaged and still auto-selects Main when it is the only receivable warehouse', async () => {
    vi.spyOn(purchasesApi, 'fetchWarehouses').mockResolvedValue([DAMAGED, MAIN])
    render(<MemoryRouter><NewPurchasePage /></MemoryRouter>)
    await screen.findByRole('option', { name: 'Main Warehouse' })
    expect(screen.queryByRole('option', { name: /Damaged/ })).not.toBeInTheDocument()
    const select = screen.getByRole('option', { name: 'Main Warehouse' }).closest('select')
    expect(select).toHaveValue('1')
  })

  it('lists every sellable warehouse', async () => {
    vi.spyOn(purchasesApi, 'fetchWarehouses').mockResolvedValue([DAMAGED, MAIN, VAN])
    render(<MemoryRouter><NewPurchasePage /></MemoryRouter>)
    await screen.findByRole('option', { name: 'Van 1' })
    expect(screen.getByRole('option', { name: 'Main Warehouse' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: /Damaged/ })).not.toBeInTheDocument()
  })
})

describe('SupplierLedgerPage table', () => {
  beforeEach(() => vi.restoreAllMocks())

  it('sits in its own horizontal scroll container', async () => {
    vi.spyOn(ledgerApi, 'fetchSupplierLedger').mockResolvedValue({
      supplier: { id: 7, name: 'Chheda Foods' }, from: null, to: null, opening_balance: '0.00',
      entries: [{ kind: 'payment', id: 1, date: '2026-11-27', type_label: 'Payment', reference: 'X', debit: '10.00', credit: null, balance: '-10.00', reversible_amount: '10.00' }],
      total_debit: '10.00', total_credit: '0.00', closing_balance: '-10.00',
    })
    render(
      <MemoryRouter initialEntries={['/suppliers/7/ledger']}>
        <Routes><Route path="/suppliers/:id/ledger" element={<SupplierLedgerPage />} /></Routes>
      </MemoryRouter>
    )
    const row = await screen.findByTestId('ledger-row')
    const scroller = screen.getByTestId('ledger-table-scroll')
    expect(scroller).toHaveClass('ledger-table-scroll')
    expect(scroller).toContainElement(row)
    expect(scroller).toContainElement(screen.getByRole('button', { name: 'Reverse' }))
  })
})
