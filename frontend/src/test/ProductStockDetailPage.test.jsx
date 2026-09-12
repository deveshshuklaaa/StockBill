// Regression test for the identical-detail-page bug:
// /inventory/3 and /inventory/124 rendered the same product because the
// balances/ledger state was not bound to the route parameter.
//
// Covers the full path: route param -> API request -> component state ->
// rendered product identity, including client-side navigation between two
// products (React Router reuses the component; it must not keep stale state).

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, Link } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ProductStockDetailPage from '../pages/ProductStockDetailPage'
import * as inventoryApi from '../api/inventory'

// Product 3 fixture (what the API must return for ?product=3)
const BALANCES_3 = {
  count: 1,
  next: null,
  previous: null,
  results: [
    {
      id: 101,
      product: 3,
      product_name: "Chheda's Yellow banana Chips",
      product_sku: 'CHIPS-25G',
      product_mrp: '10.00',
      product_base_unit: 'piece',
      product_category_name: 'Chips',
      product_is_active: true,
      product_attributes: { net_weight: 0.025, units_per_master_box: 192 },
      warehouse: 1,
      warehouse_name: 'Main Warehouse',
      quantity_on_hand: '100.000',
      average_cost: '8.00',
      created_at: '2026-09-08T10:00:00Z',
      updated_at: '2026-09-08T10:00:00Z',
    },
  ],
}

// Product 124 fixture (what the API must return for ?product=124)
const BALANCES_124 = {
  count: 1,
  next: null,
  previous: null,
  results: [
    {
      id: 102,
      product: 124,
      product_name: "Chheda's 3 in 1 Chikki",
      product_sku: 'CHIKKI-3IN1',
      product_mrp: '5.00',
      product_base_unit: 'piece',
      product_category_name: 'Packaged Food',
      product_is_active: true,
      product_attributes: { net_weight: 0.018, units_per_master_box: 360 },
      warehouse: 1,
      warehouse_name: 'Main Warehouse',
      quantity_on_hand: '4915.000',
      average_cost: '7.79',
      created_at: '2026-09-08T10:00:00Z',
      updated_at: '2026-09-08T10:00:00Z',
    },
  ],
}

const LEDGER_3 = {
  count: 1,
  next: null,
  previous: null,
  results: [
    {
      id: 1,
      product: 3,
      product_name: "Chheda's Yellow banana Chips",
      warehouse_name: 'Main Warehouse',
      movement_type: 'PURCHASE',
      reference: 'PI/FY2627/000001',
      quantity_change: '100.000',
      unit_cost: '8.00',
      created_by_username: 'admin',
      created_at: '2026-09-08T10:00:00Z',
    },
  ],
}

const LEDGER_124 = {
  count: 1,
  next: null,
  previous: null,
  results: [
    {
      id: 7,
      product: 124,
      product_name: "Chheda's 3 in 1 Chikki",
      warehouse_name: 'Main Warehouse',
      movement_type: 'SALE',
      reference: 'INV/2026/0009',
      quantity_change: '-500.000',
      unit_cost: '7.79',
      created_by_username: 'admin',
      created_at: '2026-09-09T10:00:00Z',
    },
  ],
}

function balancesFor(productId) {
  if (String(productId) === '3') return BALANCES_3
  if (String(productId) === '124') return BALANCES_124
  return { count: 0, next: null, previous: null, results: [] }
}

function ledgerFor(productId) {
  if (String(productId) === '3') return LEDGER_3
  if (String(productId) === '124') return LEDGER_124
  return { count: 0, next: null, previous: null, results: [] }
}

let lastBalanceRequest = null
let lastLedgerRequest = null

beforeEach(() => {
  lastBalanceRequest = null
  lastLedgerRequest = null
  vi.restoreAllMocks()
})

function installApiMocks() {
  vi.spyOn(inventoryApi, 'fetchProductInventory').mockImplementation(async (productId) => {
    lastBalanceRequest = productId
    return balancesFor(productId).results
  })
  vi.spyOn(inventoryApi, 'fetchStockLedger').mockImplementation(async ({ product }) => {
    lastLedgerRequest = product
    return ledgerFor(product)
  })
}

