import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import NewInvoicePage from '../pages/NewInvoicePage'
import NewPurchasePage from '../pages/NewPurchasePage'
import * as customersApi from '../api/customers'
import * as suppliersApi from '../api/suppliers'
import * as purchasesApi from '../api/purchases'
import api from '../api/client'

const useAuth = vi.hoisted(() =>
  vi.fn(() => ({ user: { id: 1, username: 'admin', role: 'admin' }, token: 'tok', loading: false }))
)
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

const SAMPLE_SUPPLIER = {
  id: 11,
  name: 'Global Foods Supplier',
  gstin: '27AABCG1234F1Z5',
  state: 'Maharashtra',
  state_code: '27',
  is_active: true,
}

const SAMPLE_WAREHOUSE = {
  id: 1,
  name: 'Main Warehouse',
  is_active: true,
}

const PRODUCT_MRP_20 = {
  id: 101,
  name: 'Super Crisp Potato Chips',
  mrp: '20.00',
  current_stock: '100.000',
  base_unit: 'piece',
  tax_rate: '5.00',
  attributes: { units_per_master_box: 50, net_weight: 0.1 },
}

const PRODUCT_MRP_5 = {
  id: 102,
  name: 'Super Crisp Potato Chips',
  mrp: '5.00',
  current_stock: '200.000',
  base_unit: 'piece',
  tax_rate: '5.00',
  attributes: { units_per_master_box: 100, net_weight: 0.025 },
}

const PRODUCT_MRP_10 = {
  id: 103,
  name: 'Super Crisp Potato Chips',
  mrp: '10.00',
  current_stock: '150.000',
  base_unit: 'piece',
  tax_rate: '5.00',
  attributes: { units_per_master_box: 80, net_weight: 0.05 },
}

const SECOND_PRODUCT = {
  id: 104,
  name: 'Tasty Mango Drink',
  mrp: '15.00',
  current_stock: '80.000',
  base_unit: 'piece',
  tax_rate: '12.00',
  attributes: { units_per_master_box: 24 },
}

