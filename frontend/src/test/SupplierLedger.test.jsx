// Supplier ledger page: running balance with Payable / Advance labels,
// payment entry (Bank transfer by default), admin-only reversal, print and
// export.

import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as ledgerApi from '../api/supplierLedger'
import SupplierLedgerPage from '../pages/SupplierLedgerPage'

const useAuth = vi.hoisted(() => vi.fn(() => ({ user: { id: 1, username: 'clerk', role: 'staff' }, token: 'tok', loading: false })))
vi.mock('../context/AuthContext', () => ({ useAuth }))

const LEDGER = {
  business: { business_name: 'Divya Enterprises' },
  supplier: { id: 7, name: 'Chheda Foods', gstin: '29AAACC1234D1Z5', contact_info: '98200', address: 'Mumbai' },
  from: null,
  to: null,
  opening_balance: '0.00',
  entries: [
    { kind: 'payment', id: 1, date: '2026-11-01', type_label: 'Payment', reference: 'ADV-1', mode_label: 'Bank transfer', debit: '100000.00', credit: null, balance: '-100000.00', reversible_amount: '100000.00' },
    { kind: 'purchase', id: 5, date: '2026-11-10', type_label: 'Purchase', reference: 'PI/26-27/00005', debit: null, credit: '97368.00', balance: '-2632.00' },
  ],
  total_debit: '100000.00',
  total_credit: '97368.00',
  closing_balance: '-2632.00',
  closing_status: 'ADVANCE',
  current_balance: '-2632.00',
}

function mount() {
  return render(
    <MemoryRouter initialEntries={['/suppliers/7/ledger']}>
      <Routes><Route path="/suppliers/:id/ledger" element={<SupplierLedgerPage />} /></Routes>
    </MemoryRouter>
  )
}

describe('balanceLabel', () => {
  it('uses the payable / advance sign convention', () => {
    expect(ledgerApi.balanceLabel('2632.00')).toBe('Payable')
    expect(ledgerApi.balanceLabel('-2632.00')).toBe('Advance')
    expect(ledgerApi.balanceLabel('0')).toBe('Settled')
  })
})

describe('SupplierLedgerPage', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    useAuth.mockImplementation(() => ({ user: { id: 1, username: 'clerk', role: 'staff' }, token: 'tok', loading: false }))
  })

  it('shows entries in order with a running balance and the closing advance', async () => {
    vi.spyOn(ledgerApi, 'fetchSupplierLedger').mockResolvedValue(LEDGER)
    mount()
    const rows = await screen.findAllByTestId('ledger-row')
    expect(rows).toHaveLength(2)
    expect(within(rows[0]).getByText('₹1,00,000.00 Advance')).toBeInTheDocument()
    expect(within(rows[1]).getByText('₹2,632.00 Advance')).toBeInTheDocument()
    expect(screen.getByTestId('closing-balance')).toHaveTextContent('₹2,632.00 Advance')
    expect(screen.getByText('Chheda Foods')).toBeInTheDocument()
    // Staff cannot reverse.
    expect(screen.queryByRole('button', { name: 'Reverse' })).not.toBeInTheDocument()
  })

  it('records a payment with Bank transfer as the default mode', async () => {
    vi.spyOn(ledgerApi, 'fetchSupplierLedger').mockResolvedValue(LEDGER)
    const create = vi.spyOn(ledgerApi, 'createSupplierPayment').mockResolvedValue({ id: 2 })
    const user = userEvent.setup()
    mount()
    expect(await screen.findByLabelText('Payment mode')).toHaveValue('BANK_TRANSFER')
    await user.type(screen.getByLabelText('Payment amount'), '5000')
    await user.type(screen.getByLabelText('Payment reference'), 'UTR42')
    await user.click(screen.getByRole('button', { name: 'Record payment' }))
    await waitFor(() => expect(create).toHaveBeenCalled())
    expect(create.mock.calls[0][0]).toMatchObject({ supplier: 7, amount: '5000', mode: 'BANK_TRANSFER', reference: 'UTR42' })
    await waitFor(() => expect(ledgerApi.fetchSupplierLedger).toHaveBeenCalledTimes(2))
  })

  it('lets an admin reverse a payment with a reason', async () => {
    useAuth.mockImplementation(() => ({ user: { id: 1, username: 'boss', role: 'admin' }, token: 'tok', loading: false }))
    vi.spyOn(ledgerApi, 'fetchSupplierLedger').mockResolvedValue(LEDGER)
    const reverse = vi.spyOn(ledgerApi, 'reverseSupplierPayment').mockResolvedValue({ id: 1 })
    const user = userEvent.setup()
    mount()
    await user.click(await screen.findByRole('button', { name: 'Reverse' }))
    await user.click(screen.getByRole('button', { name: 'Reverse payment' }))
    expect(reverse).not.toHaveBeenCalled()
    await user.type(screen.getByLabelText('Reversal reason'), 'Bounced')
    await user.click(screen.getByRole('button', { name: 'Reverse payment' }))
    await waitFor(() => expect(reverse).toHaveBeenCalledWith(1, { amount: '100000.00', reason: 'Bounced' }))
  })

  it('prints and exports the statement', async () => {
    vi.spyOn(ledgerApi, 'fetchSupplierLedger').mockResolvedValue(LEDGER)
    const exportSpy = vi.spyOn(ledgerApi, 'exportSupplierStatement').mockResolvedValue('x.xlsx')
    const printSpy = vi.spyOn(window, 'print').mockImplementation(() => {})
    const user = userEvent.setup()
    mount()
    await user.click(await screen.findByRole('button', { name: 'Print statement' }))
    expect(printSpy).toHaveBeenCalled()
    await user.click(screen.getByRole('button', { name: 'Export (Excel)' }))
    await waitFor(() => expect(exportSpy).toHaveBeenCalledWith('7', { from: '', to: '' }))
  })
})
