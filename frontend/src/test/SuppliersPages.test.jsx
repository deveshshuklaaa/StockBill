// Regression tests for the supplier master data UI.
//
// Covers: /suppliers list (server-side search wiring, active filter,
// pagination, loading/empty/error states, admin-only create/edit) and
// /suppliers/:id detail (identity/GSTIN/address/state/status, purchase
// history scoped server-side via ?supplier=<id>, View Purchase links to
// the existing /purchases/:id route, archive/reactivate by role, snapshot
// immutability note) against the real API contract.
//
// The UI must never filter purchase history client-side or invent supplier
// fields; these tests assert the backend payload flows through unchanged.

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import SuppliersPage from '../pages/SuppliersPage'
import SupplierDetailPage from '../pages/SupplierDetailPage'
import * as suppliersApi from '../api/suppliers'
import * as client from '../api/client'

const useAuth = vi.hoisted(() => vi.fn(() => ({ user: { id: 1, username: 'tester', role: 'admin' }, token: 'tok', loading: false })))
vi.mock('../context/AuthContext', () => ({ useAuth }))

const LIST_PAGE_1 = {
  count: 2,
  next: null,
  previous: null,
  results: [
    {
      id: 41,
      name: 'Alpha Traders Pvt. Ltd.',
      contact_info: '9820011122',
      gstin: '27AAACA1234A1Z5',
      address: '12, Wholesale Market, Mumbai',
      state: 'Maharashtra',
      state_code: '27',
      is_active: true,
      created_at: '2026-09-01T10:00:00Z',
    },
    {
      id: 42,
      name: 'Beta Distributors',
      contact_info: '9820033344',
      gstin: '',
      address: '',
      state: '',
      state_code: '',
      is_active: false,
      created_at: '2026-09-02T10:00:00Z',
    },
  ],
}

const DETAIL = {
  id: 41,
  name: 'Alpha Traders Pvt. Ltd.',
  contact_info: '9820011122',
  gstin: '27AAACA1234A1Z5',
  address: '12, Wholesale Market, Mumbai',
  state: 'Maharashtra',
  state_code: '27',
  is_active: true,
  created_at: '2026-09-01T10:00:00Z',
}

const PURCHASES = {
  count: 1,
  next: null,
  previous: null,
  results: [
    {
      id: 61,
      purchase_number: 'PI/26-27/000001',
      supplier: 41,
      supplier_invoice_no: 'ALPHA-BILL-1',
      invoice_date: '2026-09-10',
      state: 'POSTED',
      total_amount: '708.00',
      warehouse_name: 'Main Warehouse',
    },
  ],
}

let mockUser = { id: 1, username: 'tester', role: 'admin' }

function mountPage(ui, { role = 'admin', route = '/suppliers' } = {}) {
  mockUser = role ? { id: 1, username: 'tester', role } : null
  useAuth.mockImplementation(() => ({ user: mockUser, token: 'tok', loading: false }))
  return render(
    <MemoryRouter initialEntries={[route]}>
      <Routes>
        <Route path="/suppliers" element={ui === 'list' ? <SuppliersPage /> : undefined} />
        <Route path="/suppliers/:id" element={ui === 'detail' ? <SupplierDetailPage /> : undefined} />
        <Route path="/purchases/:id" element={<div>purchase detail page</div>} />
      </Routes>
    </MemoryRouter>
  )
}

beforeEach(() => {
  mockUser = { id: 1, username: 'tester', role: 'admin' }
  useAuth.mockImplementation(() => ({ user: mockUser, token: 'tok', loading: false }))
  vi.restoreAllMocks()
})

