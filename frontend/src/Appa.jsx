import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';

import { AuthProvider, useAuth } from './context/AuthContext';
import Login from './pages/Login';
import Dashboard from './pages/Dashboard';
import Actas from './pages/Actas';
import DetalleActa from './pages/DetalleActa';
import NuevaActa from './pages/NuevaActa';
import Usuarios from './pages/Usuarios';
import './App.css';

function RutaProtegida({ children }) {
  const { autenticado, cargando } = useAuth();

  if (cargando) {
    return <div>Verificando sesión...</div>;
  }

  return autenticado
    ? children
    : <Navigate to="/login" replace />;
}

const Rutas = () => {
  const { autenticado } = useAuth();

  return (
    <Routes>
      <Route
        path="/login"
        element={
          autenticado
            ? <Navigate to="/inicio" replace />
            : <Login />
        }
      />

      <Route
        path="/inicio"
        element={
          <RutaProtegida>
            <Dashboard />
          </RutaProtegida>
        }
      />
      <Route
  path="/actas"
  element={
    <RutaProtegida>
      <Actas />
    </RutaProtegida>
  }
/>
<Route
  path="/actas/nueva"
  element={
    <RutaProtegida>
      <NuevaActa />
    </RutaProtegida>
  }
/>
<Route
  path="/actas/:id"
  element={
    <RutaProtegida>
      <DetalleActa />
    </RutaProtegida>
  }
/>
<Route
  path="/usuarios"
  element={
    <RutaProtegida>
      <Usuarios />
    </RutaProtegida>
  }
/>

      <Route
        path="*"
        element={<Navigate to={autenticado ? '/inicio' : '/login'} replace />}
      />
    </Routes>
  );
};

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Rutas />
      </BrowserRouter>
    </AuthProvider>
  );
}

export default App;