describe('Keyboard-driven item entry workflow for NewInvoicePage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    window.HTMLElement.prototype.scrollIntoView = vi.fn()

    vi.spyOn(api, 'get').mockImplementation((url, config) => {
      if (url === '/customers/') {
        return Promise.resolve({ data: { results: [SAMPLE_CUSTOMER] } })
      }
      if (url === `/customers/${SAMPLE_CUSTOMER.id}/report/`) {
        return Promise.resolve({ data: { outstanding_balance: '1200.00' } })
      }
      if (url === '/products/') {
        const search = config?.params?.search || ''
        if (search.toLowerCase().includes('crisp')) {
          // Return products in non-ascending order to test sorting
          return Promise.resolve({ data: { results: [PRODUCT_MRP_20, PRODUCT_MRP_5, PRODUCT_MRP_10] } })
        }
        if (search.toLowerCase().includes('mango')) {
          return Promise.resolve({ data: { results: [SECOND_PRODUCT] } })
        }
        return Promise.resolve({ data: { results: [PRODUCT_MRP_5] } })
      }
      return Promise.resolve({ data: {} })
    })

    vi.spyOn(customersApi, 'fetchCustomerMRPPricing').mockResolvedValue({
      pricing: [
        { mrp: '5.00', rate_per_piece: '4.20', is_active: true },
        { mrp: '10.00', rate_per_piece: '8.40', is_active: true },
        { mrp: '20.00', rate_per_piece: '16.80', is_active: true },
      ],
    })
  })

  it('sorts same-name product results by ascending numeric MRP and places search bar below items', async () => {
    const user = userEvent.setup()

    render(
      <MemoryRouter>
        <NewInvoicePage />
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByLabelText('Search products')).toBeInTheDocument()
    })

    const searchInput = screen.getByLabelText('Search products')
    await user.type(searchInput, 'crisp')

    // Wait for suggestions
    await waitFor(() => {
      const suggestions = screen.getAllByRole('button').filter((b) => b.textContent.includes('Super Crisp'))
      expect(suggestions.length).toBe(3)
      // MRP ₹5 must appear first, then ₹10, then ₹20
      expect(suggestions[0]).toHaveTextContent('MRP ₹5.00')
      expect(suggestions[1]).toHaveTextContent('MRP ₹10.00')
      expect(suggestions[2]).toHaveTextContent('MRP ₹20.00')
    })

    // Click the first suggestion (MRP ₹5)
    const suggestions = screen.getAllByRole('button').filter((b) => b.textContent.includes('Super Crisp'))
    await user.click(suggestions[0])

    // Verify row is added
    await waitFor(() => {
      expect(screen.getByLabelText(/Sales unit for Super Crisp Potato Chips/i)).toBeInTheDocument()
    })

    // Requirement 1: Product search field appears below the item rows in DOM order
    const linesContainer = document.querySelector('.invoice-lines')
    const searchContainer = document.querySelector('.product-search')
    expect(linesContainer).toBeInTheDocument()
    expect(searchContainer).toBeInTheDocument()
    expect(linesContainer.compareDocumentPosition(searchContainer) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()

    // Requirement 2: Adding an item automatically focuses the unit selector of the newly added row
    const unitSelect = screen.getByLabelText(/Sales unit for Super Crisp Potato Chips/i)
    expect(document.activeElement).toBe(unitSelect)
  })

  it('completes the full keyboard navigation sequence: Unit -> Qty -> Rate -> Disc -> Search', async () => {
    const user = userEvent.setup()

    render(
      <MemoryRouter>
        <NewInvoicePage />
      </MemoryRouter>
    )

    const searchInput = screen.getByLabelText('Search products')
    await user.type(searchInput, 'crisp')

    await waitFor(() => {
      expect(screen.getAllByText(/MRP ₹5\.00/).length).toBeGreaterThan(0)
    })

    // Use Enter in search field to select first product
    await user.keyboard('{Enter}')

    // Unit selector should be focused
    const unitSelect = await screen.findByLabelText(/Sales unit for Super Crisp Potato Chips/i)
    await waitFor(() => {
      expect(document.activeElement).toBe(unitSelect)
    })

    // Enter in Unit moves to Quantity and selects value
    await user.keyboard('{Enter}')
    const qtyInput = screen.getByLabelText(/Quantity for Super Crisp Potato Chips/i)
    expect(document.activeElement).toBe(qtyInput)

    // Requirement 4 & 5: ArrowUp/Down do not change numeric value accidentally
    const initialQty = qtyInput.value
    fireEvent.keyDown(qtyInput, { key: 'ArrowUp', code: 'ArrowUp' })
    expect(qtyInput.value).toBe(initialQty)
    fireEvent.keyDown(qtyInput, { key: 'ArrowDown', code: 'ArrowDown' })
    expect(qtyInput.value).toBe(initialQty)

    // Typing replaces the value (simulating full selection)
    await user.clear(qtyInput)
    await user.type(qtyInput, '5')
    expect(qtyInput).toHaveValue(5)

    // Enter in Quantity moves to Rate
    await user.keyboard('{Enter}')
    const rateInput = screen.getByLabelText(/Selling rate per piece for Super Crisp Potato Chips/i)
    expect(document.activeElement).toBe(rateInput)

    // ArrowUp/Down do not change Rate accidentally
    fireEvent.keyDown(rateInput, { key: 'ArrowUp', code: 'ArrowUp' })
    fireEvent.keyDown(rateInput, { key: 'ArrowDown', code: 'ArrowDown' })

    // Typing rate 4.50
    await user.clear(rateInput)
    await user.type(rateInput, '4.50')
    expect(rateInput).toHaveValue(4.5)

    // Enter in Rate moves to Discount
    await user.keyboard('{Enter}')
    const discInput = screen.getByLabelText(/Discount for Super Crisp Potato Chips/i)
    expect(document.activeElement).toBe(discInput)

    // ArrowUp/Down do not change Discount accidentally
    fireEvent.keyDown(discInput, { key: 'ArrowUp', code: 'ArrowUp' })
    fireEvent.keyDown(discInput, { key: 'ArrowDown', code: 'ArrowDown' })

    // Typing discount 2
    await user.clear(discInput)
    await user.type(discInput, '2')
    expect(discInput).toHaveValue(2)

    // Requirement 6: Enter in Discount focuses the product search field, ready for next product
    await user.keyboard('{Enter}')
    expect(document.activeElement).toBe(searchInput)

    // Requirement 7: Adding a second item correctly focuses the new row's unit selector
    await user.type(searchInput, 'mango')
    await waitFor(() => {
      expect(screen.getByText('Tasty Mango Drink')).toBeInTheDocument()
    })
    await user.keyboard('{Enter}')

    const secondUnitSelect = await screen.findByLabelText(/Sales unit for Tasty Mango Drink/i)
    await waitFor(() => {
      expect(document.activeElement).toBe(secondUnitSelect)
    })
  })
})

