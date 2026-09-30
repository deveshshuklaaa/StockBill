import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import WarehousesPage from '../pages/WarehousesPage'
import * as warehousesApi from '../api/warehouses'

const useAuth = vi.hoisted(() => vi.fn(() => ({
  user: { id: 1, username: 'admin_user', role: 'admin' },
  token: 'mock-token',
  loading: false,
})))
vi.mock('../context/AuthContext', () => ({ useAuth }))

const SAMPLE_WAREHOUSES = [
  {
    id: 1,
    name: 'Main Warehouse',
    code: 'MAIN',
    address: 'Plot 4, Malad West, Mumbai',
    state: 'Maharashtra',
    state_code: '27',
    is_active: true,
  },
  {
    id: 2,
    name: 'Secondary Depot',
    code: 'DEPOT-2',
    address: 'Gala 12, Bhiwandi',
    state: 'Maharashtra',
    state_code: '27',
    is_active: false,
  },
]

describe('WarehousesPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.spyOn(warehousesApi, 'fetchWarehouses').mockResolvedValue(SAMPLE_WAREHOUSES)
    vi.spyOn(warehousesApi, 'fetchWarehouseSummary').mockResolvedValue(SAMPLE_WAREHOUSES)
    vi.spyOn(warehousesApi, 'createWarehouse').mockResolvedValue({
      id: 3,
      name: 'New Hub',
      code: 'HUB-3',
      address: 'Thane',
      state: 'Maharashtra',
      state_code: '27',
      is_active: true,
    })
    vi.spyOn(warehousesApi, 'updateWarehouse').mockResolvedValue({
      id: 1,
      name: 'Main Warehouse Updated',
      code: 'MAIN',
      address: 'Plot 4, Malad West, Mumbai',
      state: 'Maharashtra',
      state_code: '27',
      is_active: true,
    })
    useAuth.mockReturnValue({
      user: { id: 1, username: 'admin_user', role: 'admin' },
      token: 'mock-token',
      loading: false,
    })
  })

  it('renders warehouse list with active/inactive indicators and code', async () => {
    render(
      <MemoryRouter>
        <WarehousesPage />
      </MemoryRouter>
    )

    expect(screen.getByRole('heading', { level: 1, name: 'Warehouses' })).toBeInTheDocument()
    await waitFor(() => {
      expect(screen.getByText('Main Warehouse')).toBeInTheDocument()
      expect(screen.getByText('Secondary Depot')).toBeInTheDocument()
    })

    expect(screen.getByText('MAIN')).toBeInTheDocument()
    expect(screen.getByText('DEPOT-2')).toBeInTheDocument()
    expect(screen.getByText('Plot 4, Malad West, Mumbai')).toBeInTheDocument()
    expect(screen.getByText('Active')).toBeInTheDocument()
    expect(screen.getByText('Inactive')).toBeInTheDocument()
  })

  it('shows Add Warehouse button for admin and opens creation modal', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <WarehousesPage />
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByText('Main Warehouse')).toBeInTheDocument()
    })

    const addBtn = screen.getByRole('button', { name: /Add Warehouse/i })
    expect(addBtn).toBeInTheDocument()

    await user.click(addBtn)
    expect(screen.getByRole('heading', { level: 2, name: 'Add Warehouse' })).toBeInTheDocument()
    expect(screen.getByLabelText(/Warehouse Name/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/Warehouse Code/i)).toBeInTheDocument()
  })

  it('hides Add/Edit/Deactivate buttons for staff role', async () => {
    useAuth.mockReturnValue({
      user: { id: 2, username: 'staff_user', role: 'staff' },
      token: 'mock-token',
      loading: false,
    })

    render(
      <MemoryRouter>
        <WarehousesPage />
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByText('Main Warehouse')).toBeInTheDocument()
    })

    expect(screen.queryByRole('button', { name: /Add Warehouse/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Edit/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Deactivate/i })).not.toBeInTheDocument()
  })

  it('successfully creates a warehouse via modal submission', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <WarehousesPage />
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByText('Main Warehouse')).toBeInTheDocument()
    })

    await user.click(screen.getByRole('button', { name: /Add Warehouse/i }))

    await user.type(screen.getByLabelText(/Warehouse Name/i), 'New Hub')
    await user.type(screen.getByLabelText(/Warehouse Code/i), 'HUB-3')
    await user.type(screen.getByLabelText(/Address/i), 'Thane')

    const saveBtn = screen.getByRole('button', { name: /Save Warehouse/i })
    await user.click(saveBtn)

    await waitFor(() => {
      expect(warehousesApi.createWarehouse).toHaveBeenCalledWith(
        expect.objectContaining({
          name: 'New Hub',
          code: 'HUB-3',
          address: 'Thane',
          state: 'Maharashtra',
          state_code: '27',
          is_active: true,
        })
      )
    })
  })

  it('prompts confirmation modal before deactivating a warehouse', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <WarehousesPage />
      </MemoryRouter>
    )

    await waitFor(() => {
      expect(screen.getByText('Main Warehouse')).toBeInTheDocument()
    })

    const deactBtn = screen.getAllByRole('button', { name: /Deactivate/i })[0]
    await user.click(deactBtn)

    expect(screen.getByRole('heading', { level: 3, name: /Deactivate Warehouse/i })).toBeInTheDocument()
    expect(screen.getByText(/Are you sure you want to deactivate/i)).toBeInTheDocument()

    const confirmBtn = screen.getByRole('button', { name: /Yes, Deactivate/i })
    await user.click(confirmBtn)

    await waitFor(() => {
      expect(warehousesApi.updateWarehouse).toHaveBeenCalledWith(
        1,
        expect.objectContaining({ is_active: false })
      )
    })
  })
})
