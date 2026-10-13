import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BrowserRouter, MemoryRouter, NavLink, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import NewInvoicePage from '../pages/NewInvoicePage'
import NewPurchasePage from '../pages/NewPurchasePage'
import * as customersApi from '../api/customers'
import * as purchasesApi from '../api/purchases'
import * as suppliersApi from '../api/suppliers'
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

const SAMPLE_PRODUCT = {
  id: 101,
  name: "Chheda's Banana Chips",
  mrp: '10.00',
  current_stock: '500.000',
  base_unit: 'piece',
  tax_rate: '5.00',
  attributes: {
    units_per_master_box: 100,
    net_weight: 0.045,
  },
}

const SAMPLE_SUPPLIER = {
  id: 10,
  name: 'Chheda Agro Food Park Pvt. Ltd.',
  gstin: '27ABECS9815P1ZI',
  state: 'Maharashtra',
  state_code: '27',
  contact_info: '9820011223',
}

describe('Unsaved Changes Protection - New Invoice', () => {
  beforeEach(() => {
    vi.clearAllMocks()

    vi.spyOn(api, 'get').mockImplementation((url) => {
      if (url === '/customers/') {
        return Promise.resolve({ data: { results: [SAMPLE_CUSTOMER] } })
      }
      if (url.startsWith('/customers/42/report')) {
        return Promise.resolve({ data: { outstanding_balance: '0.00' } })
      }
      if (url === '/products/') {
        return Promise.resolve({ data: { results: [SAMPLE_PRODUCT] } })
      }
      return Promise.resolve({ data: {} })
    })

    vi.spyOn(customersApi, 'fetchCustomerMRPPricing').mockResolvedValue({
      pricing: [],
    })
  })

  it('allows leaving a completely blank invoice without showing any prompt', async () => {
    const user = userEvent.setup()

    render(
      <MemoryRouter initialEntries={['/invoices/new']}>
        <NavLink to="/dashboard">Dashboard</NavLink>
        <Routes>
          <Route path="/invoices/new" element={<NewInvoicePage />} />
          <Route path="/dashboard" element={<h1>Dashboard Page</h1>} />
        </Routes>
      </MemoryRouter>
    )

    await screen.findByRole('heading', { name: /New invoice/i })

    // Click navigation link to leave
    await user.click(screen.getByRole('link', { name: 'Dashboard' }))

    // Should navigate immediately without prompt
    expect(screen.getByText('Dashboard Page')).toBeInTheDocument()
    expect(screen.queryByText(/Unsaved Invoice/i)).not.toBeInTheDocument()
  })

  it('triggers unsaved-changes dialog when navigating away from a modified invoice', async () => {
    const user = userEvent.setup()

    render(
      <MemoryRouter initialEntries={['/invoices/new']}>
        <NavLink to="/dashboard">Dashboard</NavLink>
        <Routes>
          <Route path="/invoices/new" element={<NewInvoicePage />} />
          <Route path="/dashboard" element={<h1>Dashboard Page</h1>} />
        </Routes>
      </MemoryRouter>
    )

    await screen.findByRole('heading', { name: /New invoice/i })

    // Modify invoice by entering notes
    const notesInput = screen.getByPlaceholderText('Optional notes on invoice')
    await user.type(notesInput, 'Urgent delivery needed')

    // Try to navigate away
    await user.click(screen.getByRole('link', { name: 'Dashboard' }))

    // Confirmation dialog should appear with 3 options
    expect(screen.getByText('Unsaved Invoice')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save as Draft' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Leave Without Saving' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeInTheDocument()

    // Dashboard page should NOT be displayed yet
    expect(screen.queryByText('Dashboard Page')).not.toBeInTheDocument()
  })

  it('cancels navigation, closes dialog, and preserves entered values on Cancel', async () => {
    const user = userEvent.setup()

    render(
      <MemoryRouter initialEntries={['/invoices/new']}>
        <NavLink to="/dashboard">Dashboard</NavLink>
        <Routes>
          <Route path="/invoices/new" element={<NewInvoicePage />} />
          <Route path="/dashboard" element={<h1>Dashboard Page</h1>} />
        </Routes>
      </MemoryRouter>
    )

    await screen.findByRole('heading', { name: /New invoice/i })

    const notesInput = screen.getByPlaceholderText('Optional notes on invoice')
    await user.type(notesInput, 'Urgent delivery needed')

    await user.click(screen.getByRole('link', { name: 'Dashboard' }))
    expect(screen.getByText('Unsaved Invoice')).toBeInTheDocument()

    // Click Cancel
    await user.click(screen.getByRole('button', { name: 'Cancel' }))

    // Dialog closes
    expect(screen.queryByText('Unsaved Invoice')).not.toBeInTheDocument()
    // Stays on page and notes are preserved
    expect(screen.getByPlaceholderText('Optional notes on invoice').value).toBe('Urgent delivery needed')
    expect(screen.queryByText('Dashboard Page')).not.toBeInTheDocument()
  })

  it('navigates without creating a draft on Leave Without Saving', async () => {
    const user = userEvent.setup()
    const postSpy = vi.spyOn(api, 'post')

    render(
      <MemoryRouter initialEntries={['/invoices/new']}>
        <NavLink to="/dashboard">Dashboard</NavLink>
        <Routes>
          <Route path="/invoices/new" element={<NewInvoicePage />} />
          <Route path="/dashboard" element={<h1>Dashboard Page</h1>} />
        </Routes>
      </MemoryRouter>
    )

    await screen.findByRole('heading', { name: /New invoice/i })

    const notesInput = screen.getByPlaceholderText('Optional notes on invoice')
    await user.type(notesInput, 'Urgent delivery needed')

    await user.click(screen.getByRole('link', { name: 'Dashboard' }))
    expect(screen.getByText('Unsaved Invoice')).toBeInTheDocument()

    // Click Leave Without Saving
    await user.click(screen.getByRole('button', { name: 'Leave Without Saving' }))

    // Navigates to Dashboard
    expect(screen.getByText('Dashboard Page')).toBeInTheDocument()
    // No draft was saved
    expect(postSpy).not.toHaveBeenCalledWith('/invoices/drafts/', expect.anything(), expect.anything())
  })

  it('saves draft via API and then continues requested navigation on Save as Draft', async () => {
    const user = userEvent.setup()
    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({
      data: { id: 77, invoice_number: 'INV-DRAFT-01', state: 'DRAFT' },
    })

    render(
      <MemoryRouter initialEntries={['/invoices/new']}>
        <NavLink to="/products">Products</NavLink>
        <Routes>
          <Route path="/invoices/new" element={<NewInvoicePage />} />
          <Route path="/products" element={<h1>Products Catalogue</h1>} />
        </Routes>
      </MemoryRouter>
    )

    await screen.findByRole('heading', { name: /New invoice/i })

    // Add a product line
    const searchInput = screen.getByLabelText(/Search products/i)
    await user.type(searchInput, 'Banana')
    const addProductBtn = await screen.findByRole('button', { name: /Chheda's Banana Chips/i })
    await user.click(addProductBtn)

    expect(await screen.findByText("Chheda's Banana Chips")).toBeInTheDocument()

    // Try to navigate to /products
    await user.click(screen.getByRole('link', { name: 'Products' }))
    expect(screen.getByText('Unsaved Invoice')).toBeInTheDocument()

    // Click Save as Draft in dialog
    await user.click(screen.getByRole('button', { name: 'Save as Draft' }))

    // Verified draft was posted
    await waitFor(() => {
      expect(postSpy).toHaveBeenCalledWith(
        '/invoices/drafts/',
        expect.objectContaining({
          line_items: expect.arrayContaining([
            expect.objectContaining({ product: 101 }),
          ]),
        }),
        expect.anything()
      )
    })

    // Continues navigation to requested target (/products)
    expect(await screen.findByText('Products Catalogue')).toBeInTheDocument()
  })

  it('stays on page and displays error if Save as Draft fails', async () => {
    const user = userEvent.setup()

    render(
      <MemoryRouter initialEntries={['/invoices/new']}>
        <NavLink to="/dashboard">Dashboard</NavLink>
        <Routes>
          <Route path="/invoices/new" element={<NewInvoicePage />} />
          <Route path="/dashboard" element={<h1>Dashboard Page</h1>} />
        </Routes>
      </MemoryRouter>
    )

    await screen.findByRole('heading', { name: /New invoice/i })

    // Only notes entered, no line items added
    const notesInput = screen.getByPlaceholderText('Optional notes on invoice')
    await user.type(notesInput, 'No lines here')

    await user.click(screen.getByRole('link', { name: 'Dashboard' }))
    expect(screen.getByText('Unsaved Invoice')).toBeInTheDocument()

    // Click Save as Draft
    await user.click(screen.getByRole('button', { name: 'Save as Draft' }))

    // Error is shown in dialog because at least one product is required
    expect(await screen.findByText(/Add at least one product before saving as draft/i)).toBeInTheDocument()
    // Does NOT navigate
    expect(screen.queryByText('Dashboard Page')).not.toBeInTheDocument()
    expect(screen.getByPlaceholderText('Optional notes on invoice')).toBeInTheDocument()
  })

  it('triggers native beforeunload on window when modified', async () => {
    const user = userEvent.setup()

    render(
      <MemoryRouter initialEntries={['/invoices/new']}>
        <Routes>
          <Route path="/invoices/new" element={<NewInvoicePage />} />
        </Routes>
      </MemoryRouter>
    )

    await screen.findByRole('heading', { name: /New invoice/i })

    const notesInput = screen.getByPlaceholderText('Optional notes on invoice')
    await user.type(notesInput, 'Check beforeunload')

    const beforeUnloadEvent = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(beforeUnloadEvent)

    expect(beforeUnloadEvent.defaultPrevented).toBe(true)
  })

  it('navigates cleanly without prompt when successfully saving draft via the page button', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'post').mockResolvedValue({
      data: { id: 99, invoice_number: 'INV-99', state: 'DRAFT' },
    })

    render(
      <MemoryRouter initialEntries={['/invoices/new']}>
        <Routes>
          <Route path="/invoices/new" element={<NewInvoicePage />} />
          <Route path="/invoices/:id" element={<h1>Invoice Detail #99</h1>} />
        </Routes>
      </MemoryRouter>
    )

    await screen.findByRole('heading', { name: /New invoice/i })

    const searchInput = screen.getByLabelText(/Search products/i)
    await user.type(searchInput, 'Banana')
    const addProductBtn = await screen.findByRole('button', { name: /Chheda's Banana Chips/i })
    await user.click(addProductBtn)

    // Click page's own "Save as draft" button
    const saveDraftBtn = screen.getByRole('button', { name: 'Save as draft' })
    await user.click(saveDraftBtn)

    // Navigates directly to detail page without prompting
    expect(await screen.findByText('Invoice Detail #99')).toBeInTheDocument()
    expect(screen.queryByText('Unsaved Invoice')).not.toBeInTheDocument()
  })

  it('navigates cleanly without prompt when successfully creating/posting invoice via the page button', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'post').mockResolvedValue({
      data: { id: 100, invoice_number: 'INV-100', state: 'POSTED' },
    })

    render(
      <MemoryRouter initialEntries={['/invoices/new']}>
        <Routes>
          <Route path="/invoices/new" element={<NewInvoicePage />} />
          <Route path="/invoices/:id" element={<h1>Invoice Detail #100</h1>} />
        </Routes>
      </MemoryRouter>
    )

    await screen.findByRole('heading', { name: /New invoice/i })

    const searchInput = screen.getByLabelText(/Search products/i)
    await user.type(searchInput, 'Banana')
    const addProductBtn = await screen.findByRole('button', { name: /Chheda's Banana Chips/i })
    await user.click(addProductBtn)

    // Click page's "Create invoice" button
    const submitBtn = screen.getByRole('button', { name: 'Create invoice' })
    await user.click(submitBtn)

    expect(await screen.findByText('Invoice Detail #100')).toBeInTheDocument()
    expect(screen.queryByText('Unsaved Invoice')).not.toBeInTheDocument()
  })

  it('triggers unsaved-changes dialog on browser Back and restores history position on Cancel', async () => {
    const user = userEvent.setup()
    const historyGoSpy = vi.spyOn(window.history, 'go').mockImplementation(() => {})

    window.history.pushState({ idx: 0 }, '', '/dashboard')
    window.history.pushState({ idx: 1 }, '', '/invoices/new')

    render(
      <BrowserRouter>
        <Routes>
          <Route path="/dashboard" element={<h1>Dashboard Page</h1>} />
          <Route path="/invoices/new" element={<NewInvoicePage />} />
        </Routes>
      </BrowserRouter>
    )

    await screen.findByRole('heading', { name: /New invoice/i })

    const notesInput = screen.getByPlaceholderText('Optional notes on invoice')
    await user.type(notesInput, 'Back button test note')

    window.history.replaceState({ idx: 0 }, '', '/dashboard')
    const popEvent = new PopStateEvent('popstate', {
      state: { idx: 0 },
      bubbles: true,
      cancelable: true,
    })

    act(() => {
      window.dispatchEvent(popEvent)
    })

    expect(await screen.findByText('Unsaved Invoice')).toBeInTheDocument()

    const cancelBtn = screen.getByRole('button', { name: 'Cancel' })
    await user.click(cancelBtn)

    expect(screen.queryByText('Unsaved Invoice')).not.toBeInTheDocument()
    expect(historyGoSpy).toHaveBeenCalledWith(1)
    expect(screen.getByPlaceholderText('Optional notes on invoice')).toHaveValue('Back button test note')
  })

  it('navigates without creating a draft on Leave Without Saving during browser Back in New Invoice', async () => {
    const user = userEvent.setup()
    const postSpy = vi.spyOn(api, 'post')

    window.history.pushState({ idx: 0 }, '', '/dashboard')
    window.history.pushState({ idx: 1 }, '', '/invoices/new')

    render(
      <BrowserRouter>
        <Routes>
          <Route path="/dashboard" element={<h1>Dashboard Page</h1>} />
          <Route path="/invoices/new" element={<NewInvoicePage />} />
        </Routes>
      </BrowserRouter>
    )

    await screen.findByRole('heading', { name: /New invoice/i })

    const notesInput = screen.getByPlaceholderText('Optional notes on invoice')
    await user.type(notesInput, 'Leave note')

    window.history.replaceState({ idx: 0 }, '', '/dashboard')
    act(() => {
      window.dispatchEvent(
        new PopStateEvent('popstate', { state: { idx: 0 }, bubbles: true, cancelable: true })
      )
    })

    expect(await screen.findByText('Unsaved Invoice')).toBeInTheDocument()

    const leaveBtn = screen.getByRole('button', { name: 'Leave Without Saving' })
    await user.click(leaveBtn)

    expect(await screen.findByText('Dashboard Page')).toBeInTheDocument()
    expect(postSpy).not.toHaveBeenCalled()
  })

  it('saves draft via API on Save as Draft then completes browser Back navigation in New Invoice', async () => {
    const user = userEvent.setup()
    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({
      data: { id: 88, invoice_number: 'INV-DRAFT-88', state: 'DRAFT' },
    })

    window.history.pushState({ idx: 0 }, '', '/dashboard')
    window.history.pushState({ idx: 1 }, '', '/invoices/new')

    render(
      <BrowserRouter>
        <Routes>
          <Route path="/dashboard" element={<h1>Dashboard Page</h1>} />
          <Route path="/invoices/new" element={<NewInvoicePage />} />
        </Routes>
      </BrowserRouter>
    )

    await screen.findByRole('heading', { name: /New invoice/i })

    const searchInput = screen.getByLabelText(/Search products/i)
    await user.type(searchInput, 'Banana')
    const addProductBtn = await screen.findByRole('button', { name: /Chheda's Banana Chips/i })
    await user.click(addProductBtn)

    window.history.replaceState({ idx: 0 }, '', '/dashboard')
    act(() => {
      window.dispatchEvent(
        new PopStateEvent('popstate', { state: { idx: 0 }, bubbles: true, cancelable: true })
      )
    })

    expect(await screen.findByText('Unsaved Invoice')).toBeInTheDocument()

    const saveDraftBtn = screen.getByRole('button', { name: 'Save as Draft' })
    await user.click(saveDraftBtn)

    await waitFor(() => {
      expect(postSpy).toHaveBeenCalledWith(
        '/invoices/drafts/',
        expect.objectContaining({
          line_items: expect.arrayContaining([
            expect.objectContaining({ product: 101 }),
          ]),
        }),
        expect.anything()
      )
    })

    expect(await screen.findByText('Dashboard Page')).toBeInTheDocument()
  })

  it('stays on page and preserves input if Save as Draft fails during browser Back in New Invoice', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'post').mockRejectedValue(new Error('Draft save network failure'))

    window.history.pushState({ idx: 0 }, '', '/dashboard')
    window.history.pushState({ idx: 1 }, '', '/invoices/new')

    render(
      <BrowserRouter>
        <Routes>
          <Route path="/dashboard" element={<h1>Dashboard Page</h1>} />
          <Route path="/invoices/new" element={<NewInvoicePage />} />
        </Routes>
      </BrowserRouter>
    )

    await screen.findByRole('heading', { name: /New invoice/i })

    const searchInput = screen.getByLabelText(/Search products/i)
    await user.type(searchInput, 'Banana')
    const addProductBtn = await screen.findByRole('button', { name: /Chheda's Banana Chips/i })
    await user.click(addProductBtn)

    window.history.replaceState({ idx: 0 }, '', '/dashboard')
    act(() => {
      window.dispatchEvent(
        new PopStateEvent('popstate', { state: { idx: 0 }, bubbles: true, cancelable: true })
      )
    })

    expect(await screen.findByText('Unsaved Invoice')).toBeInTheDocument()

    const saveDraftBtn = screen.getByRole('button', { name: 'Save as Draft' })
    await user.click(saveDraftBtn)

    expect(await screen.findByText('Django server could not be reached.')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /New invoice/i })).toBeInTheDocument()
    expect(screen.getByText("Chheda's Banana Chips")).toBeInTheDocument()
  })
})

describe('Unsaved Changes Protection - New Purchase', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.spyOn(purchasesApi, 'fetchWarehouses').mockResolvedValue([
      { id: 1, name: 'Main Warehouse', code: 'MAIN' },
    ])
    vi.spyOn(purchasesApi, 'fetchNextPurchaseNumber').mockResolvedValue('PI/26-27/000005')
    vi.spyOn(suppliersApi, 'fetchActiveSuppliers').mockResolvedValue([SAMPLE_SUPPLIER])
    vi.spyOn(purchasesApi, 'searchPurchaseProducts').mockResolvedValue({
      data: { results: [SAMPLE_PRODUCT] },
    })
  })

  it('allows leaving a blank purchase without showing any prompt', async () => {
    const user = userEvent.setup()

    render(
      <MemoryRouter initialEntries={['/purchases/new']}>
        <NavLink to="/dashboard">Dashboard</NavLink>
        <Routes>
          <Route path="/purchases/new" element={<NewPurchasePage />} />
          <Route path="/dashboard" element={<h1>Dashboard Page</h1>} />
        </Routes>
      </MemoryRouter>
    )

    await screen.findByRole('heading', { name: /New purchase/i })

    await user.click(screen.getByRole('link', { name: 'Dashboard' }))
    expect(screen.getByText('Dashboard Page')).toBeInTheDocument()
    expect(screen.queryByText(/Unsaved Purchase/i)).not.toBeInTheDocument()
  })

  it('triggers unsaved-changes dialog when modifying supplier invoice number and navigating away', async () => {
    const user = userEvent.setup()

    render(
      <MemoryRouter initialEntries={['/purchases/new']}>
        <NavLink to="/suppliers">Suppliers</NavLink>
        <Routes>
          <Route path="/purchases/new" element={<NewPurchasePage />} />
          <Route path="/suppliers" element={<h1>Suppliers Page</h1>} />
        </Routes>
      </MemoryRouter>
    )

    await screen.findByRole('heading', { name: /New purchase/i })

    // Modify invoice number
    const invInput = screen.getByPlaceholderText('As printed on the bill')
    await user.type(invInput, 'SUPP-INV-99')

    // Navigate to suppliers
    await user.click(screen.getByRole('link', { name: 'Suppliers' }))

    expect(screen.getByText('Unsaved Purchase')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save as Draft' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Leave Without Saving' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeInTheDocument()
    expect(screen.queryByText('Suppliers Page')).not.toBeInTheDocument()
  })

  it('navigates without creating a draft on Leave Without Saving in New Purchase', async () => {
    const user = userEvent.setup()
    const postSpy = vi.spyOn(api, 'post')

    render(
      <MemoryRouter initialEntries={['/purchases/new']}>
        <NavLink to="/suppliers">Suppliers</NavLink>
        <Routes>
          <Route path="/purchases/new" element={<NewPurchasePage />} />
          <Route path="/suppliers" element={<h1>Suppliers Page</h1>} />
        </Routes>
      </MemoryRouter>
    )

    await screen.findByRole('heading', { name: /New purchase/i })

    const invInput = screen.getByPlaceholderText('As printed on the bill')
    await user.type(invInput, 'SUPP-INV-99')

    await user.click(screen.getByRole('link', { name: 'Suppliers' }))
    expect(screen.getByText('Unsaved Purchase')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Leave Without Saving' }))

    expect(screen.getByText('Suppliers Page')).toBeInTheDocument()
    expect(postSpy).not.toHaveBeenCalledWith('/purchase-invoices/', expect.anything(), expect.anything())
  })

  it('saves draft via API and continues navigation on Save as Draft in New Purchase', async () => {
    const user = userEvent.setup()
    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({
      data: { id: 88, purchase_number: 'PI-DRAFT-01', state: 'DRAFT' },
    })

    render(
      <MemoryRouter initialEntries={['/purchases/new']}>
        <NavLink to="/suppliers">Suppliers</NavLink>
        <Routes>
          <Route path="/purchases/new" element={<NewPurchasePage />} />
          <Route path="/suppliers" element={<h1>Suppliers Page</h1>} />
        </Routes>
      </MemoryRouter>
    )

    await screen.findByRole('heading', { name: /New purchase/i })

    // Pick supplier
    const supplierInput = screen.getByPlaceholderText(/Search active suppliers/i)
    await user.type(supplierInput, 'Chheda')
    const supplierBtn = await screen.findByRole('button', { name: /Chheda Agro Food Park/i })
    await user.click(supplierBtn)

    // Add a product
    const productInput = screen.getByPlaceholderText(/Search products by name/i)
    await user.type(productInput, 'Banana')
    const productBtn = await screen.findByRole('button', { name: /Chheda's Banana Chips/i })
    await user.click(productBtn)

    // Fill purchase rate
    const rateInput = await screen.findByLabelText(/Purchase rate per piece for/i)
    await user.type(rateInput, '7.50')

    // Navigate to suppliers
    await user.click(screen.getByRole('link', { name: 'Suppliers' }))
    expect(screen.getByText('Unsaved Purchase')).toBeInTheDocument()

    // Click Save as Draft
    await user.click(screen.getByRole('button', { name: 'Save as Draft' }))

    await waitFor(() => {
      expect(postSpy).toHaveBeenCalledWith(
        '/purchase-invoices/',
        expect.objectContaining({
          supplier: 10,
          post: false,
          line_items: expect.arrayContaining([
            expect.objectContaining({ product: 101, rate: 7.5 }),
          ]),
        }),
        expect.anything()
      )
    })

    // Lands on requested target
    expect(await screen.findByText('Suppliers Page')).toBeInTheDocument()
  })

  it('navigates cleanly without prompt when saving draft via the page button in New Purchase', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'post').mockResolvedValue({
      data: { id: 188, purchase_number: 'PI-DRAFT-188', state: 'DRAFT' },
    })

    render(
      <MemoryRouter initialEntries={['/purchases/new']}>
        <Routes>
          <Route path="/purchases/new" element={<NewPurchasePage />} />
          <Route path="/purchases/:id" element={<h1>Purchase Detail #188</h1>} />
        </Routes>
      </MemoryRouter>
    )

    await screen.findByRole('heading', { name: /New purchase/i })

    const supplierInput = screen.getByPlaceholderText(/Search active suppliers/i)
    await user.type(supplierInput, 'Chheda')
    const supplierBtn = await screen.findByRole('button', { name: /Chheda Agro Food Park/i })
    await user.click(supplierBtn)

    const productInput = screen.getByPlaceholderText(/Search products by name/i)
    await user.type(productInput, 'Banana')
    const productBtn = await screen.findByRole('button', { name: /Chheda's Banana Chips/i })
    await user.click(productBtn)

    const rateInput = await screen.findByLabelText(/Purchase rate per piece for/i)
    await user.type(rateInput, '7.50')

    // Click page's own "Save draft" button
    const saveDraftBtn = screen.getByRole('button', { name: 'Save draft' })
    await user.click(saveDraftBtn)

    expect(await screen.findByText('Purchase Detail #188')).toBeInTheDocument()
    expect(screen.queryByText('Unsaved Purchase')).not.toBeInTheDocument()
  })

  it('navigates cleanly without prompt when posting purchase via the page button in New Purchase', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'post').mockResolvedValue({
      data: { id: 189, purchase_number: 'PI-POSTED-189', state: 'POSTED' },
    })

    render(
      <MemoryRouter initialEntries={['/purchases/new']}>
        <Routes>
          <Route path="/purchases/new" element={<NewPurchasePage />} />
          <Route path="/purchases/:id" element={<h1>Purchase Detail #189</h1>} />
        </Routes>
      </MemoryRouter>
    )

    await screen.findByRole('heading', { name: /New purchase/i })

    const supplierInput = screen.getByPlaceholderText(/Search active suppliers/i)
    await user.type(supplierInput, 'Chheda')
    const supplierBtn = await screen.findByRole('button', { name: /Chheda Agro Food Park/i })
    await user.click(supplierBtn)

    const productInput = screen.getByPlaceholderText(/Search products by name/i)
    await user.type(productInput, 'Banana')
    const productBtn = await screen.findByRole('button', { name: /Chheda's Banana Chips/i })
    await user.click(productBtn)

    const rateInput = await screen.findByLabelText(/Purchase rate per piece for/i)
    await user.type(rateInput, '7.50')

    // Click page's own "Post & receive stock" button
    const postBtn = screen.getByRole('button', { name: 'Post & receive stock' })
    await user.click(postBtn)

    expect(await screen.findByText('Purchase Detail #189')).toBeInTheDocument()
    expect(screen.queryByText('Unsaved Purchase')).not.toBeInTheDocument()
  })

  it('triggers unsaved-changes dialog on browser Back and restores history position on Cancel in New Purchase', async () => {
    const user = userEvent.setup()
    const historyGoSpy = vi.spyOn(window.history, 'go').mockImplementation(() => {})

    window.history.pushState({ idx: 0 }, '', '/dashboard')
    window.history.pushState({ idx: 1 }, '', '/purchases/new')

    render(
      <BrowserRouter>
        <Routes>
          <Route path="/dashboard" element={<h1>Dashboard Page</h1>} />
          <Route path="/purchases/new" element={<NewPurchasePage />} />
        </Routes>
      </BrowserRouter>
    )

    await screen.findByRole('heading', { name: /New purchase/i })

    const invoiceNoInput = screen.getByPlaceholderText('As printed on the bill')
    await user.type(invoiceNoInput, 'BILL-POP-1')

    window.history.replaceState({ idx: 0 }, '', '/dashboard')
    const popEvent = new PopStateEvent('popstate', {
      state: { idx: 0 },
      bubbles: true,
      cancelable: true,
    })

    act(() => {
      window.dispatchEvent(popEvent)
    })

    expect(await screen.findByText('Unsaved Purchase')).toBeInTheDocument()

    const cancelBtn = screen.getByRole('button', { name: 'Cancel' })
    await user.click(cancelBtn)

    expect(screen.queryByText('Unsaved Purchase')).not.toBeInTheDocument()
    expect(historyGoSpy).toHaveBeenCalledWith(1)
    expect(screen.getByPlaceholderText('As printed on the bill')).toHaveValue('BILL-POP-1')
  })

  it('navigates without creating a draft on Leave Without Saving during browser Back in New Purchase', async () => {
    const user = userEvent.setup()
    const postSpy = vi.spyOn(api, 'post')

    window.history.pushState({ idx: 0 }, '', '/dashboard')
    window.history.pushState({ idx: 1 }, '', '/purchases/new')

    render(
      <BrowserRouter>
        <Routes>
          <Route path="/dashboard" element={<h1>Dashboard Page</h1>} />
          <Route path="/purchases/new" element={<NewPurchasePage />} />
        </Routes>
      </BrowserRouter>
    )

    await screen.findByRole('heading', { name: /New purchase/i })

    const invoiceNoInput = screen.getByPlaceholderText('As printed on the bill')
    await user.type(invoiceNoInput, 'BILL-LEAVE-1')

    window.history.replaceState({ idx: 0 }, '', '/dashboard')
    act(() => {
      window.dispatchEvent(
        new PopStateEvent('popstate', { state: { idx: 0 }, bubbles: true, cancelable: true })
      )
    })

    expect(await screen.findByText('Unsaved Purchase')).toBeInTheDocument()

    const leaveBtn = screen.getByRole('button', { name: 'Leave Without Saving' })
    await user.click(leaveBtn)

    expect(await screen.findByText('Dashboard Page')).toBeInTheDocument()
    expect(postSpy).not.toHaveBeenCalled()
  })

  it('saves draft via API on Save as Draft then completes browser Back navigation in New Purchase', async () => {
    const user = userEvent.setup()
    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({
      data: { id: 195, purchase_number: 'PI-DRAFT-195', state: 'DRAFT' },
    })

    window.history.pushState({ idx: 0 }, '', '/dashboard')
    window.history.pushState({ idx: 1 }, '', '/purchases/new')

    render(
      <BrowserRouter>
        <Routes>
          <Route path="/dashboard" element={<h1>Dashboard Page</h1>} />
          <Route path="/purchases/new" element={<NewPurchasePage />} />
        </Routes>
      </BrowserRouter>
    )

    await screen.findByRole('heading', { name: /New purchase/i })

    const supplierInput = screen.getByPlaceholderText(/Search active suppliers/i)
    await user.type(supplierInput, 'Chheda')
    const supplierBtn = await screen.findByRole('button', { name: /Chheda Agro Food Park/i })
    await user.click(supplierBtn)

    const productInput = screen.getByPlaceholderText(/Search products by name/i)
    await user.type(productInput, 'Banana')
    const productBtn = await screen.findByRole('button', { name: /Chheda's Banana Chips/i })
    await user.click(productBtn)

    const rateInput = await screen.findByLabelText(/Purchase rate per piece for/i)
    await user.type(rateInput, '7.50')

    window.history.replaceState({ idx: 0 }, '', '/dashboard')
    act(() => {
      window.dispatchEvent(
        new PopStateEvent('popstate', { state: { idx: 0 }, bubbles: true, cancelable: true })
      )
    })

    expect(await screen.findByText('Unsaved Purchase')).toBeInTheDocument()

    const saveDraftBtn = screen.getByRole('button', { name: 'Save as Draft' })
    await user.click(saveDraftBtn)

    await waitFor(() => {
      expect(postSpy).toHaveBeenCalledWith(
        '/purchase-invoices/',
        expect.objectContaining({
          supplier: 10,
          post: false,
          line_items: expect.arrayContaining([
            expect.objectContaining({ product: 101, rate: 7.5 }),
          ]),
        }),
        expect.anything()
      )
    })

    expect(await screen.findByText('Dashboard Page')).toBeInTheDocument()
  })

  it('stays on page and preserves input if Save as Draft fails during browser Back in New Purchase', async () => {
    const user = userEvent.setup()
    vi.spyOn(api, 'post').mockRejectedValue(new Error('Draft purchase network error'))

    window.history.pushState({ idx: 0 }, '', '/dashboard')
    window.history.pushState({ idx: 1 }, '', '/purchases/new')

    render(
      <BrowserRouter>
        <Routes>
          <Route path="/dashboard" element={<h1>Dashboard Page</h1>} />
          <Route path="/purchases/new" element={<NewPurchasePage />} />
        </Routes>
      </BrowserRouter>
    )

    await screen.findByRole('heading', { name: /New purchase/i })

    const supplierInput = screen.getByPlaceholderText(/Search active suppliers/i)
    await user.type(supplierInput, 'Chheda')
    const supplierBtn = await screen.findByRole('button', { name: /Chheda Agro Food Park/i })
    await user.click(supplierBtn)

    const productInput = screen.getByPlaceholderText(/Search products by name/i)
    await user.type(productInput, 'Banana')
    const productBtn = await screen.findByRole('button', { name: /Chheda's Banana Chips/i })
    await user.click(productBtn)

    const rateInput = await screen.findByLabelText(/Purchase rate per piece for/i)
    await user.type(rateInput, '7.50')

    window.history.replaceState({ idx: 0 }, '', '/dashboard')
    act(() => {
      window.dispatchEvent(
        new PopStateEvent('popstate', { state: { idx: 0 }, bubbles: true, cancelable: true })
      )
    })

    expect(await screen.findByText('Unsaved Purchase')).toBeInTheDocument()

    const saveDraftBtn = screen.getByRole('button', { name: 'Save as Draft' })
    await user.click(saveDraftBtn)

    expect(await screen.findByText('Django server could not be reached.')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /New purchase/i })).toBeInTheDocument()
    expect(screen.getByText("Chheda's Banana Chips")).toBeInTheDocument()
  })
})
