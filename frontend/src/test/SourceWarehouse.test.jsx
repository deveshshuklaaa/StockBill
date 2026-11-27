// Optional invoice source warehouse: hidden when there is nothing to choose,
// absent from the payload unless chosen, shown on the invoice detail.

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import api from '../api/client'
import * as customersApi from '../api/customers'
import * as invoicesApi from '../api/invoices'
import InvoiceDetailPage from '../pages/InvoiceDetailPage'
import NewInvoicePage from '../pages/NewInvoicePage'
import { saleSourceOptions } from '../utils/warehouses'

const useAuth = vi.hoisted(() => vi.fn(() => ({ user: { id: 1, username: 'clerk', role: 'admin' }, token: 'tok', loading: false })))
vi.mock('../context/AuthContext', () => ({ useAuth }))

const PRODUCT = { id: 101, name: 'Banana Chips 1kg', mrp: '120.00', current_stock: '500.000', base_unit: 'piece', tax_rate: '5.00', attributes: {} }
const MAIN = { id: 1, code: 'MAIN', name: 'Main Warehouse', is_active: true, is_sellable: true }
const VAN = { id: 2, code: 'VAN1', name: 'Van 1', is_active: true, is_sellable: true }
const DAMAGED = { id: 3, code: 'DAMAGED', name: 'Damaged / Quarantine', is_active: true, is_sellable: false }

function mockApi(warehouses) {
  vi.spyOn(api, 'get').mockImplementation((url) => {
    if (url === '/warehouses/') return Promise.resolve({ data: warehouses })
    if (url === '/customers/') return Promise.resolve({ data: { results: [] } })
    if (url === '/products/') return Promise.resolve({ data: { results: [PRODUCT] } })
    return Promise.resolve({ data: {} })
  })
  vi.spyOn(customersApi, 'fetchCustomerMRPPricing').mockResolvedValue({ pricing: [] })
  return vi.spyOn(api, 'post').mockResolvedValue({ data: { id: 77 } })
}

async function fillOneLine(user) {
  await waitFor(() => expect(screen.getByText('Walk-in (no account)')).toBeInTheDocument())
  await user.type(screen.getByLabelText('Search products'), 'Banana')
  await user.click(await screen.findByText('Banana Chips 1kg'))
  const rateInput = await screen.findByLabelText(/Selling rate per piece for Banana Chips 1kg/i)
  await user.clear(rateInput)
  await user.type(rateInput, '100')
}

describe('saleSourceOptions', () => {
  it('drops Main, inactive and non-sellable warehouses', () => {
    expect(saleSourceOptions([MAIN, VAN, DAMAGED, { ...VAN, id: 9, is_active: false }])).toEqual([VAN])
  })
})

describe('NewInvoicePage source warehouse', () => {
  beforeEach(() => vi.restoreAllMocks())

  it('shows no selector when Main is the only sellable warehouse', async () => {
    mockApi([MAIN, DAMAGED])
    render(<MemoryRouter><NewInvoicePage /></MemoryRouter>)
    await waitFor(() => expect(screen.getByText('Walk-in (no account)')).toBeInTheDocument())
    expect(screen.queryByLabelText('Source warehouse')).not.toBeInTheDocument()
  })

  it('defaults to Main and sends no source_warehouse for a normal sale', async () => {
    const post = mockApi([MAIN, VAN])
    const user = userEvent.setup()
    render(<MemoryRouter><NewInvoicePage /></MemoryRouter>)
    const select = await screen.findByLabelText('Source warehouse')
    expect(select).toHaveValue('')
    expect(screen.getByRole('option', { name: 'Main (default)' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: /Damaged/ })).not.toBeInTheDocument()
    await fillOneLine(user)
    await user.click(screen.getByRole('button', { name: 'Create invoice' }))
    await waitFor(() => expect(post).toHaveBeenCalled())
    const [url, payload] = post.mock.calls[0]
    expect(url).toBe('/invoices/')
    expect(payload).not.toHaveProperty('source_warehouse')
  })

  it('sends the chosen warehouse id', async () => {
    const post = mockApi([MAIN, VAN])
    const user = userEvent.setup()
    render(<MemoryRouter><NewInvoicePage /></MemoryRouter>)
    await user.selectOptions(await screen.findByLabelText('Source warehouse'), 'Van 1 (VAN1)')
    await fillOneLine(user)
    await user.click(screen.getByRole('button', { name: 'Create invoice' }))
    await waitFor(() => expect(post).toHaveBeenCalled())
    expect(post.mock.calls[0][1].source_warehouse).toBe(2)
  })
})

describe('InvoiceDetailPage source warehouse', () => {
  beforeEach(() => vi.restoreAllMocks())

  const DETAIL = {
    id: 11, invoice_number: 'DE/2026-27/0001', invoice_date: '2026-11-27', state: 'POSTED',
    payment_type: 'cash', payment_status: 'paid', tax_mode: 'exclusive', place_of_supply: '29',
    customer_name: 'Walk-in customer', total_amount: '100.00', round_off: '0.00', line_items: [],
  }

  function mount() {
    return render(
      <MemoryRouter initialEntries={['/invoices/11']}>
        <Routes><Route path="/invoices/:id" element={<InvoiceDetailPage />} /></Routes>
      </MemoryRouter>
    )
  }

  it('shows the chosen source warehouse', async () => {
    vi.spyOn(invoicesApi, 'fetchInvoice').mockResolvedValue({ ...DETAIL, source_warehouse: 2, source_warehouse_code: 'VAN1', source_warehouse_name: 'Van 1' })
    mount()
    expect(await screen.findByText('Stock from: Van 1 (VAN1)')).toBeInTheDocument()
  })

  it('shows Main when none was chosen', async () => {
    vi.spyOn(invoicesApi, 'fetchInvoice').mockResolvedValue({ ...DETAIL, source_warehouse: null })
    mount()
    expect(await screen.findByText('Stock from: Main (default)')).toBeInTheDocument()
  })
})
