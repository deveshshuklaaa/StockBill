import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import api from '../api/client'
import EnvironmentBanner, { BANNER_CLASS, bannerText } from '../components/EnvironmentBanner'

function mockMeta(response) {
  return vi.spyOn(api, 'get').mockImplementation((url) =>
    url === '/meta/' ? response : Promise.resolve({ data: {} })
  )
}

describe('EnvironmentBanner', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    document.documentElement.classList.remove(BANNER_CLASS)
  })

  it('shows a red bar with the environment and database outside production', async () => {
    const spy = mockMeta(Promise.resolve({ data: { environment: 'development', database: 'stockbill@localhost:5450' } }))
    render(<EnvironmentBanner />)
    const bar = await screen.findByRole('status', { name: 'Environment' })
    expect(bar).toHaveTextContent('DEVELOPMENT — test data · stockbill@localhost:5450')
    expect(bar).toHaveClass('env-banner')
    expect(document.documentElement).toHaveClass(BANNER_CLASS)
    expect(spy).toHaveBeenCalledTimes(1)
  })

  it('shows staging too', async () => {
    mockMeta(Promise.resolve({ data: { environment: 'staging', database: 'stockbill@db:5432' } }))
    render(<EnvironmentBanner />)
    expect(await screen.findByRole('status', { name: 'Environment' })).toHaveTextContent('STAGING')
  })

  it('shows nothing in production', async () => {
    const spy = mockMeta(Promise.resolve({ data: { environment: 'production' } }))
    const { container } = render(<EnvironmentBanner />)
    await waitFor(() => expect(spy).toHaveBeenCalled())
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(container).toBeEmptyDOMElement()
    expect(document.documentElement).not.toHaveClass(BANNER_CLASS)
  })

  it('shows nothing and does not throw when /api/meta/ fails', async () => {
    const spy = mockMeta(Promise.reject(new Error('offline')))
    const { container } = render(<EnvironmentBanner />)
    await waitFor(() => expect(spy).toHaveBeenCalled())
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(container).toBeEmptyDOMElement()
  })

  it('removes the page offset when unmounted', async () => {
    mockMeta(Promise.resolve({ data: { environment: 'development', database: 'x@y:1' } }))
    const { unmount } = render(<EnvironmentBanner />)
    await screen.findByRole('status', { name: 'Environment' })
    unmount()
    expect(document.documentElement).not.toHaveClass(BANNER_CLASS)
  })

  it('builds the text from the meta response', () => {
    expect(bannerText({ environment: 'production' })).toBe('')
    expect(bannerText(null)).toBe('')
    expect(bannerText({ environment: 'development' })).toBe('DEVELOPMENT — test data')
  })
})
