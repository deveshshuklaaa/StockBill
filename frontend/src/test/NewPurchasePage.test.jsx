import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import NewPurchasePage from '../pages/NewPurchasePage'
import * as purchasesApi from '../api/purchases'
import * as suppliersApi from '../api/suppliers'
import api from '../api/client'

const useAuth = vi.hoisted(() => vi.fn(() => ({ user: { id: 1, username: 'admin', role: 'admin' }, token: 'tok', loading: false })))
vi.mock('../context/AuthContext', () => ({ useAuth }))

const SAMPLE_PRODUCT_192 = {
  id: 181,
  name: "Chheda's Soya Snax",
  mrp: '10.00',
  current_stock: '0.000',
  base_unit: 'piece',
  tax_rate: '5.00',
  attributes: {
    units_per_master_box: 192,
    net_weight: 0.038,
  },
}

const SAMPLE_PRODUCT_120 = {
  id: 167,
  name: "Chheda's Krispy Korn Masala",
  mrp: '5.00',
  current_stock: '0.000',
  base_unit: 'piece',
  tax_rate: '5.00',
  attributes: {
    units_per_master_box: 120,
    net_weight: 0.029,
  },
}

describe('NewPurchasePage master box purchase rate calculations', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.spyOn(purchasesApi, 'fetchWarehouses').mockResolvedValue([
      { id: 1, name: 'Main Warehouse', code: 'MAIN' },
    ])
    vi.spyOn(purchasesApi, 'fetchNextPurchaseNumber').mockResolvedValue('PI/26-27/000004')
    vi.spyOn(suppliersApi, 'fetchActiveSuppliers').mockResolvedValue([
      { id: 10, name: 'Chheda Agro Food Park Pvt. Ltd.', gstin: '27ABECS9815P1ZI', state: 'Maharashtra', state_code: '27' },
    ])
  })

  it('calculates master box taxable amount as base_quantity (5 x 192 = 960) x rate (6.66)', async () => {
    vi.spyOn(purchasesApi, 'searchPurchaseProducts').mockResolvedValue({
      data: { results: [SAMPLE_PRODUCT_192] },
    })

    render(
      <MemoryRouter>
        <NewPurchasePage />
      </MemoryRouter>
    )

    await waitFor(() => expect(screen.getByText('New purchase')).toBeInTheDocument())

    // Search and add product
    const productInput = screen.getByPlaceholderText('Search products by name to add...')
    await userEvent.type(productInput, 'Soya')

    await waitFor(() => expect(screen.getByRole('button', { name: new RegExp("Chheda's Soya Snax") })).toBeInTheDocument())
    await userEvent.click(screen.getByRole('button', { name: new RegExp("Chheda's Soya Snax") }))

    // Switch unit to Master box
    const unitSelect = screen.getByRole('combobox', { name: /Unit/i })
    await userEvent.selectOptions(unitSelect, 'master box')

    // Enter quantity = 5 master boxes
    const qtyInput = screen.getByLabelText(/Quantity in master boxes/i)
    await userEvent.clear(qtyInput)
    await userEvent.type(qtyInput, '5')

    // Enter rate = 6.66 / piece
    const rateInput = screen.getByLabelText(/Purchase rate per piece/i)
    await userEvent.clear(rateInput)
    await userEvent.type(rateInput, '6.66')

    // Verify conversion badge shows 5 × 192 = 960 Pieces
    expect(screen.getByText(/Conversion: 5 × 192 = 960 Pieces/i)).toBeInTheDocument()

    // Taxable: 960 × 6.66 = 6,393.60
    expect(screen.getByText(/Taxable: Rs 6,393.60/i)).toBeInTheDocument()

    // 5% GST = 319.68, Total = 6,713.28
    expect(screen.getAllByText(/Rs 6,713.28/i).length).toBeGreaterThanOrEqual(1)
  })

  it('produces identical taxable amount and total for 960 pieces and 5 master boxes (x192)', async () => {
    vi.spyOn(purchasesApi, 'searchPurchaseProducts').mockResolvedValue({
      data: { results: [SAMPLE_PRODUCT_192] },
    })

    render(
      <MemoryRouter>
        <NewPurchasePage />
      </MemoryRouter>
    )

    await waitFor(() => expect(screen.getByText('New purchase')).toBeInTheDocument())

    const productInput = screen.getByPlaceholderText('Search products by name to add...')
    await userEvent.type(productInput, 'Soya')

    await waitFor(() => expect(screen.getByRole('button', { name: new RegExp("Chheda's Soya Snax") })).toBeInTheDocument())
    await userEvent.click(screen.getByRole('button', { name: new RegExp("Chheda's Soya Snax") }))

    // Default unit is piece, set quantity = 960 pieces, rate = 6.66
    const qtyInput = screen.getByLabelText(/Quantity in pieces/i)
    await userEvent.clear(qtyInput)
    await userEvent.type(qtyInput, '960')

    const rateInput = screen.getByLabelText(/Purchase rate per piece/i)
    await userEvent.clear(rateInput)
    await userEvent.type(rateInput, '6.66')

    // Verify piece calculation
    expect(screen.getByText(/Taxable: Rs 6,393.60/i)).toBeInTheDocument()
    expect(screen.getAllByText(/Rs 6,713.28/i).length).toBeGreaterThanOrEqual(1)
  })

  it('calculates 12 master boxes x 120 pcs @ 3.33/piece correctly as 4,795.20 taxable', async () => {
    vi.spyOn(purchasesApi, 'searchPurchaseProducts').mockResolvedValue({
      data: { results: [SAMPLE_PRODUCT_120] },
    })

    render(
      <MemoryRouter>
        <NewPurchasePage />
      </MemoryRouter>
    )

    await waitFor(() => expect(screen.getByText('New purchase')).toBeInTheDocument())

    const productInput = screen.getByPlaceholderText('Search products by name to add...')
    await userEvent.type(productInput, 'Krispy')

    await waitFor(() => expect(screen.getByRole('button', { name: new RegExp("Chheda's Krispy Korn Masala") })).toBeInTheDocument())
    await userEvent.click(screen.getByRole('button', { name: new RegExp("Chheda's Krispy Korn Masala") }))

    const unitSelect = screen.getByRole('combobox', { name: /Unit/i })
    await userEvent.selectOptions(unitSelect, 'master box')

    const qtyInput = screen.getByLabelText(/Quantity in master boxes/i)
    await userEvent.clear(qtyInput)
    await userEvent.type(qtyInput, '12')

    const rateInput = screen.getByLabelText(/Purchase rate per piece/i)
    await userEvent.clear(rateInput)
    await userEvent.type(rateInput, '3.33')

    // 12 × 120 = 1440 pieces
    expect(screen.getByText(/Conversion: 12 × 120 = 1440 Pieces/i)).toBeInTheDocument()

    // 1440 × 3.33 = 4,795.20
    expect(screen.getByText(/Taxable: Rs 4,795.20/i)).toBeInTheDocument()
  })
})
