
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Search,
  FileSearch,
  Eye,
  ChevronLeft,
  ChevronRight,
  RefreshCw,
  ArrowLeft,
  Landmark,
  LogOut
} from 'lucide-react';

import { useAuth } from '../context/AuthContext';
import api from '../services/api';

const Actas = () => {
  const navigate = useNavigate();
  const { usuario, cerrarSesion } = useAuth();

  const [actas, setActas] = useState([]);
  const [busqueda, setBusqueda] = useState('');
  const [pagina, setPagina] = useState(1);
  const [paginacion, setPaginacion] = useState({
    pagina: 1,
    limite: 10,
    total: 0,
    totalPaginas: 0
  });

  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState('');

  const consultarActas = async (paginaActual = pagina, termino = busqueda) => {
    setCargando(true);
    setError('');

    try {
      const respuesta = await api.get('/actas', {
        params: {
          busqueda: termino,
          pagina: paginaActual,
          limite: 10
        }
      });

      setActas(respuesta.data.actas || []);
      setPaginacion(respuesta.data.paginacion);

    } catch (err) {
      setError(
        err.response?.data?.mensaje ||
        'No fue posible consultar las actas.'
      );

    } finally {
      setCargando(false);
    }
  };

  // Consultar cuando cambia la página o la búsqueda.
  useEffect(() => {
    const temporizador = setTimeout(() => {
      consultarActas(pagina, busqueda);
    }, busqueda ? 400 : 0);

    return () => clearTimeout(temporizador);
  }, [pagina, busqueda]);

  const cambiarBusqueda = (valor) => {
    setBusqueda(valor);
    setPagina(1);
  };

  const formatearFecha = (fecha) => {
    if (!fecha) return '—';

    const valor = String(fecha).substring(0, 10);
    const partes = valor.split('-');

    if (partes.length !== 3) return valor;

    return `${partes[2]}/${partes[1]}/${partes[0]}`;
  };

  const nombreCompleto = (acta) => {
    return [
      acta.nombres,
      acta.primer_apellido,
      acta.segundo_apellido
    ].filter(Boolean).join(' ');
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

          <button
            className="sidebar-item"
            onClick={() => navigate('/inicio')}
          >
            <ArrowLeft size={19} />
            <span>Panel principal</span>
          </button>

          <button className="sidebar-item sidebar-item-active">
            <FileSearch size={19} />
            <span>Consultar actas</span>
          </button>

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

          <div className="user-info">
            <div className="user-avatar">
              {usuario?.nombre_completo?.charAt(0) || 'U'}
            </div>

            <div>
              <strong>{usuario?.nombre_completo}</strong>
              <small>{usuario?.rol}</small>
            </div>
          </div>
        </header>

        <section className="dashboard-content">

          <span className="section-eyebrow">
            GESTIÓN DOCUMENTAL
          </span>

          <h1>Consulta de actas</h1>

          <p className="dashboard-subtitle">
            Busca y consulta los expedientes registrados en el sistema.
          </p>

          <div className="actas-toolbar">

            <div className="actas-search">
              <Search size={19} />

              <input
                type="text"
                placeholder="Buscar por nombre, CURP, identificador o número de acta..."
                value={busqueda}
                onChange={(e) => cambiarBusqueda(e.target.value)}
              />

              {busqueda && (
                <button
                  type="button"
                  onClick={() => cambiarBusqueda('')}
                  title="Limpiar búsqueda"
                >
                  ×
                </button>
              )}
            </div>

            <button
              className="actas-refresh"
              onClick={() => consultarActas(pagina, busqueda)}
              disabled={cargando}
              title="Actualizar listado"
            >
              <RefreshCw size={18} />
            </button>

          </div>

          <div className="actas-summary">
            <div>
              <FileSearch size={20} />
              <span>
                {paginacion.total} expediente(s) encontrado(s)
              </span>
            </div>
          </div>

          {error && (
            <div className="actas-error">
              {error}
            </div>
          )}

          <div className="actas-table-container">

            <table className="actas-table">

              <thead>
                <tr>
                  <th>EXPEDIENTE</th>
                  <th>NOMBRE COMPLETO</th>
                  <th>FECHA NACIMIENTO</th>
                  <th>OFICIALÍA</th>
                  <th>NÚMERO ACTA</th>
                  <th>CAPTURISTA</th>
                  <th>ACCIÓN</th>
                </tr>
              </thead>

              <tbody>

                {cargando ? (
                  <tr>
                    <td colSpan="7" className="actas-empty">
                      Consultando expedientes...
                    </td>
                  </tr>

                ) : error ? (
                  <tr>
                    <td colSpan="7" className="actas-empty">
                      No se pudo cargar el listado.
                    </td>
                  </tr>

                ) : actas.length === 0 ? (
                  <tr>
                    <td colSpan="7" className="actas-empty">
                      <FileSearch size={30} />
                      <strong>No se encontraron actas</strong>
                      <span>Prueba con otro término de búsqueda.</span>
                    </td>
                  </tr>

                ) : (
                  actas.map((acta) => (
                    <tr key={acta.id_acta}>

                      <td>
                        <strong>#{acta.id_acta}</strong>
                      </td>

                      <td>
                        <strong>{nombreCompleto(acta)}</strong>
                        <small>
                          {acta.curp || 'CURP no registrada'}
                        </small>
                      </td>

                      <td>
                        {formatearFecha(acta.fecha_nacimiento)}
                      </td>

                      <td>{acta.oficialia}</td>

                      <td>{acta.numero_acta}</td>

                      <td>{acta.usuario_captura}</td>

                      <td>
                        <button
                          className="actas-view-button"
                          onClick={() => navigate(`/actas/${acta.id_acta}`)}
                          title="Consultar expediente"
                        >
                          <Eye size={17} />
                          Ver
                        </button>
                      </td>

                    </tr>
                  ))
                )}

              </tbody>
            </table>

          </div>

          <div className="actas-pagination">

            <span>
              Página {paginacion.pagina || 1} de {paginacion.totalPaginas || 1}
            </span>

            <div>

              <button
                disabled={pagina <= 1 || cargando}
                onClick={() => setPagina(p => p - 1)}
              >
                <ChevronLeft size={18} />
                Anterior
              </button>

              <button
                disabled={
                  pagina >= paginacion.totalPaginas || cargando
                }
                onClick={() => setPagina(p => p + 1)}
              >
                Siguiente
                <ChevronRight size={18} />
              </button>

            </div>

          </div>

        </section>

      </main>

    </div>
  );
};

export default Actas;
