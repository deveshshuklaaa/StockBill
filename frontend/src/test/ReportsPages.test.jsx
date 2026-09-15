// Regression tests for the reports + dashboard UI.
//
// Asserts: pages load and render backend values verbatim (no client-side
// financial recalculation), filters are sent as query parameters, empty
// and error states render, permission-gated pages surface 403 messages,
// and the dashboard cards link into the corresponding reports.

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import SalesReportPage from '../pages/reports/SalesReportPage'
import PurchaseReportPage from '../pages/reports/PurchaseReportPage'
import InventoryReportPage from '../pages/reports/InventoryReportPage'
import StockMovementReportPage from '../pages/reports/StockMovementReportPage'
import ProductSalesReportPage from '../pages/reports/ProductSalesReportPage'
import CustomerSalesReportPage from '../pages/reports/CustomerSalesReportPage'
import TaxReportPage from '../pages/reports/TaxReportPage'
import ProfitReportPage from '../pages/reports/ProfitReportPage'
import TopProductsReportPage from '../pages/reports/TopProductsReportPage'
import DashboardPage from '../pages/DashboardPage'
import * as reportsApi from '../api/reports'
import * as customersApi from '../api/customers'
import * as suppliersApi from '../api/suppliers'
import * as warehousesApi from '../api/warehouses'
import * as client from '../api/client'

const useAuth = vi.hoisted(() => vi.fn(() => ({ user: { id: 1, username: 'tester', role: 'admin' }, token: 'tok', loading: false })))
vi.mock('../context/AuthContext', () => ({ useAuth }))

const SALES = {
  from: '2026-09-01', to: '2026-09-30',
  invoice_count: 4,
  cancelled_invoice_count: 1,
  cancelled_invoice_value: '35.40',
  gross_sales: '140.00',
  discounts: '0.00',
  taxable_sales: '140.00',
  gst: '25.20',
  net_sales: '165.20',
  cogs: '76.00',
  gross_profit: '89.20',
}

const PURCHASES = {
  from: '2026-09-01', to: '2026-09-30',
  purchase_count: 3,
  cancelled_purchase_count: 1,
  cancelled_purchase_value: '70.80',
  taxable_purchases: '1000.00',
  gst: '180.00',
  total_purchase_value: '1180.00',
  by_supplier: [
    { supplier_id: 1, supplier_name: 'Alpha Traders', invoice_count: 2, taxable_total: '600.00', gst_total: '108.00', purchase_total: '708.00' },
    { supplier_id: 2, supplier_name: 'Beta Distributors', invoice_count: 1, taxable_total: '400.00', gst_total: '72.00', purchase_total: '472.00' },
  ],
}

const INVENTORY = {
  product_count: 2,
  quantity_on_hand: '138',
  total_value: '924.00',
  by_warehouse: [
    { warehouse_id: 1, warehouse_name: 'Main Warehouse', warehouse_code: 'MAIN', product_count: 2, quantity: '138', value: '924.00' },
  ],
}

const MOVEMENT = {
  movement_count: 7,
  inflow: '160',
  outflow: '-12',
  net_quantity: '148',
  by_movement_type: [
    { movement_type: 'PURCHASE', movement_count: 2, net_quantity: '160' },
    { movement_type: 'SALE', movement_count: 2, net_quantity: '-12' },
  ],
}

const PRODUCT_SALES = {
  from: '2026-09-01', to: '2026-09-30',
  products: [
    { product_id: 1, product_name: 'Report Product A', variant_snapshot: 'Report Product A', base_unit: 'piece', quantity_sold: '10', gross_sales: '100.00', discounts: '0.00', taxable_sales: '100.00', gst: '18.00', sales_value: '118.00', cogs: '60.00', gross_profit: '58.00', margin_percent: '49.2' },
  ],
  total_revenue: '166.00',
  total_cogs: '76.00',
  total_gross_profit: '90.00',
}