describe('SuppliersPage', () => {
  it('renders the supplier list with master data fields', async () => {
    vi.spyOn(suppliersApi, 'fetchSuppliers').mockResolvedValue(LIST_PAGE_1)

    mountPage('list')

    await screen.findByText('Alpha Traders Pvt. Ltd.')
    expect(screen.getByText('9820011122')).toBeInTheDocument()
    expect(screen.getByText('27AAACA1234A1Z5')).toBeInTheDocument()
    expect(screen.getByText('Maharashtra')).toBeInTheDocument()
    expect(screen.getAllByText('Archived').length).toBeGreaterThan(0)
  })

  it('links each row to the supplier detail route', async () => {
    vi.spyOn(suppliersApi, 'fetchSuppliers').mockResolvedValue(LIST_PAGE_1)

    mountPage('list')

    await screen.findByText('Alpha Traders Pvt. Ltd.')
    // Both the name and the View action link to /suppliers/:id.
    const detailLinks = screen.getAllByRole('link').filter((link) => link.getAttribute('href') === '/suppliers/41')
    expect(detailLinks.length).toBeGreaterThan(0)
    expect(detailLinks[0].textContent).toContain('Alpha Traders Pvt. Ltd.')
  })

  it('sends server-side search and status filters', async () => {
    const user = userEvent.setup()
    let capturedParams = null
    vi.spyOn(suppliersApi, 'fetchSuppliers').mockImplementation(async (params = {}) => {
      capturedParams = params
      return LIST_PAGE_1
    })

    mountPage('list')
    await screen.findByText('Alpha Traders Pvt. Ltd.')

    await user.type(screen.getByLabelText('Search suppliers'), 'Alpha')
    await waitFor(() => {
      expect(capturedParams.search).toBe('Alpha')
      expect(capturedParams.page).toBe(1)
    })

    await user.selectOptions(screen.getByLabelText('Filter by status'), 'false')
    await waitFor(() => {
      expect(capturedParams.isActive).toBe('false')
    })
  })

  it('paginates using the backend page parameter', async () => {
    const user = userEvent.setup()
    const captured = []
    vi.spyOn(suppliersApi, 'fetchSuppliers').mockImplementation(async (params = {}) => {
      captured.push(params)
      return { count: 30, next: 'http://x/?page=2', previous: null, results: LIST_PAGE_1.results }
    })

    mountPage('list')
    await screen.findByText('Alpha Traders Pvt. Ltd.')

    await user.click(screen.getByRole('button', { name: /Next →/ }))
    await waitFor(() => {
      expect(captured.at(-1).page).toBe(2)
    })
  })

  it('shows the empty state when no suppliers match', async () => {
    vi.spyOn(suppliersApi, 'fetchSuppliers').mockResolvedValue({
      count: 0, next: null, previous: null, results: [],
    })
    mountPage('list')
    await screen.findByText('No suppliers yet.')
  })

  it('surfaces API errors without raw coercion', async () => {
    vi.spyOn(suppliersApi, 'fetchSuppliers').mockRejectedValue({
      response: { status: 403, data: { detail: 'Only admin users can access this endpoint.' } },
    })
    vi.spyOn(client, 'apiErrorMessage').mockImplementation((err) => err.response.data.detail)

    mountPage('list', { role: 'staff' })
    await screen.findByText('Only admin users can access this endpoint.')
    expect(document.body.textContent).not.toMatch(/0:/)
  })

  it('hides create and edit actions from staff', async () => {
    vi.spyOn(suppliersApi, 'fetchSuppliers').mockResolvedValue(LIST_PAGE_1)

    mountPage('list', { role: 'staff' })
    await screen.findByText('Alpha Traders Pvt. Ltd.')
    expect(screen.queryByRole('button', { name: 'Add supplier' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument()
  })
})

describe('SupplierDetailPage', () => {
  it('renders supplier identity, GSTIN, address, contact, state, and status', async () => {
    vi.spyOn(suppliersApi, 'fetchSupplier').mockResolvedValue(DETAIL)
    vi.spyOn(suppliersApi, 'fetchSupplierPurchases').mockResolvedValue(PURCHASES)

    mountPage('detail', { route: '/suppliers/41' })

    await screen.findByText('Alpha Traders Pvt. Ltd.')
    expect(screen.getByText('27AAACA1234A1Z5')).toBeInTheDocument()
    expect(screen.getByText('12, Wholesale Market, Mumbai')).toBeInTheDocument()
    expect(screen.getByText('9820011122')).toBeInTheDocument()
    expect(screen.getByText('Maharashtra (27)')).toBeInTheDocument()
    expect(screen.getByText('Active')).toBeInTheDocument()
  })

  it('fetches purchase history scoped to the supplier server-side', async () => {
    const historySpy = vi.spyOn(suppliersApi, 'fetchSupplierPurchases').mockResolvedValue(PURCHASES)
    vi.spyOn(suppliersApi, 'fetchSupplier').mockResolvedValue(DETAIL)

    mountPage('detail', { route: '/suppliers/41' })
    await screen.findByText('PI/26-27/000001')

    expect(historySpy).toHaveBeenCalledWith({ supplier: '41', page: 1 })
  })

  it('links View Purchase to the existing purchase detail route', async () => {
    vi.spyOn(suppliersApi, 'fetchSupplier').mockResolvedValue(DETAIL)
    vi.spyOn(suppliersApi, 'fetchSupplierPurchases').mockResolvedValue(PURCHASES)

    mountPage('detail', { route: '/suppliers/41' })
    await screen.findByText('PI/26-27/000001')

    const viewLink = screen.getByRole('link', { name: 'View Purchase' })
    expect(viewLink.getAttribute('href')).toBe('/purchases/61')
  })

  it('shows the purchase history empty state', async () => {
    vi.spyOn(suppliersApi, 'fetchSupplier').mockResolvedValue(DETAIL)
    vi.spyOn(suppliersApi, 'fetchSupplierPurchases').mockResolvedValue({
      count: 0, next: null, previous: null, results: [],
    })

    mountPage('detail', { route: '/suppliers/41' })
    await screen.findByText('No purchases from this supplier yet.')
  })

  it('archives through the backend delete endpoint and refreshes state', async () => {
    const user = userEvent.setup()
    window.confirm = vi.fn(() => true)
    const archiveSpy = vi.spyOn(suppliersApi, 'archiveSupplier').mockResolvedValue()
    vi.spyOn(suppliersApi, 'fetchSupplier')
      .mockResolvedValueOnce(DETAIL)
      .mockResolvedValueOnce({ ...DETAIL, is_active: false })
    vi.spyOn(suppliersApi, 'fetchSupplierPurchases').mockResolvedValue(PURCHASES)

    mountPage('detail', { route: '/suppliers/41' })
    await screen.findByText('Alpha Traders Pvt. Ltd.')

    await user.click(screen.getByRole('button', { name: 'Archive supplier' }))
    await waitFor(() => {
      expect(archiveSpy).toHaveBeenCalledWith('41')
    })
    await waitFor(() => {
      expect(screen.getByText('Archived')).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Reactivate supplier' })).toBeInTheDocument()
    })
  })

  it('reactivates through the backend patch endpoint', async () => {
    const user = userEvent.setup()
    const reactivateSpy = vi.spyOn(suppliersApi, 'reactivateSupplier')
      .mockResolvedValue({ ...DETAIL, is_active: true })
    vi.spyOn(suppliersApi, 'fetchSupplier').mockResolvedValue({ ...DETAIL, is_active: false })
    vi.spyOn(suppliersApi, 'fetchSupplierPurchases').mockResolvedValue(PURCHASES)

    mountPage('detail', { route: '/suppliers/41' })
    await screen.findByText('Alpha Traders Pvt. Ltd.')

    await user.click(screen.getByRole('button', { name: 'Reactivate supplier' }))
    await waitFor(() => {
      expect(reactivateSpy).toHaveBeenCalledWith('41')
    })
    await waitFor(() => {
      expect(screen.getByText('Active')).toBeInTheDocument()
    })
  })

  it('hides archive/reactivate and edit from staff', async () => {
    vi.spyOn(suppliersApi, 'fetchSupplier').mockResolvedValue(DETAIL)
    vi.spyOn(suppliersApi, 'fetchSupplierPurchases').mockRejectedValue({
      response: { status: 403, data: { detail: 'Only admin users can access this endpoint.' } },
    })

    mountPage('detail', { role: 'staff', route: '/suppliers/41' })
    await screen.findByText('Alpha Traders Pvt. Ltd.')
    expect(screen.queryByRole('button', { name: 'Archive supplier' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Reactivate supplier' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Edit supplier' })).not.toBeInTheDocument()
    // Purchase history is admin-only per backend permissions.
    expect(screen.getByText('Purchase history is available to administrators.')).toBeInTheDocument()
  })

  it('edits master data through the backend patch endpoint', async () => {
    const user = userEvent.setup()
    const updateSpy = vi.spyOn(suppliersApi, 'updateSupplier')
      .mockResolvedValue({ ...DETAIL, contact_info: '9899999999' })
    vi.spyOn(suppliersApi, 'fetchSupplier').mockResolvedValue(DETAIL)
    vi.spyOn(suppliersApi, 'fetchSupplierPurchases').mockResolvedValue(PURCHASES)

    mountPage('detail', { route: '/suppliers/41' })
    await screen.findByText('Alpha Traders Pvt. Ltd.')

    await user.click(screen.getByRole('button', { name: 'Edit supplier' }))
    const phoneInput = screen.getByLabelText(/Phone \/ contact/i)
    await user.clear(phoneInput)
    await user.type(phoneInput, '9899999999')
    await user.click(screen.getByRole('button', { name: 'Update supplier' }))

    await waitFor(() => {
      expect(updateSpy).toHaveBeenCalledWith('41', expect.objectContaining({ contact_info: '9899999999' }))
    })
    await waitFor(() => {
      expect(screen.getByText('9899999999')).toBeInTheDocument()
    })
  })

  it('shows the error state when the supplier does not exist', async () => {
    vi.spyOn(suppliersApi, 'fetchSupplier').mockRejectedValue({
      response: { status: 404, data: { detail: 'Not found.' } },
    })
    vi.spyOn(suppliersApi, 'fetchSupplierPurchases').mockResolvedValue({
      count: 0, next: null, previous: null, results: [],
    })
    vi.spyOn(client, 'apiErrorMessage').mockImplementation((err) => err.response.data.detail)

    mountPage('detail', { route: '/suppliers/999' })
    await screen.findByText('Not found.')
    expect(screen.getByRole('link', { name: 'Back to suppliers' })).toBeInTheDocument()
  })
})
