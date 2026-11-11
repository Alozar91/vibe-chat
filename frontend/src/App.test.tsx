import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import App from './App'

describe('App', () => {
  it('рендерится без падения', () => {
    render(<App />)
    expect(document.body).toBeInTheDocument()
  })
})
