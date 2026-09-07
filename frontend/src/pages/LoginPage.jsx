import { useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import StatusMessage from '../components/StatusMessage'
import { useAuth } from '../context/AuthContext'

export default function LoginPage() {
  const { token, login, authError } = useAuth()
  const navigate = useNavigate()
  const [form, setForm] = useState({ username: '', password: '' })
  const [busy, setBusy] = useState(false)

  if (token) return <Navigate to="/products" replace />

  async function submit(event) {
    event.preventDefault()
    setBusy(true)
    try {
      await login(form.username, form.password)
      navigate('/products')
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="login-page">
      <section className="login-panel">
        <div className="login-brand"><span className="brand-mark">DE</span><span>StockBill</span></div>
        <div className="login-heading">
          <p className="eyebrow">Divya Enterprises</p>
          <h1>Back office, ready.</h1>
          <p>Sign in to manage stock, customers, and daily operations.</p>
        </div>
        <form className="login-form" onSubmit={submit}>
          <label>Username<input autoComplete="username" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} required /></label>
          <label>Password<input type="password" autoComplete="current-password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} required /></label>
          <StatusMessage>{authError}</StatusMessage>
          <button className="primary-button full-width" disabled={busy}>{busy ? 'Signing in...' : 'Sign in'}</button>
        </form>
        <p className="security-note">Your session is kept in this browser tab only. It is cleared when you sign out.</p>
      </section>
      <aside className="login-aside">
        <div className="aside-rule" />
        <p className="eyebrow">Operational clarity</p>
        <h2>Know what is on the shelf before the next bill.</h2>
        <p>One focused workspace for the people moving product through Divya Enterprises every day.</p>
        <div className="aside-stats"><span><strong>01</strong> stock view</span><span><strong>02</strong> customer ledger</span></div>
      </aside>
    </main>
  )
}