function mountAt(initialUrl) {
  return render(
    <MemoryRouter initialEntries={[initialUrl]}>
      {/* Persistent nav links so the test can navigate between products
          without remounting the detail component (client-side routing). */}
      <nav>
        <Link to="/inventory/3">go 3</Link>
        <Link to="/inventory/124">go 124</Link>
      </nav>
      <Routes>
        <Route path="/inventory/:productId" element={<ProductStockDetailPage />} />
      </Routes>
    </MemoryRouter>
  )
}

describe('ProductStockDetailPage route binding', () => {
  it('renders product 3 from /inventory/3', async () => {
    installApiMocks()

    mountAt('/inventory/3')

    await waitFor(() => {
      expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
        "Chheda's Yellow banana Chips"
      )
    })

    expect(lastBalanceRequest).toBe('3')
    expect(lastLedgerRequest).toBe('3')
    expect(screen.getByText('CHIPS-25G')).toBeInTheDocument()
    expect(screen.getByText('Chips')).toBeInTheDocument()
    expect(screen.getByText('₹10.00')).toBeInTheDocument()
    expect(screen.getByText('PI/FY2627/000001')).toBeInTheDocument()
  })

  it('renders a different product from /inventory/124', async () => {
    installApiMocks()

    mountAt('/inventory/124')

    await waitFor(() => {
      expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
        "Chheda's 3 in 1 Chikki"
      )
    })

    expect(lastBalanceRequest).toBe('124')
    expect(lastLedgerRequest).toBe('124')
    // Must NOT show anything belonging to product 3
    expect(screen.queryByText("Chheda's Yellow banana Chips")).not.toBeInTheDocument()
    expect(screen.queryByText('CHIPS-25G')).not.toBeInTheDocument()
    expect(screen.queryByText('PI/FY2627/000001')).not.toBeInTheDocument()
  })

  it('updates the rendered product when navigating 3 -> 124 and back without a remount', async () => {
    installApiMocks()
    const user = userEvent.setup()

    mountAt('/inventory/3')

    // Product 3 renders first.
    await waitFor(() => {
      expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
        "Chheda's Yellow banana Chips"
      )
    })

    // Navigate to product 124: same component instance must re-render with
    // new data, never keep product 3's state.
    await user.click(screen.getByRole('link', { name: 'go 124' }))
    await waitFor(() => {
      expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
        "Chheda's 3 in 1 Chikki"
      )
    })
    expect(lastBalanceRequest).toBe('124')
    expect(lastLedgerRequest).toBe('124')
    expect(screen.queryByText("Chheda's Yellow banana Chips")).not.toBeInTheDocument()
    expect(screen.queryByText('CHIPS-25G')).not.toBeInTheDocument()
    expect(screen.queryByText('PI/FY2627/000001')).not.toBeInTheDocument()

    // Navigate back to product 3: also must re-render correctly.
    await user.click(screen.getByRole('link', { name: 'go 3' }))
    await waitFor(() => {
      expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(
        "Chheda's Yellow banana Chips"
      )
    })
    expect(lastBalanceRequest).toBe('3')
    expect(screen.queryByText("Chheda's 3 in 1 Chikki")).not.toBeInTheDocument()
    expect(screen.queryByText('CHIKKI-3IN1')).not.toBeInTheDocument()
  })

  it('shows an explicit not-found state when the product has no balances', async () => {
    vi.spyOn(inventoryApi, 'fetchProductInventory').mockResolvedValue([])
    vi.spyOn(inventoryApi, 'fetchStockLedger').mockImplementation(async ({ product }) =>
      ledgerFor(product)
    )

    mountAt('/inventory/999')

    await waitFor(() => {
      expect(screen.getByText('Product not found in inventory.')).toBeInTheDocument()
    })
    expect(screen.queryByRole('heading', { level: 1 })).not.toBeInTheDocument()
  })
})