describe('Keyboard-driven item entry workflow for NewPurchasePage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    window.HTMLElement.prototype.scrollIntoView = vi.fn()

    vi.spyOn(purchasesApi, 'fetchWarehouses').mockResolvedValue([SAMPLE_WAREHOUSE])
    vi.spyOn(purchasesApi, 'fetchNextPurchaseNumber').mockResolvedValue('PO-20261010-001')
    vi.spyOn(suppliersApi, 'fetchActiveSuppliers').mockResolvedValue([SAMPLE_SUPPLIER])
    vi.spyOn(suppliersApi, 'fetchSupplierPricing').mockResolvedValue({
      pricing: [
        { mrp: '5.00', rate_per_piece: '3.50', is_active: true },
        { mrp: '10.00', rate_per_piece: '7.00', is_active: true },
        { mrp: '20.00', rate_per_piece: '14.00', is_active: true },
      ],
    })

    vi.spyOn(purchasesApi, 'searchPurchaseProducts').mockImplementation((query) => {
      if (query.toLowerCase().includes('crisp')) {
        return Promise.resolve({ data: { results: [PRODUCT_MRP_20, PRODUCT_MRP_5, PRODUCT_MRP_10] } })
      }
      if (query.toLowerCase().includes('mango')) {
        return Promise.resolve({ data: { results: [SECOND_PRODUCT] } })
      }
      return Promise.resolve({ data: { results: [PRODUCT_MRP_5] } })
    })
  })

  it('sorts same-name product results by ascending numeric MRP and places search bar below items', async () => {
    const user = userEvent.setup()

    render(
      <MemoryRouter>
        <NewPurchasePage />
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByLabelText('Search products')).toBeInTheDocument()
    })

    const searchInput = screen.getByLabelText('Search products')
    await user.type(searchInput, 'crisp')

    // Wait for suggestions and verify ascending order: ₹5.00 first, then ₹10.00, then ₹20.00
    await waitFor(() => {
      const suggestions = screen.getAllByRole('button').filter((b) => b.textContent.includes('Super Crisp'))
      expect(suggestions.length).toBe(3)
      expect(suggestions[0]).toHaveTextContent('MRP: ₹5.00')
      expect(suggestions[1]).toHaveTextContent('MRP: ₹10.00')
      expect(suggestions[2]).toHaveTextContent('MRP: ₹20.00')
    })

    // Click the lowest MRP product
    const suggestions = screen.getAllByRole('button').filter((b) => b.textContent.includes('Super Crisp'))
    await user.click(suggestions[0])

    await waitFor(() => {
      expect(screen.getByLabelText(/Unit for Super Crisp Potato Chips/i)).toBeInTheDocument()
    })

    // Check search container is below item lines
    const linesContainer = document.querySelector('.invoice-lines')
    const searchContainer = document.querySelector('.product-search')
    expect(linesContainer).toBeInTheDocument()
    expect(searchContainer).toBeInTheDocument()
    expect(linesContainer.compareDocumentPosition(searchContainer) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()

    // Unit selector is focused
    const unitSelect = screen.getByLabelText(/Unit for Super Crisp Potato Chips/i)
    expect(document.activeElement).toBe(unitSelect)
  })

  it('completes the full purchase keyboard sequence: Unit -> Qty -> Rate -> Disc -> Search', async () => {
    const user = userEvent.setup()

    render(
      <MemoryRouter>
        <NewPurchasePage />
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByLabelText('Search products')).toBeInTheDocument()
    })

    const searchInput = screen.getByLabelText('Search products')
    await user.type(searchInput, 'crisp')

    await waitFor(() => {
      expect(screen.getAllByText(/MRP: ₹5\.00/).length).toBeGreaterThan(0)
    })

    // Enter in search selects first product
    await user.keyboard('{Enter}')

    // Unit selector should be focused
    const unitSelect = await screen.findByLabelText(/Unit for Super Crisp Potato Chips/i)
    await waitFor(() => {
      expect(document.activeElement).toBe(unitSelect)
    })

    // Enter in Unit moves to Quantity
    await user.keyboard('{Enter}')
    const qtyInput = screen.getByLabelText(/Quantity in pieces for Super Crisp Potato Chips/i)
    expect(document.activeElement).toBe(qtyInput)

    // ArrowUp/Down do not alter quantity
    const initialQty = qtyInput.value
    fireEvent.keyDown(qtyInput, { key: 'ArrowUp', code: 'ArrowUp' })
    expect(qtyInput.value).toBe(initialQty)
    fireEvent.keyDown(qtyInput, { key: 'ArrowDown', code: 'ArrowDown' })
    expect(qtyInput.value).toBe(initialQty)

    // Type 10
    await user.clear(qtyInput)
    await user.type(qtyInput, '10')
    expect(qtyInput).toHaveValue(10)

    // Enter in Quantity moves to Purchase Rate
    await user.keyboard('{Enter}')
    const rateInput = screen.getByLabelText(/Purchase rate per piece for Super Crisp Potato Chips/i)
    expect(document.activeElement).toBe(rateInput)

    // ArrowUp/Down do not alter Rate
    fireEvent.keyDown(rateInput, { key: 'ArrowUp', code: 'ArrowUp' })
    fireEvent.keyDown(rateInput, { key: 'ArrowDown', code: 'ArrowDown' })

    await user.clear(rateInput)
    await user.type(rateInput, '3.25')
    expect(rateInput).toHaveValue(3.25)

    // Enter in Rate moves to Discount
    await user.keyboard('{Enter}')
    const discInput = screen.getByLabelText(/Discount amount for Super Crisp Potato Chips/i)
    expect(document.activeElement).toBe(discInput)

    // ArrowUp/Down do not alter Discount
    fireEvent.keyDown(discInput, { key: 'ArrowUp', code: 'ArrowUp' })
    fireEvent.keyDown(discInput, { key: 'ArrowDown', code: 'ArrowDown' })

    await user.clear(discInput)
    await user.type(discInput, '1.50')
    expect(discInput).toHaveValue(1.5)

    // Enter in Discount returns focus to Search input
    await user.keyboard('{Enter}')
    expect(document.activeElement).toBe(searchInput)

    // Adding next product focuses its Unit selector
    await user.type(searchInput, 'mango')
    await waitFor(() => {
      expect(screen.getByText('Tasty Mango Drink')).toBeInTheDocument()
    })
    await user.keyboard('{Enter}')

    const secondUnitSelect = await screen.findByLabelText(/Unit for Tasty Mango Drink/i)
    await waitFor(() => {
      expect(document.activeElement).toBe(secondUnitSelect)
    })
  })
})
