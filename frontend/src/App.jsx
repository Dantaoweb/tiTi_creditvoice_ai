import { Navigate, Routes, Route } from "react-router-dom";
import { ToastProvider } from "./components/Toast";
import { useAuth } from "./context/AuthContext";
import InstallPrompt from "./components/InstallPrompt";
import Layout       from "./components/Layout";
import Landing      from "./pages/Landing";
import Login        from "./pages/Login";
import Chat         from "./pages/Chat";
import Dashboard    from "./pages/Dashboard";
import Customers    from "./pages/Customers";
import Transactions from "./pages/Transactions";
import Inventory    from "./pages/Inventory";
import Suppliers    from "./pages/Suppliers";
import Staff        from "./pages/Staff";
import Partners     from "./pages/Partners";
import Notes        from "./pages/Notes";
import Admin        from "./pages/Admin";
import Reminders    from "./pages/Reminders";
import Automation   from "./pages/Automation"
import Branches     from "./pages/Branches";
import Capture      from "./pages/Capture";
import POS          from "./pages/POS";
import Receipt      from "./pages/Receipt";
import Receipts     from "./pages/Receipts";
import Invoices     from "./pages/Invoices";
import Deliveries   from "./pages/Deliveries";
import Wallet       from "./pages/Wallet";
import Thrift        from "./pages/Thrift";
import Opportunities from "./pages/Opportunities";
import Terms        from "./pages/Terms";
import Privacy      from "./pages/Privacy";
import Upgrade      from "./pages/Upgrade";

function RequireAuth({ children }) {
  const { isAuthed } = useAuth();
  return isAuthed ? children : <Navigate to="/login" replace />;
}

export default function App() {
  return (
    <ToastProvider>
      <InstallPrompt />
      <Routes>
        {/* Public */}
        <Route index element={<Landing />} />
        <Route path="login" element={<Login />} />
        <Route path="terms" element={<Terms />} />
        <Route path="privacy" element={<Privacy />} />

        {/* Authenticated — all inside sidebar Layout */}
        <Route
          element={
            <RequireAuth>
              <Layout />
            </RequireAuth>
          }
        >
          <Route path="home"         element={<Chat />}         />
          <Route path="dashboard"    element={<Dashboard />}    />
          <Route path="capture"      element={<Capture />}      />
          <Route path="pos"          element={<POS />}          />
          <Route path="pos/receipt/:id" element={<Receipt />}   />
          <Route path="receipts"     element={<Receipts />}     />
          <Route path="invoices"     element={<Invoices />}     />
          <Route path="deliveries"   element={<Deliveries />}   />
          <Route path="customers"    element={<Customers />}    />
          <Route path="transactions" element={<Transactions />} />
          <Route path="inventory"    element={<Inventory />}    />
          <Route path="suppliers"    element={<Suppliers />}    />
          <Route path="staff"        element={<Staff />}        />
          <Route path="partners"     element={<Partners />}     />
          <Route path="notes"        element={<Notes />}        />
          <Route path="reminders"    element={<Reminders />}    />
          <Route path="wallet"       element={<Wallet />}       />
          <Route path="thrift"       element={<Thrift />}       />
          <Route path="branches"     element={<Branches />}     />
          <Route path="automation"     element={<Automation />}     />
          <Route path="opportunities" element={<Opportunities />} />
          <Route path="admin"        element={<Admin />}          />
          <Route path="upgrade"      element={<Upgrade />}        />
        </Route>

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </ToastProvider>
  );
}