const CUSTOMERS = {
  from: '2026-09-01', to: '2026-09-30',
  invoice_count: 3,
  total_sales: '165.20',
  payment_count: 1,
  payment_amount: '47.20',
  by_customer: [
    { customer_id: 1, customer_name: 'J K Traders', is_walk_in: false, invoice_count: 1, sales_value: '118.00', outstanding_balance: '118.00' },
    { customer_id: null, customer_name: 'Walk-in customer', is_walk_in: true, invoice_count: 1, sales_value: '47.20', outstanding_balance: null },
  ],
}

const TAX = {
  from: '2026-09-01', to: '2026-09-30',
  output_tax: { taxable_sales: '140.00', cgst: '12.60', sgst: '12.60', igst: '0.00', total: '25.20' },
  input_tax: { taxable_purchases: '1000.00', cgst: '54.00', sgst: '54.00', igst: '72.00', total: '180.00' },
  net_tax: '-154.80',
}

const PROFIT = {
  from: '2026-09-01', to: '2026-09-30',
  revenue: '165.20',
  cogs: '76.00',
  gross_profit: '89.20',
  gross_margin_percent: '54.0',
  by_product: [
    { product_id: 1, product_name: 'Report Product A', revenue: '118.00', cogs: '60.00', gross_profit: '58.00' },
  ],
}

const TOP = {
  from: '2026-09-01', to: '2026-09-30',
  sort_by: 'quantity',
  products: [
    { product_id: 1, product_name: 'Report Product A', variant_snapshot: 'Report Product A', rank: 1, total_quantity: '10', total_revenue: '118.00', total_cogs: '60.00', total_profit: '58.00' },
  ],
}

const DASHBOARD = {
  from: '2026-09-01', to: '2026-09-30',
  today: { invoice_count: 2, net_sales: '165.20', purchase_count: 1, purchase_value: '708.00' },
  inventory: { product_count: 2, total_value: '924.00' },
  customer_outstanding_total: '118.00',
  active_customers: 2,
  active_suppliers: 3,
  period: { revenue: '165.20', cogs: '76.00', gross_profit: '89.20' },
  low_stock: [{ id: 1, name: 'Report Product A', current_stock: '2', low_stock_threshold: '10' }],
  recent_sales: [{ id: 11, invoice_number: 'INV-1', invoice_date: '2026-09-13', total_amount: '118.00', customer_name_snapshot: 'J K Traders' }],
  recent_purchases: [{ id: 7, purchase_number: 'PI/26-27/000004', invoice_date: '2026-09-10', total_amount: '708.00', supplier_name_snapshot: 'Alpha Traders' }],
  top_products: [{ product_id: 1, product_name: 'Report Product A', total_quantity: '10', total_revenue: '118.00' }],
}

const customersList = { count: 1, next: null, previous: null, results: [{ id: 1, name: 'J K Traders' }] }
const suppliersList = { count: 1, next: null, previous: null, results: [{ id: 1, name: 'Alpha Traders' }] }
const warehousesList = [{ id: 1, name: 'Main Warehouse', code: 'MAIN' }]

function mount(ui, { route = '/' } = {}) {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <Routes>
        <Route path="/" element={ui} />
        <Route path="/invoices/:id" element={<div>invoice page</div>} />
        <Route path="/purchases/:id" element={<div>purchase page</div>} />
      </Routes>
    </MemoryRouter>
  )
}

beforeEach(() => {
  vi.restoreAllMocks()
  useAuth.mockImplementation(() => ({ user: { id: 1, username: 'tester', role: 'admin' }, token: 'tok', loading: false }))
})

