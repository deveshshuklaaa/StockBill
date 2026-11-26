// Credit-note destination (Main by default, Damaged on request) and the
// minimal supplier-return panel.

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import api from '../api/client'
import * as invoicesApi from '../api/invoices'
import SupplierReturnsPanel from '../components/SupplierReturnsPanel'
import InvoiceDetailPage from '../pages/InvoiceDetailPage'

const useAuth = vi.hoisted(() => vi.fn(() => ({ user: { id: 1, username: 'clerk', role: 'staff' }, token: 'tok', loading: false })))
vi.mock('../context/AuthContext', () => ({ useAuth }))

const MAIN = { id: 1, code: 'MAIN', name: 'Main Warehouse', is_active: true, is_sellable: true }
const DAMAGED = { id: 3, code: 'DAMAGED', name: 'Damaged / Quarantine', is_active: true, is_sellable: false }

const INVOICE = {
  id: 11, invoice_number: 'DE/26-27/00001', invoice_date: '2026-11-27', state: 'POSTED',
  payment_type: 'credit', payment_status: 'credit', tax_mode: 'exclusive', place_of_supply: '29',
  customer_name: 'Van Sales - Route 1', total_amount: '1050.00', round_off: '0.00', source_warehouse: null,
  line_items: [{ id: 501, product: 101, product_name: 'Chips', base_quantity: '10.000', base_unit_snapshot: 'piece', quantity: '10.000', rate_charged: '100.00', line_total: '1050.00' }],
}

function mountDetail() {
  return render(
    <MemoryRouter initialEntries={['/invoices/11']}>
      <Routes><Route path="/invoices/:id" element={<InvoiceDetailPage />} /></Routes>
    </MemoryRouter>
  )
}

describe('Credit note destination', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(invoicesApi, 'fetchInvoice').mockResolvedValue(INVOICE)
    vi.spyOn(invoicesApi, 'fetchCorrectionEligibility').mockResolvedValue({ eligible: false, reason: 'x' })
    vi.spyOn(api, 'get').mockImplementation((url) => {
      if (url === '/warehouses/') return Promise.resolve({ data: { results: [MAIN, DAMAGED] } })
      return Promise.resolve({ data: {} })
    })
  })

  it('defaults to Main and sends no destination', async () => {
    const create = vi.spyOn(invoicesApi, 'createCreditNote').mockResolvedValue({ id: 9, credit_note_number: 'CN/26-27/00001', destination_warehouse: null })
    const user = userEvent.setup()
    mountDetail()
    await user.click(await screen.findByRole('button', { name: 'Issue credit note' }))
    const select = await screen.findByLabelText('Return destination warehouse')
    expect(select).toHaveValue('')
    await screen.findByRole('option', { name: /Damaged \/ Quarantine \(DAMAGED\) — not sellable/ })
    await user.type(screen.getByLabelText('Return quantity for Chips'), '4')
    await user.click(screen.getByRole('button', { name: 'Create credit note' }))
    await waitFor(() => expect(create).toHaveBeenCalled())
    const payload = create.mock.calls[0][0]
    expect(payload).toEqual({ original_invoice: 11, reason: '', line_items: [{ invoice_line_item: 501, product: 101, quantity: 4 }] })
    expect(await screen.findByText(/CN\/26-27\/00001 created; stock returned to Main/)).toBeInTheDocument()
  })

  it('sends the Damaged warehouse when chosen', async () => {
    const create = vi.spyOn(invoicesApi, 'createCreditNote').mockResolvedValue({ id: 9, credit_note_number: 'CN/26-27/00002', destination_warehouse: 3, destination_warehouse_name: 'Damaged / Quarantine' })
    const user = userEvent.setup()
    mountDetail()
    await user.click(await screen.findByRole('button', { name: 'Issue credit note' }))
    await screen.findByRole('option', { name: /Damaged/ })
    await user.selectOptions(screen.getByLabelText('Return destination warehouse'), '3')
    await user.type(screen.getByLabelText('Return quantity for Chips'), '6')
    await user.type(screen.getByLabelText('Credit note reason'), 'Route damaged pile')
    await user.click(screen.getByRole('button', { name: 'Create credit note' }))
    await waitFor(() => expect(create).toHaveBeenCalled())
    expect(create.mock.calls[0][0].destination_warehouse).toBe(3)
    expect(create.mock.calls[0][0].reason).toBe('Route damaged pile')
    expect(await screen.findByText(/stock returned to Damaged \/ Quarantine/)).toBeInTheDocument()
  })

  it('asks for a quantity before submitting', async () => {
    const create = vi.spyOn(invoicesApi, 'createCreditNote')
    const user = userEvent.setup()
    mountDetail()
    await user.click(await screen.findByRole('button', { name: 'Issue credit note' }))
    await user.click(await screen.findByRole('button', { name: 'Create credit note' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Enter a return quantity')
    expect(create).not.toHaveBeenCalled()
  })
})

describe('SupplierReturnsPanel', () => {
  beforeEach(() => vi.restoreAllMocks())

  const RETURN = {
    id: 4, display_number: 'SR-4', return_date: '2026-11-27', product: 101, product_name: 'Chips',
    quantity: '6.000', replaced_quantity: '4.000', outstanding_quantity: '2.000', value: '48.00',
  }

  it('lists returns with pending quantity and records a replacement', async () => {
    vi.spyOn(api, 'get').mockImplementation((url) => {
      if (url === '/supplier-returns/') return Promise.resolve({ data: { results: [RETURN] } })
      return Promise.resolve({ data: {} })
    })
    const post = vi.spyOn(api, 'post').mockResolvedValue({ data: { ...RETURN, replaced_quantity: '6.000', outstanding_quantity: '0.000' } })
    const user = userEvent.setup()
    render(<SupplierReturnsPanel supplierId="7" canEdit />)
    expect(await screen.findByText('SR-4')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Receive replacement' }))
    expect(screen.getByLabelText('Replacement quantity')).toHaveValue(2)
    await user.click(screen.getByRole('button', { name: 'Receive into Main' }))
    await waitFor(() => expect(post).toHaveBeenCalledWith('/supplier-returns/4/replacements/', { quantity: '2.000', reference: '' }))
  })

  it('is read-only for staff', async () => {
    vi.spyOn(api, 'get').mockResolvedValue({ data: { results: [RETURN] } })
    render(<SupplierReturnsPanel supplierId="7" canEdit={false} />)
    expect(await screen.findByText('SR-4')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Receive replacement' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Send back to supplier' })).not.toBeInTheDocument()
  })
})
