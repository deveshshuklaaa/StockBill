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
        <nav className="primary-nav" aria-label="Primary navigation">
          <div className="workspace-label">Overview</div>
          <NavLink to="/dashboard" className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
            <span className="nav-symbol">D</span> Dashboard
          </NavLink>
          <div className="workspace-label">Operations</div>
          <NavLink to="/invoices/new" className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
            <span className="nav-symbol">B</span> New invoice
          </NavLink>
          <NavLink to="/invoices" className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
            <span className="nav-symbol">S</span> Invoices
          </NavLink>
          <NavLink to="/inventory" className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
            <span className="nav-symbol">I</span> Inventory
          </NavLink>
          {isAdmin && <NavLink to="/purchases" className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
            <span className="nav-symbol">U</span> Purchases
          </NavLink>}
          {isAdmin && <NavLink to="/suppliers" className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
            <span className="nav-symbol">V</span> Suppliers
          </NavLink>}
          <div className="workspace-label">Reports</div>
          <NavLink to="/reports/sales" className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
            <span className="nav-symbol">R</span> Sales
          </NavLink>
          <NavLink to="/reports/products" className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
            <span className="nav-symbol">M</span> Product Sales
          </NavLink>
          {isAdmin && <NavLink to="/reports/purchases" className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
            <span className="nav-symbol">N</span> Purchases
          </NavLink>}
          <NavLink to="/reports/inventory" className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
            <span className="nav-symbol">E</span> Stock Valuation
          </NavLink>
          <NavLink to="/reports/stock-movement" className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
            <span className="nav-symbol">L</span> Stock Movement
          </NavLink>
          <NavLink to="/reports/top-products" className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
            <span className="nav-symbol">Q</span> Top Products
          </NavLink>
          {isAdmin && <>
            <NavLink to="/reports/customers" className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
              <span className="nav-symbol">X</span> Customer Sales
            </NavLink>
            <NavLink to="/reports/tax" className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
              <span className="nav-symbol">Z</span> GST Summary
            </NavLink>
            <NavLink to="/reports/profit" className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
              <span className="nav-symbol">F</span> Profit
            </NavLink>
          </>}
          <div className="workspace-label">Catalogue</div>
          <NavLink to="/products" className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
            <span className="nav-symbol">P</span> Products
          </NavLink>
          <NavLink to="/catalogue" className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
            <span className="nav-symbol">K</span> Catalogue
          </NavLink>
          <NavLink to="/customers" className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
            <span className="nav-symbol">C</span> Customers
          </NavLink>
          {isAdmin && <>
            <div className="workspace-label">Configuration</div>
            <NavLink to="/warehouses" className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
              <span className="nav-symbol">W</span> Warehouses
            </NavLink>
            <NavLink to="/settings/business" className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
              <span className="nav-symbol">G</span> Business Profile
            </NavLink>
            <NavLink to="/settings/taxes" className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
              <span className="nav-symbol">T</span> Taxes
            </NavLink>
            <div className="workspace-label">Administration</div>
            <NavLink to="/audit-logs" className={({ isActive }) => isActive ? 'nav-item active' : 'nav-item'}>
              <span className="nav-symbol">A</span> Audit Logs
            </NavLink>
          </>}
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
