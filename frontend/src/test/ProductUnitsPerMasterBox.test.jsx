import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ProductsPage from '../pages/ProductsPage'
import EditProductPage from '../pages/EditProductPage'
import api from '../api/client'
import {
  emptyProductForm,
  productFormFromProduct,
  buildProductPayload,
  validateUnitsPerMasterBox,
} from '../components/ProductForm'
import { masterBoxSize, formatStockWithBoxes } from '../utils/format'

const mockNavigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  }
})

const useAuth = vi.hoisted(() =>
  vi.fn(() => ({ user: { id: 1, username: 'admin', role: 'admin' }, token: 'tok', loading: false }))
)
vi.mock('../context/AuthContext', () => ({ useAuth }))

const SAMPLE_CATEGORIES = [
  { id: 1, name: 'Snacks', is_active: true },
]

const SAMPLE_TAX_RATES = [
  { id: 1, name: 'GST 18%', rate: '18.00' },
]

const SAMPLE_PRODUCTS = [
  {
    id: 101,
    name: 'Chheda Banana Chips 200g',
    sku: 'SNK-001',
    category_name: 'Snacks',
    brand: 'Chheda',
    mrp: '65.00',
    current_stock: '48.000',
    low_stock_threshold: '10.000',
    tax_rate: '18.00',
    is_active: true,
    units_per_master_box: 24,
    attributes: { units_per_master_box: 24, net_weight: 0.2 },
  },
]

describe('Product Units per Master Box Improvement', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    window.HTMLElement.prototype.scrollIntoView = vi.fn()

    vi.spyOn(api, 'get').mockImplementation((url) => {
      if (url === '/products/') {
        return Promise.resolve({
          data: {
            count: SAMPLE_PRODUCTS.length,
            next: null,
            previous: null,
            results: SAMPLE_PRODUCTS,
          },
        })
      }
      if (url === '/products/101/') {
        return Promise.resolve({ data: SAMPLE_PRODUCTS[0] })
      }
      if (url === '/categories/') {
        return Promise.resolve({ data: { results: SAMPLE_CATEGORIES } })
      }
      if (url === '/tax-rates/') {
        return Promise.resolve({ data: { results: SAMPLE_TAX_RATES } })
      }
      if (url.includes('/attributes/')) {
        return Promise.resolve({ data: [] })
      }
      return Promise.resolve({ data: {} })
    })

    vi.spyOn(api, 'post').mockResolvedValue({
      data: { id: 102, name: 'New Snack', units_per_master_box: 24 },
    })
    vi.spyOn(api, 'patch').mockResolvedValue({
      data: { id: 101, name: 'Chheda Banana Chips 200g', units_per_master_box: 36 },
    })
  })

  it('renders Units per Master Box field in Add Product form with placeholder 24', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <ProductsPage />
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByText('Chheda Banana Chips 200g')).toBeInTheDocument()
    })

    // Click Add Product
    const addBtn = screen.getByRole('button', { name: /add product/i })
    await user.click(addBtn)

    // Verify Units per Master Box input exists with label and placeholder 24
    const masterBoxInput = screen.getByLabelText(/units per master box/i)
    expect(masterBoxInput).toBeInTheDocument()
    expect(masterBoxInput).toHaveAttribute('placeholder', '24')
    expect(masterBoxInput).toHaveAttribute('type', 'number')
    expect(masterBoxInput).toHaveAttribute('min', '1')
  })

  it('submits valid positive whole number units_per_master_box when creating product', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <ProductsPage />
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByText('Chheda Banana Chips 200g')).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: /add product/i }))

    // Fill form
    const nameInput = screen.getByLabelText(/product name/i)
    await user.type(nameInput, 'Salted Peanuts 50g')

    const masterBoxInput = screen.getByLabelText(/units per master box/i)
    await user.type(masterBoxInput, '48')

    // Submit
    const submitBtn = screen.getByRole('button', { name: /save product/i })
    await user.click(submitBtn)

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        '/products/',
        expect.objectContaining({
          name: 'Salted Peanuts 50g',
          units_per_master_box: 48,
          attributes: expect.objectContaining({
            units_per_master_box: 48,
          }),
        })
      )
    })
  })

  it('allows leaving units_per_master_box blank for products where pack size is not applicable', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <ProductsPage />
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByText('Chheda Banana Chips 200g')).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: /add product/i }))

    const nameInput = screen.getByLabelText(/product name/i)
    await user.type(nameInput, 'Loose Grain')

    const masterBoxInput = screen.getByLabelText(/units per master box/i)
    expect(masterBoxInput.value).toBe('')

    const submitBtn = screen.getByRole('button', { name: /save product/i })
    await user.click(submitBtn)

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        '/products/',
        expect.objectContaining({
          name: 'Loose Grain',
          units_per_master_box: null,
        })
      )
    })
  })

  it('validates and rejects zero, negative, and fractional values', async () => {
    expect(validateUnitsPerMasterBox('0')).toBe('Units per Master Box must be greater than 0.')
    expect(validateUnitsPerMasterBox('-5')).toBe('Units per Master Box must be a positive whole number.')
    expect(validateUnitsPerMasterBox('24.5')).toBe('Units per Master Box must be a positive whole number.')
    expect(validateUnitsPerMasterBox('abc')).toBe('Units per Master Box must be a positive whole number.')
    expect(validateUnitsPerMasterBox('')).toBe('')
    expect(validateUnitsPerMasterBox(null)).toBe('')
    expect(validateUnitsPerMasterBox('24')).toBe('')
  })

  it('loads and allows editing units_per_master_box in EditProductPage', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/products/101/edit']}>
        <Routes>
          <Route path="/products/:id/edit" element={<EditProductPage />} />
        </Routes>
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByDisplayValue('Chheda Banana Chips 200g')).toBeInTheDocument()
    })

    const masterBoxInput = screen.getByLabelText(/units per master box/i)
    expect(masterBoxInput).toHaveValue(24)

    // Edit value to 36
    await user.clear(masterBoxInput)
    await user.type(masterBoxInput, '36')

    const saveBtn = screen.getByRole('button', { name: /save changes/i })
    await user.click(saveBtn)

    await waitFor(() => {
      expect(api.patch).toHaveBeenCalledWith(
        '/products/101/',
        expect.objectContaining({
          units_per_master_box: 36,
          attributes: expect.objectContaining({
            units_per_master_box: 36,
          }),
        })
      )
    })
  })

  it('displays units_per_master_box in product table and formatters without changing stock', () => {
    const product = SAMPLE_PRODUCTS[0]
    expect(masterBoxSize(product)).toBe(24)
    // 48 pieces with 24 pcs/box = 2 boxes
    const stockDisplay = formatStockWithBoxes(48, product)
    expect(stockDisplay).toContain('48 pcs')
    expect(stockDisplay).toContain('2 boxes')
  })
})

