import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as settingsApi from '../api/settings'
import LogoSettings from '../components/LogoSettings'

describe('LogoSettings', () => {
  beforeEach(() => {
    globalThis.URL.createObjectURL = vi.fn(() => 'blob:logo-preview')
    globalThis.URL.revokeObjectURL = vi.fn()
  })
  afterEach(() => vi.restoreAllMocks())

  it('shows the current logo and removes it', async () => {
    const user = userEvent.setup()
    vi.spyOn(settingsApi, 'fetchBusinessLogoBlob').mockResolvedValue(new Blob(['png']))
    const remove = vi.spyOn(settingsApi, 'deleteBusinessLogo').mockResolvedValue()
    render(<LogoSettings hasLogo />)
    expect(await screen.findByAltText('Current shop logo')).toHaveAttribute('src', 'blob:logo-preview')
    await user.click(screen.getByRole('button', { name: 'Remove logo' }))
    await waitFor(() => expect(remove).toHaveBeenCalled())
    expect(await screen.findByText('No logo')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Remove logo' })).not.toBeInTheDocument()
  })

  it('uploads a PNG/JPEG file and shows the preview', async () => {
    const user = userEvent.setup()
    vi.spyOn(settingsApi, 'fetchBusinessLogoBlob').mockResolvedValue(new Blob(['png']))
    const upload = vi.spyOn(settingsApi, 'uploadBusinessLogo').mockResolvedValue({ has_logo: true })
    render(<LogoSettings hasLogo={false} />)
    const input = screen.getByLabelText('Logo file')
    expect(input).toHaveAttribute('accept', 'image/png,image/jpeg')
    const file = new File(['fake'], 'shop.png', { type: 'image/png' })
    await user.upload(input, file)
    await waitFor(() => expect(upload).toHaveBeenCalledWith(file))
    expect(await screen.findByAltText('Current shop logo')).toBeInTheDocument()
    expect(screen.getByText(/Logo uploaded/)).toBeInTheDocument()
  })

  it('shows the server message when the upload is rejected', async () => {
    const user = userEvent.setup()
    vi.spyOn(settingsApi, 'uploadBusinessLogo').mockRejectedValue({
      response: { status: 400, data: { logo: ['The logo must be a PNG or JPEG image (this file is GIF).'] } },
    })
    render(<LogoSettings hasLogo={false} />)
    await user.upload(screen.getByLabelText('Logo file'), new File(['gif'], 'a.png', { type: 'image/png' }))
    expect(await screen.findByText('The logo must be a PNG or JPEG image (this file is GIF).')).toBeInTheDocument()
    expect(screen.getByText('No logo')).toBeInTheDocument()
  })
})