describe('SalesReportPage', () => {
  it('renders backend totals verbatim without recalculation', async () => {
    vi.spyOn(reportsApi, 'fetchSalesReport').mockResolvedValue(SALES)
    const customersSpy = vi.spyOn(customersApi, 'fetchCustomers').mockResolvedValue(customersList)

    mount(<SalesReportPage />)

    await screen.findByText('₹165.20')
    expect(screen.getByText('₹25.20')).toBeInTheDocument()
    expect(screen.getByText('₹76.00')).toBeInTheDocument()
    expect(screen.getByText('₹89.20')).toBeInTheDocument()
    expect(screen.getByText('₹35.40')).toBeInTheDocument()
    expect(customersSpy).toHaveBeenCalledWith({ page: 1 })
  })

  it('sends date, customer, and payment filters to the backend', async () => {
    const user = userEvent.setup()
    let captured = null
    vi.spyOn(reportsApi, 'fetchSalesReport').mockImplementation(async (params = {}) => {
      captured = params
      return SALES
    })
    vi.spyOn(customersApi, 'fetchCustomers').mockResolvedValue(customersList)

    mount(<SalesReportPage />)
    await screen.findByText('₹165.20')

    await user.selectOptions(screen.getByLabelText('Filter by customer'), '1')
    await user.selectOptions(screen.getByLabelText('Filter by payment type'), 'cash')
    await user.click(screen.getByRole('button', { name: 'Apply' }))

    await waitFor(() => {
      expect(captured.customer).toBe('1')
      expect(captured.paymentType).toBe('cash')
    })
  })

  it('shows the error state on failure', async () => {
    vi.spyOn(reportsApi, 'fetchSalesReport').mockRejectedValue({
      response: { status: 500, data: {} },
    })
    vi.spyOn(client, 'apiErrorMessage').mockImplementation(() => 'Server error while loading sales report.')

    mount(<SalesReportPage />)
    await screen.findByText('Server error while loading sales report.')
  })
})

describe('PurchaseReportPage', () => {
  it('renders totals and supplier breakdown', async () => {
    vi.spyOn(reportsApi, 'fetchPurchaseReport').mockResolvedValue(PURCHASES)
    const suppliersSpy = vi.spyOn(suppliersApi, 'fetchSuppliers').mockResolvedValue(suppliersList)

    mount(<PurchaseReportPage />)

    await screen.findByText('₹1,180.00')
    expect(screen.getByText('₹1,000.00')).toBeInTheDocument()
    expect(screen.getByText('₹180.00')).toBeInTheDocument()
    expect(screen.getByText('₹70.80')).toBeInTheDocument()
    // Alpha Traders appears in the dropdown and the breakdown table.
    expect(screen.getAllByText('Alpha Traders').length).toBeGreaterThan(0)
    expect(screen.getByText('Beta Distributors')).toBeInTheDocument()
    expect(suppliersSpy).toHaveBeenCalledWith({ page: 1 })
  })

  it('sends the supplier filter', async () => {
    const user = userEvent.setup()
    let captured = null
    vi.spyOn(reportsApi, 'fetchPurchaseReport').mockImplementation(async (params = {}) => {
      captured = params
      return PURCHASES
    })
    vi.spyOn(suppliersApi, 'fetchSuppliers').mockResolvedValue(suppliersList)

    mount(<PurchaseReportPage />)
    await screen.findByText('₹1,180.00')

    await user.selectOptions(screen.getByLabelText('Filter by supplier'), '1')
    await user.click(screen.getByRole('button', { name: 'Apply' }))

    await waitFor(() => { expect(captured.supplier).toBe('1') })
  })
})

describe('InventoryReportPage', () => {
  it('renders the authoritative WAC valuation', async () => {
    vi.spyOn(reportsApi, 'fetchInventoryReport').mockResolvedValue(INVENTORY)
    vi.spyOn(warehousesApi, 'fetchWarehouses').mockResolvedValue(warehousesList)

    mount(<InventoryReportPage />)

    // ₹924.00 appears in the total metric and the warehouse breakdown.
    await screen.findAllByText('₹924.00')
    expect(screen.getAllByText('138').length).toBeGreaterThan(0)
    // Main Warehouse appears as a dropdown option and a breakdown row.
    expect(screen.getAllByText('Main Warehouse').length).toBeGreaterThan(1)
  })

  it('sends warehouse and status filters', async () => {
    const user = userEvent.setup()
    let captured = null
    vi.spyOn(reportsApi, 'fetchInventoryReport').mockImplementation(async (params = {}) => {
      captured = params
      return INVENTORY
    })
    vi.spyOn(warehousesApi, 'fetchWarehouses').mockResolvedValue(warehousesList)

    mount(<InventoryReportPage />)
    await screen.findAllByText('₹924.00')

    await user.selectOptions(screen.getByLabelText('Filter by warehouse'), '1')
    await user.selectOptions(screen.getByLabelText('Filter by status'), 'true')
    await waitFor(() => {
      expect(captured.warehouse).toBe('1')
      expect(captured.isActive).toBe('true')
    })
  })
})

