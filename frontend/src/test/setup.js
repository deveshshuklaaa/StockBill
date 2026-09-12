import { cleanup } from '@testing-library/react'
import { afterEach, beforeAll, afterAll } from 'vitest'
import '@testing-library/jest-dom/vitest'

afterEach(() => {
  cleanup()
  localStorage.clear()
  sessionStorage.clear()
})
