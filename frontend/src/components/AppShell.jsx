import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

export default function AppShell() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const isAdmin = user?.role === 'admin'

  function signOut() {
    logout()
    navigate('/login')
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-lockup">
          <div className="brand-mark">DE</div>
          <div>
            <strong>Divya Enterprises</strong>
            <span>StockBill operations</span>
          </div>
        </div>
        <div className="workspace-label">Workspace</div>
        <nav className="primary-nav" aria-label="Primary navigation">
          <NavLink to="/invoices/new" className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
            <span className="nav-symbol">B</span> New invoice
          </NavLink>
          {isAdmin && <NavLink to="/purchases" className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
            <span className="nav-symbol">U</span> Purchases
          </NavLink>}
          <NavLink to="/products" className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
            <span className="nav-symbol">P</span> Products
          </NavLink>
          <NavLink to="/catalogue" className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
            <span className="nav-symbol">K</span> Catalogue
          </NavLink>
          <NavLink to="/customers" className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
            <span className="nav-symbol">C</span> Customers
          </NavLink>
          {isAdmin && <div className="nav-note">Admin controls are enabled for product and customer records.</div>}
        </nav>
        <div className="sidebar-foot">
          <div className="account-block">
            <div className="avatar">{(user?.first_name || user?.username || 'U').slice(0, 1).toUpperCase()}</div>
            <div className="account-copy">
              <strong>{user?.username || user?.first_name}</strong>
              <span>{user?.role === 'admin' ? 'ADMINISTRATOR' : 'STAFF'}</span>
            </div>
          </div>
          <button className="logout-button" onClick={signOut}>Logout</button>
        </div>
      </aside>
      <main className="main-content">
        <Outlet />
      </main>
    </div>
  )
}