describe('StockMovementReportPage', () => {
  it('renders ledger aggregates and movement breakdown', async () => {
    vi.spyOn(reportsApi, 'fetchStockMovementReport').mockResolvedValue(MOVEMENT)
    vi.spyOn(warehousesApi, 'fetchWarehouses').mockResolvedValue(warehousesList)

    mount(<StockMovementReportPage />)

    await screen.findByText('148')
    expect(screen.getByText('+160')).toBeInTheDocument()
    // 'Purchase' appears as a movement label and dropdown option.
    expect(screen.getAllByText('Purchase').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Sale').length).toBeGreaterThan(0)
  })
})

describe('ProductSalesReportPage', () => {
  it('renders historical COGS and margin verbatim', async () => {
    vi.spyOn(reportsApi, 'fetchProductSalesReport').mockResolvedValue(PRODUCT_SALES)

    mount(<ProductSalesReportPage />)

    await screen.findAllByText('Report Product A')
    expect(screen.getByText('₹58.00')).toBeInTheDocument()
    expect(screen.getByText('49.2%')).toBeInTheDocument()
    // Totals come from the backend response, never recomputed.
    expect(screen.getByText('₹90.00')).toBeInTheDocument()
  })

  it('shows the empty state', async () => {
    vi.spyOn(reportsApi, 'fetchProductSalesReport').mockResolvedValue({
      ...PRODUCT_SALES, products: [], total_revenue: '0.00', total_cogs: '0.00', total_gross_profit: '0.00',
    })
    mount(<ProductSalesReportPage />)
    await screen.findByText('No posted sales in this period.')
  })
})

describe('CustomerSalesReportPage', () => {
  it('renders customer rows with outstanding and walk-in identity', async () => {
    vi.spyOn(reportsApi, 'fetchCustomerSalesReport').mockResolvedValue(CUSTOMERS)

    mount(<CustomerSalesReportPage />)

    await screen.findByText('J K Traders')
    expect(screen.getByText('Walk-in customer')).toBeInTheDocument()
    expect(screen.getByText('Cash sale without account')).toBeInTheDocument()
    const view = screen.getByRole('link', { name: 'View' })
    expect(view.getAttribute('href')).toBe('/customers/1')
    // Outstanding (₹118.00) also matches the J K Traders sales value.
    expect(screen.getAllByText('₹118.00').length).toBeGreaterThan(0)
  })

  it('surfaces 403 with a permission message', async () => {
    vi.spyOn(reportsApi, 'fetchCustomerSalesReport').mockRejectedValue({
      response: { status: 403, data: { detail: 'Only admin users can access this endpoint.' } },
    })
    vi.spyOn(client, 'apiForbiddenMessage').mockImplementation(
      (err, forbiddenAction) => `You do not have permission to ${forbiddenAction}.`
    )

    mount(<CustomerSalesReportPage />)
    await screen.findByText('You do not have permission to view the customer sales report.')
  })
})

describe('TaxReportPage', () => {
  it('distinguishes output from input tax with the snapshot split', async () => {
    vi.spyOn(reportsApi, 'fetchTaxReport').mockResolvedValue(TAX)

    mount(<TaxReportPage />)

    // ₹25.20 is the output-tax card value; ₹12.60 appears as CGST/SGST.
    await screen.findAllByText('₹25.20')
    // ₹180.00 appears as the input-tax card and its table row.
    expect(screen.getAllByText('₹180.00').length).toBeGreaterThan(0)
    expect(screen.getByText('₹-154.80')).toBeInTheDocument()
    expect(screen.getByText('OUTPUT — sales')).toBeInTheDocument()
    expect(screen.getByText('INPUT — purchases')).toBeInTheDocument()
    expect(screen.getAllByText('₹12.60').length).toBeGreaterThan(0)
    expect(screen.getByText('₹72.00')).toBeInTheDocument()
  })
})

describe('ProfitReportPage', () => {
  it('renders revenue, historical COGS, and margin verbatim', async () => {
    vi.spyOn(reportsApi, 'fetchProfitReport').mockResolvedValue(PROFIT)

    mount(<ProfitReportPage />)

    // Gross profit ₹89.20 appears in the metric card and by-product table
    // sums to the same figure; assert presence at least once.
    await screen.findAllByText('₹89.20')
    expect(screen.getByText('₹165.20')).toBeInTheDocument()
    expect(screen.getByText('₹76.00')).toBeInTheDocument()
    expect(screen.getByText('54.0%')).toBeInTheDocument()
    // No client-side recompute: the displayed revenue is exactly the payload value.
    expect(screen.queryByText('₹166.00')).not.toBeInTheDocument()
  })
})

describe('TopProductsReportPage', () => {
  it('renders ranked rows and sends the sort filter', async () => {
    const user = userEvent.setup()
    let captured = null
    vi.spyOn(reportsApi, 'fetchTopProductsReport').mockImplementation(async (params = {}) => {
      captured = params
      return TOP
    })

    mount(<TopProductsReportPage />)
    await screen.findByText('#1')

    await user.selectOptions(screen.getByLabelText('Rank products by'), 'profit')
    await user.click(screen.getByRole('button', { name: 'Apply' }))
    await waitFor(() => { expect(captured.sortBy).toBe('profit') })
  })
})

describe('DashboardPage', () => {
  it('renders every metric card from the dashboard payload', async () => {
    vi.spyOn(reportsApi, 'fetchDashboard').mockResolvedValue(DASHBOARD)

    mount(<DashboardPage />)

    await screen.findByText('₹165.20')
    // ₹708.00 appears in the today's-purchases card and recent purchases.
    expect(screen.getAllByText('₹708.00').length).toBeGreaterThan(0)
    expect(screen.getAllByText('₹924.00').length).toBeGreaterThan(0)
    // ₹118.00 is both the outstanding card and the recent sale total.
    expect(screen.getAllByText('₹118.00').length).toBeGreaterThan(1)
    expect(screen.getByText('2 active customer(s)')).toBeInTheDocument()
    expect(screen.getByText('₹89.20')).toBeInTheDocument()
  })

  it('links cards into their underlying reports', async () => {
    vi.spyOn(reportsApi, 'fetchDashboard').mockResolvedValue(DASHBOARD)

    mount(<DashboardPage />)
    await screen.findByText("Today's sales")

    const salesCard = screen.getByText("Today's sales").closest('a')
    expect(salesCard.getAttribute('href')).toMatch(/^\/reports\/sales\?from=/)
    const profitCard = screen.getByText('Gross profit (period)').closest('a')
    expect(profitCard.getAttribute('href')).toMatch(/^\/reports\/profit\?from=/)
    const inventoryCard = screen.getByText('Inventory value').closest('a')
    expect(inventoryCard.getAttribute('href')).toBe('/reports/inventory')
  })

  it('renders recent activity and stock alerts with links', async () => {
    vi.spyOn(reportsApi, 'fetchDashboard').mockResolvedValue(DASHBOARD)

    mount(<DashboardPage />)
    await screen.findByText('Recent sales')

    const invoiceLink = screen.getByRole('link', { name: 'INV-1' })
    expect(invoiceLink.getAttribute('href')).toBe('/invoices/11')
    const purchaseLink = screen.getByRole('link', { name: 'PI/26-27/000004' })
    expect(purchaseLink.getAttribute('href')).toBe('/purchases/7')
    expect(screen.getAllByText('Report Product A').length).toBeGreaterThan(0)
  })

  it('shows the error state when the dashboard fails', async () => {
    vi.spyOn(reportsApi, 'fetchDashboard').mockRejectedValue({
      response: { status: 403, data: { detail: 'Only admin users can access this endpoint.' } },
    })
    vi.spyOn(client, 'apiForbiddenMessage').mockImplementation(
      (err, forbiddenAction) => `You do not have permission to ${forbiddenAction}.`
    )

    mount(<DashboardPage />)
    await screen.findByText('You do not have permission to view the dashboard.')
  })
})
