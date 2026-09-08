import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import AppShell from './components/AppShell'
import ProtectedRoute from './components/ProtectedRoute'
import { AuthProvider } from './context/AuthContext'
import CustomersPage from './pages/CustomersPage'
import InvoiceDetailPage from './pages/InvoiceDetailPage'
import NewInvoicePage from './pages/NewInvoicePage'
import LoginPage from './pages/LoginPage'
import ProductsPage from './pages/ProductsPage'
import './App.css'

function App() {
  return <AuthProvider><BrowserRouter><Routes>
    <Route path="/login" element={<LoginPage />} />
    <Route element={<ProtectedRoute />}><Route element={<AppShell />}>
      <Route path="/products" element={<ProductsPage />} />
      <Route path="/customers" element={<CustomersPage />} />
      <Route path="/invoices/new" element={<NewInvoicePage />} />
      <Route path="/invoices/:id" element={<InvoiceDetailPage />} />
      <Route path="*" element={<Navigate to="/products" replace />} />
    </Route></Route>
  </Routes></BrowserRouter></AuthProvider>
}

export default App
