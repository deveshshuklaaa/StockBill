import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import InventoryPage from '../pages/InventoryPage'
import * as inventoryApi from '../api/inventory'
import * as warehousesApi from '../api/warehouses'

const BALANCES = {
  count: 1,
  next: null,
  previous: null,
  results: [{
    id: 1,
    product: 7,
    product_name: 'Banana Chips',
    product_sku: 'CH-1',
    product_category_name: 'Snacks',
    product_mrp: '10.00',
    product_base_unit: 'piece',
    product_is_active: true,
    product_attributes: {},
    warehouse_name: 'Main Warehouse',
    quantity_on_hand: '120.000',
    average_cost: '7.50',
  }],
}
const WAREHOUSES = [{ id: 1, name: 'Main Warehouse', code: 'MAIN' }, { id: 2, name: 'Godown 2', code: 'GD2' }]

function mount() {
  return render(<MemoryRouter><InventoryPage /></MemoryRouter>)
}

describe('InventoryPage stock export', () => {
  afterEach(() => vi.restoreAllMocks())

  it('Export Excel sends the search and warehouse filters the list is using', async () => {
    const user = userEvent.setup()
    vi.spyOn(inventoryApi, 'fetchInventoryBalances').mockResolvedValue(BALANCES)
    vi.spyOn(warehousesApi, 'fetchWarehouses').mockResolvedValue(WAREHOUSES)
    let resolveExport
    const exportSpy = vi.spyOn(inventoryApi, 'exportInventoryXlsx').mockImplementation(
      () => new Promise((resolve) => { resolveExport = resolve })
    )

    mount()
    await screen.findByText('Banana Chips')
    await screen.findByRole('option', { name: 'Godown 2' })
    await user.selectOptions(screen.getByLabelText('Filter by warehouse'), '2')
    await user.type(screen.getByLabelText('Search inventory'), 'chips')
    await waitFor(() => expect(inventoryApi.fetchInventoryBalances).toHaveBeenLastCalledWith({ page: 1, warehouse: '2', search: 'chips' }))

    const button = screen.getByRole('button', { name: 'Export stock to Excel' })
    expect(button).toHaveTextContent('Export Excel')
    await user.click(button)
    expect(exportSpy).toHaveBeenCalledWith({ warehouse: '2', search: 'chips' })
    expect(button).toBeDisabled()
    resolveExport('stockbill-inventory.xlsx')
    await waitFor(() => expect(button).not.toBeDisabled())
  })

  it('shows an export error from the API', async () => {
    const user = userEvent.setup()
    vi.spyOn(inventoryApi, 'fetchInventoryBalances').mockResolvedValue(BALANCES)
    vi.spyOn(warehousesApi, 'fetchWarehouses').mockResolvedValue(WAREHOUSES)
    vi.spyOn(inventoryApi, 'exportInventoryXlsx').mockRejectedValue({ response: { status: 400, data: { detail: 'warehouse does not exist.' } } })

    mount()
    await screen.findByText('Banana Chips')
    await user.click(screen.getByRole('button', { name: 'Export stock to Excel' }))
    expect(await screen.findByText(/warehouse does not exist/)).toBeInTheDocument()
  })
})
