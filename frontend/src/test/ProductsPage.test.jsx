import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ProductsPage from '../pages/ProductsPage'
import api from '../api/client'

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
  { id: 2, name: 'Beverages', is_active: true },
]

const SAMPLE_TAX_RATES = [
  { id: 1, name: 'GST 5%', rate: '5.00' },
  { id: 2, name: 'GST 12%', rate: '12.00' },
]

const SAMPLE_PRODUCTS = [
  {
    id: 101,
    name: 'Potato Chips Masala 50g',
    sku: 'SNK-001',
    category_name: 'Snacks',
    brand: 'CrispyBites',
    mrp: '10.00',
    current_stock: '150.000',
    low_stock_threshold: '20.000',
    tax_rate: '5.00',
    is_active: true,
    attributes: { net_weight: 0.05 },
  },
  {
    id: 102,
    name: 'Mango Drink 200ml',
    sku: 'BEV-002',
    category_name: 'Beverages',
    brand: 'FruitSplash',
    mrp: '20.00',
    current_stock: '80.000',
    low_stock_threshold: '10.000',
    tax_rate: '12.00',
    is_active: true,
    attributes: {},
  },
]

describe('ProductsPage - Product Creation Form UX Improvement', () => {
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
      data: { id: 103, name: 'New Banana Chips' },
    })
  })

  it('renders products table and does not display the creation form initially', async () => {
    render(
      <MemoryRouter>
        <ProductsPage />
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByText('Potato Chips Masala 50g')).toBeInTheDocument()
      expect(screen.getByText('Mango Drink 200ml')).toBeInTheDocument()
    })

    expect(screen.getByRole('button', { name: /Add product/i })).toBeInTheDocument()
    expect(screen.queryByLabelText(/Product name/i)).not.toBeInTheDocument()
  })

  it('displays the product creation form at the top (above table) and focuses first input on Add Product click', async () => {
    const user = userEvent.setup()

    render(
      <MemoryRouter>
        <ProductsPage />
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByText('Potato Chips Masala 50g')).toBeInTheDocument()
    })

    const addProductBtn = screen.getByRole('button', { name: /Add product/i })
    await user.click(addProductBtn)

    // Form should be rendered
    const formHeading = await screen.findByRole('heading', { name: /Add product/i, level: 2 })
    expect(formHeading).toBeInTheDocument()

    // 1. Verify form is positioned above the table-frame in DOM order
    const formContainer = document.querySelector('.product-form-container')
    const tableFrame = document.querySelector('.table-frame')
    expect(formContainer).toBeInTheDocument()
    expect(tableFrame).toBeInTheDocument()
    expect(formContainer.compareDocumentPosition(tableFrame) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()

    // Verify the form only renders once (not duplicated at bottom)
    const forms = document.querySelectorAll('form.record-form')
    expect(forms.length).toBe(1)

    // 2. Verify scrollIntoView was called on form container
    expect(window.HTMLElement.prototype.scrollIntoView).toHaveBeenCalled()

    // 3. Verify keyboard focus is moved to the first input field (Product name)
    const nameInput = screen.getByLabelText(/Product name/i)
    await waitFor(() => {
      expect(document.activeElement).toBe(nameInput)
    })
  })

  it('closes form on Cancel and preserves product table', async () => {
    const user = userEvent.setup()

    render(
      <MemoryRouter>
        <ProductsPage />
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByText('Potato Chips Masala 50g')).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: /Add product/i }))
    expect(screen.getByRole('heading', { name: /Add product/i, level: 2 })).toBeInTheDocument()

    // Click Cancel
    const cancelBtn = screen.getByRole('button', { name: /Cancel/i })
    await user.click(cancelBtn)

    // Form should disappear
    expect(screen.queryByRole('heading', { name: /Add product/i, level: 2 })).not.toBeInTheDocument()
    expect(document.querySelector('.product-form-container')).not.toBeInTheDocument()

    // Product list remains intact
    expect(screen.getByText('Potato Chips Masala 50g')).toBeInTheDocument()
    expect(screen.getByText('Mango Drink 200ml')).toBeInTheDocument()
  })

  it('submits form, calls API, closes form on success, and refreshes product list', async () => {
    const user = userEvent.setup()

    render(
      <MemoryRouter>
        <ProductsPage />
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByText('Potato Chips Masala 50g')).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: /Add product/i }))

    const nameInput = screen.getByLabelText(/Product name/i)
    await user.type(nameInput, 'New Banana Chips')

    const brandInput = screen.getByLabelText(/Brand/i)
    await user.type(brandInput, 'Chheda')

    const saveBtn = screen.getByRole('button', { name: /Save product/i })
    await user.click(saveBtn)

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        '/products/',
        expect.objectContaining({
          name: 'New Banana Chips',
          brand: 'Chheda',
        })
      )
    })

    // On success, form closes
    await waitFor(() => {
      expect(screen.queryByRole('heading', { name: /Add product/i, level: 2 })).not.toBeInTheDocument()
    })
  })

  it('navigates to edit route when Edit button is clicked on a table row', async () => {
    const user = userEvent.setup()

    render(
      <MemoryRouter>
        <ProductsPage />
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByText('Potato Chips Masala 50g')).toBeInTheDocument()
    })

    const editButtons = screen.getAllByRole('button', { name: /Edit/i })
    await user.click(editButtons[0])

    expect(mockNavigate).toHaveBeenCalledWith('/products/101/edit')
  })

  it('preserves entered values and refocuses first input when Add Product is clicked while form is already open', async () => {
    const user = userEvent.setup()

    render(
      <MemoryRouter>
        <ProductsPage />
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByText('Potato Chips Masala 50g')).toBeInTheDocument()
    })

    const addProductBtn = screen.getByRole('button', { name: /Add product/i })
    await user.click(addProductBtn)

    const nameInput = screen.getByLabelText(/Product name/i)
    await user.type(nameInput, 'Partially Entered Product')
    const brandInput = screen.getByLabelText(/Brand/i)
    await user.type(brandInput, 'MyBrand')

    expect(nameInput.value).toBe('Partially Entered Product')
    expect(brandInput.value).toBe('MyBrand')

    // Click "Add product" again
    await user.click(addProductBtn)

    // Form remains open and inputs are NOT cleared
    expect(screen.getByLabelText(/Product name/i).value).toBe('Partially Entered Product')
    expect(screen.getByLabelText(/Brand/i).value).toBe('MyBrand')
    expect(window.HTMLElement.prototype.scrollIntoView).toHaveBeenCalled()
    expect(document.activeElement).toBe(nameInput)
  })
})
