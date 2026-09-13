import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import AppShell from './components/AppShell'
import ProtectedRoute from './components/ProtectedRoute'
import { AuthProvider } from './context/AuthContext'
import AuditLogsPage from './pages/AuditLogsPage'
import BusinessProfilePage from './pages/BusinessProfilePage'
import CataloguePage from './pages/CataloguePage'
import CustomerDetailPage from './pages/CustomerDetailPage'
import CustomersPage from './pages/CustomersPage'
import DashboardPage from './pages/DashboardPage'
import EditProductPage from './pages/EditProductPage'
import InventoryPage from './pages/InventoryPage'
import InvoiceDetailPage from './pages/InvoiceDetailPage'
import InvoicesPage from './pages/InvoicesPage'
import NewInvoicePage from './pages/NewInvoicePage'
import LoginPage from './pages/LoginPage'
import NewPurchasePage from './pages/NewPurchasePage'
import ProductSalesReportPage from './pages/reports/ProductSalesReportPage'
import ProductsPage from './pages/ProductsPage'
import ProductStockDetailPage from './pages/ProductStockDetailPage'
import ProfitReportPage from './pages/reports/ProfitReportPage'
import PurchaseDetailPage from './pages/PurchaseDetailPage'
import PurchasesPage from './pages/PurchasesPage'
import PurchaseReportPage from './pages/reports/PurchaseReportPage'
import CustomerSalesReportPage from './pages/reports/CustomerSalesReportPage'
import SalesReportPage from './pages/reports/SalesReportPage'
import StockLedgerPage from './pages/StockLedgerPage'
import StockMovementReportPage from './pages/reports/StockMovementReportPage'
import SupplierDetailPage from './pages/SupplierDetailPage'
import SuppliersPage from './pages/SuppliersPage'
import TaxConfigurationPage from './pages/TaxConfigurationPage'
import TaxReportPage from './pages/reports/TaxReportPage'
import TopProductsReportPage from './pages/reports/TopProductsReportPage'
import WarehousesPage from './pages/WarehousesPage'
import InventoryReportPage from './pages/reports/InventoryReportPage'
import './App.css'

function App() {
  return <AuthProvider><BrowserRouter><Routes>
    <Route path="/login" element={<LoginPage />} />
    <Route element={<ProtectedRoute />}><Route element={<AppShell />}>
      <Route path="/" element={<Navigate to="/dashboard" replace />} />
      <Route path="/dashboard" element={<DashboardPage />} />
      <Route path="/reports/sales" element={<SalesReportPage />} />
      <Route path="/reports/purchases" element={<PurchaseReportPage />} />
      <Route path="/reports/inventory" element={<InventoryReportPage />} />
      <Route path="/reports/stock-movement" element={<StockMovementReportPage />} />
      <Route path="/reports/products" element={<ProductSalesReportPage />} />
      <Route path="/reports/customers" element={<CustomerSalesReportPage />} />
      <Route path="/reports/tax" element={<TaxReportPage />} />
      <Route path="/reports/profit" element={<ProfitReportPage />} />
      <Route path="/reports/top-products" element={<TopProductsReportPage />} />
      <Route path="/products" element={<ProductsPage />} />
      <Route path="/products/:id/edit" element={<EditProductPage />} />
      <Route path="/catalogue" element={<CataloguePage />} />
      <Route path="/customers" element={<CustomersPage />} />
      <Route path="/customers/:id" element={<CustomerDetailPage />} />
      <Route path="/inventory" element={<InventoryPage />} />
      <Route path="/inventory/:productId" element={<ProductStockDetailPage />} />
      <Route path="/stock-ledger" element={<StockLedgerPage />} />
      <Route path="/purchases" element={<PurchasesPage />} />
      <Route path="/purchases/new" element={<NewPurchasePage />} />
      <Route path="/purchases/:id" element={<PurchaseDetailPage />} />
      <Route path="/suppliers" element={<SuppliersPage />} />
      <Route path="/suppliers/:id" element={<SupplierDetailPage />} />
      <Route path="/warehouses" element={<WarehousesPage />} />
      <Route path="/settings/business" element={<BusinessProfilePage />} />
      <Route path="/settings/taxes" element={<TaxConfigurationPage />} />
      <Route path="/audit-logs" element={<AuditLogsPage />} />
      <Route path="/invoices" element={<InvoicesPage />} />
      <Route path="/invoices/new" element={<NewInvoicePage />} />
      <Route path="/invoices/:id" element={<InvoiceDetailPage />} />
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Route></Route>
  </Routes></BrowserRouter></AuthProvider>
}

export default App
