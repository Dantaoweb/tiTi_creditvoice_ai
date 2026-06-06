import { Navigate, Routes, Route } from "react-router-dom";
import { ToastProvider } from "./components/Toast";
import { useAuth } from "./context/AuthContext";
import Layout       from "./components/Layout";
import Login        from "./pages/Login";
import Dashboard    from "./pages/Dashboard";
import Capture      from "./pages/Capture";
import Customers    from "./pages/Customers";
import Transactions from "./pages/Transactions";
import Inventory    from "./pages/Inventory";
import Suppliers    from "./pages/Suppliers";
import Staff        from "./pages/Staff";
import Reminders    from "./pages/Reminders";
import POS          from "./pages/POS";
import Receipt      from "./pages/Receipt";

function RequireAuth({ children }) {
  const { isAuthed } = useAuth();
  return isAuthed ? children : <Navigate to="/login" replace />;
}

export default function App() {
  return (
    <ToastProvider>
      <Routes>
        <Route path="login" element={<Login />} />
        <Route
          element={
            <RequireAuth>
              <Layout />
            </RequireAuth>
          }
        >
          <Route index                          element={<Dashboard />}    />
          <Route path="capture"                 element={<Capture />}      />
          <Route path="pos"                     element={<POS />}          />
          <Route path="pos/receipt/:id"         element={<Receipt />}      />
          <Route path="customers"               element={<Customers />}    />
          <Route path="transactions"            element={<Transactions />} />
          <Route path="inventory"               element={<Inventory />}    />
          <Route path="suppliers"               element={<Suppliers />}    />
          <Route path="staff"                   element={<Staff />}        />
          <Route path="reminders"               element={<Reminders />}    />
        </Route>
      </Routes>
    </ToastProvider>
  );
}
