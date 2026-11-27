import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import StockBillLogo from '../components/StockBillLogo'
import LoginPage from '../pages/LoginPage'

vi.mock('../context/AuthContext', () => ({
  useAuth: () => ({ token: null, user: null, login: vi.fn(), authError: '' }),
}))

describe('StockBill branding', () => {
  it('renders the wordmark as live text in two coloured halves', () => {
    const { container } = render(<StockBillLogo tone="light" />)
    expect(container.querySelector('.sb-stock')).toHaveTextContent('Stock')
    expect(container.querySelector('.sb-bill')).toHaveTextContent('Bill')
    expect(container.querySelector('.sb-wordmark')).toHaveTextContent('StockBill')
    expect(container.querySelector('img.sb-icon')).toHaveAttribute('width', '28')
    expect(container.querySelector('.sb-lockup')).toHaveClass('sb-lockup-light')
  })

  it('login page shows StockBill and a neutral product line, no shop name', () => {
    render(<MemoryRouter><LoginPage /></MemoryRouter>)
    expect(screen.getByText('Billing and inventory')).toBeInTheDocument()
    expect(document.querySelector('.login-brand .sb-wordmark')).toHaveTextContent('StockBill')
    expect(document.body).not.toHaveTextContent(/divya/i)
  })
})
