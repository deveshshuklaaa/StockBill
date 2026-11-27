import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import api from '../api/client'
import * as customersApi from '../api/customers'
import NewInvoicePage from '../pages/NewInvoicePage'
import { formatRoundOff, roundOffInvoiceTotal } from '../utils/roundOff'

const useAuth = vi.hoisted(() => vi.fn(() => ({ user: { id: 1, username: 'clerk', role: 'staff' }, token: 'tok', loading: false })))
vi.mock('../context/AuthContext', () => ({ useAuth }))

describe('roundOffInvoiceTotal (half-up to the rupee)', () => {
  it.each([
    [107.10, -0.10, 107],
    [107.50, 0.50, 108],
    [107.49, -0.49, 107],
    [107.51, 0.49, 108],
    [108.00, 0, 108],
    [0.50, 0.50, 1],
  ])('%s -> round off %s, total %s', (exact, roundOff, total) => {
    expect(roundOffInvoiceTotal(exact, true)).toEqual({ roundOff, total })
  })

  it('is not fooled by float noise around .50 and .49', () => {
    expect(roundOffInvoiceTotal(0.1 + 107.4, true)).toEqual({ roundOff: 0.5, total: 108 }) // 107.50000000000001
    expect(roundOffInvoiceTotal(107.49999999999999, true)).toEqual({ roundOff: 0.5, total: 108 }) // rounds to 107.50 paise
    // 102.38 + 5% = 107.499; the server rounds GST to paise first (5.12),
    // so the bill is 107.50 and rounds up, as here.
    expect(roundOffInvoiceTotal(102.38 * 1.05, true).total).toBe(108)
    expect(roundOffInvoiceTotal(107.494, true).total).toBe(107) // 107.49 in paise
  })

  it('keeps the exact total when the setting is off', () => {
    expect(roundOffInvoiceTotal(107.1, false)).toEqual({ roundOff: 0, total: 107.1 })
  })

  it('formats the sign', () => {
    expect(formatRoundOff(0.9)).toBe('+0.90')
    expect(formatRoundOff(-0.1)).toBe('−0.10')
    expect(formatRoundOff(0)).toBe('0.00')
  })
})

const CUSTOMER = { id: 42, name: 'ABC Traders', gstin: '', state: 'Maharashtra', state_code: '27', is_active: true }
const PRODUCT = { id: 101, name: 'Banana Chips 1kg', mrp: '120.00', current_stock: '500.000', base_unit: 'piece', tax_rate: '5.00', attributes: {} }

function mockApi(roundOff) {
  vi.spyOn(api, 'get').mockImplementation((url) => {
    if (url === '/billing-settings/') return Promise.resolve({ data: { round_off_invoice_total: roundOff } })
    if (url === '/customers/') return Promise.resolve({ data: { results: [CUSTOMER] } })
    if (url === '/products/') return Promise.resolve({ data: { results: [PRODUCT] } })
    return Promise.resolve({ data: {} })
  })
  vi.spyOn(customersApi, 'fetchCustomerMRPPricing').mockResolvedValue({ pricing: [] })
}

async function addLineAtRate(rate) {
  const user = userEvent.setup()
  render(<MemoryRouter><NewInvoicePage /></MemoryRouter>)
  await waitFor(() => expect(screen.getByText('Walk-in (no account)')).toBeInTheDocument())
  await user.type(screen.getByLabelText('Search products'), 'Banana')
  await user.click(await screen.findByText('Banana Chips 1kg'))
  const rateInput = await screen.findByLabelText(/Selling rate per piece for Banana Chips 1kg/i)
  await user.clear(rateInput)
  await user.type(rateInput, rate)
}

describe('NewInvoicePage round-off preview', () => {
  beforeEach(() => vi.restoreAllMocks())

  it('shows a Round off row and the rounded grand total when the setting is on', async () => {
    mockApi(true)
    await addLineAtRate('102') // 102.00 + 5% = 107.10
    await waitFor(() => expect(screen.getByTestId('round-off-row')).toHaveTextContent('−0.10'))
    expect(screen.getByTestId('grand-total')).toHaveTextContent('₹107.00')
  })

  it('shows no Round off row and the exact estimate when the setting is off', async () => {
    mockApi(false)
    await addLineAtRate('102')
    await waitFor(() => expect(screen.getByTestId('grand-total')).toHaveTextContent('₹107.1'))
    expect(screen.queryByTestId('round-off-row')).not.toBeInTheDocument()
  })

  it('shows nothing extra if billing settings cannot be loaded', async () => {
    vi.spyOn(api, 'get').mockImplementation((url) => {
      if (url === '/billing-settings/') return Promise.reject(new Error('offline'))
      if (url === '/customers/') return Promise.resolve({ data: { results: [CUSTOMER] } })
      if (url === '/products/') return Promise.resolve({ data: { results: [PRODUCT] } })
      return Promise.resolve({ data: {} })
    })
    vi.spyOn(customersApi, 'fetchCustomerMRPPricing').mockResolvedValue({ pricing: [] })
    await addLineAtRate('102')
    await waitFor(() => expect(screen.getByTestId('grand-total')).toHaveTextContent('₹107.1'))
    expect(screen.queryByTestId('round-off-row')).not.toBeInTheDocument()
  })
})
