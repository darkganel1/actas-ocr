
import {
  FileSearch,
  FilePlus2,
  Users,
  ClipboardList,
  LogOut,
  Landmark
} from 'lucide-react';

import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

const Dashboard = () => {
  const {
    usuario,
    cerrarSesion,
    tienePermiso
  } = useAuth();

  const navigate = useNavigate();

  const opciones = [
    {
      titulo: 'Consultar actas',
      descripcion: 'Buscar y consultar expedientes registrados.',
      icono: FileSearch,
      permiso: 'actas.consultar',
      ruta: '/actas'
    },
    {
      titulo: 'Nueva captura',
      descripcion: 'Procesar documentos y revisar datos mediante OCR.',
      icono: FilePlus2,
      permiso: 'actas.capturar',
      ruta: '/actas/nueva'
    },
    {
      titulo: 'Usuarios',
      descripcion: 'Administrar cuentas y accesos al sistema.',
      icono: Users,
      administrador: true,
      ruta: '/usuarios'
    },
    {
      titulo: 'Auditoría',
      descripcion: 'Consultar el historial de operaciones.',
      icono: ClipboardList,
      administrador: true,
      ruta: '/auditoria'
    }
  ];

  const opcionVisible = (opcion) => {
    return opcion.administrador
      ? usuario?.rol === 'Administrador'
      : tienePermiso(opcion.permiso);
  };

  const navegar = (ruta) => {
    navigate(ruta);
  };

  return (
    <div className="dashboard">

      <aside className="sidebar">

        <div className="sidebar-brand">
          <Landmark size={29} />
          <div>
            <strong>REGISTRO</strong>
            <span>DE ACTAS</span>
          </div>
        </div>

        <div className="sidebar-section">
          MENÚ PRINCIPAL
        </div>

        <nav className="sidebar-nav">
          {opciones.filter(opcionVisible).map((opcion) => {
            const Icono = opcion.icono;

            return (
              <button
                type="button"
                className="sidebar-item"
                key={opcion.titulo}
                onClick={() => navegar(opcion.ruta)}
              >
                <Icono size={19} />
                <span>{opcion.titulo}</span>
              </button>
            );
          })}
        </nav>

        <button
          className="logout-button"
          onClick={cerrarSesion}
        >
          <LogOut size={19} />
          Cerrar sesión
        </button>

      </aside>

      <main className="dashboard-main">

        <header className="topbar">
          <span>Sistema de Gestión Documental</span>

          <button
  type="button"
  className="user-info mi-cuenta-trigger"
  onClick={() => navigate('/mi-cuenta')}
  title="Abrir mi cuenta"
  aria-label="Abrir mi cuenta y cambiar contraseña"
>
  <div className="user-avatar">
    {usuario?.nombre_completo?.charAt(0) || 'U'}
  </div>

  <div>
    <strong>{usuario?.nombre_completo}</strong>
    <small>{usuario?.rol}</small>
  </div>
</button>
        </header>

        <section className="dashboard-content">

          <span className="section-eyebrow">
            PANEL DE CONTROL
          </span>

          <h1>Bienvenido al sistema</h1>

          <p className="dashboard-subtitle">
            Selecciona una de las opciones disponibles para comenzar.
          </p>

          <div className="dashboard-grid">

            {opciones.filter(opcionVisible).map((opcion) => {
              const Icono = opcion.icono;

              return (
                <button
                  type="button"
                  className="dashboard-card"
                  key={opcion.titulo}
                  onClick={() => navegar(opcion.ruta)}
                >
                  <div className="dashboard-card-icon">
                    <Icono size={25} />
                  </div>

                  <h2>{opcion.titulo}</h2>

                  <p>{opcion.descripcion}</p>

                  <span className="card-accent" />
                </button>
              );
            })}

          </div>
        </section>

      </main>
    </div>
  );
};

export default Dashboard;
