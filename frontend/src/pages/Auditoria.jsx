import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  AlertCircle,
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  ClipboardList,
  Eye,
  FilePlus2,
  FileSearch,
  Landmark,
  LogOut,
  RotateCcw,
  ShieldCheck,
  X
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import api from '../services/api';
import './Auditoria.css';

const FILTROS_INICIALES = {
  usuario: '',
  accion: '',
  entidad: '',
  desde: '',
  hasta: ''
};

const ACCIONES = [
  'CREAR',
  'ACTUALIZAR',
  'ELIMINAR',
  'ACTIVAR',
  'DESACTIVAR',
  'LOGIN_EXITOSO',
  'LOGIN_FALLIDO',
  'LOGOUT',
  'SESION_EXPIRADA_INACTIVIDAD'
];

function fechaLocal(fecha) {
  if (!fecha) return '—';
  const valor = new Date(fecha);
  if (Number.isNaN(valor.getTime())) return String(fecha);

  return new Intl.DateTimeFormat('es-MX', {
    dateStyle: 'medium',
    timeStyle: 'short',
    timeZone: 'America/Mexico_City'
  }).format(valor);
}

function jsonLegible(valor) {
  if (valor === null || valor === undefined || valor === '') {
    return 'Sin información';
  }

  if (typeof valor === 'string') {
    try {
      return JSON.stringify(JSON.parse(valor), null, 2);
    } catch {
      return valor;
    }
  }

  return JSON.stringify(valor, null, 2);
}

function etiquetaAccion(accion) {
  const valor = String(accion || '').toUpperCase();
  return valor.replaceAll('_', ' ');
}

export default function Auditoria() {
  const navigate = useNavigate();
  const { usuario, cerrarSesion } = useAuth();

  const [filtros, setFiltros] = useState(FILTROS_INICIALES);
  const [filtrosAplicados, setFiltrosAplicados] = useState(FILTROS_INICIALES);
  const [eventos, setEventos] = useState([]);
  const [pagina, setPagina] = useState(1);
  const [limite] = useState(10);
  const [total, setTotal] = useState(0);
  const [totalPaginas, setTotalPaginas] = useState(1);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState('');

  const [eventoSeleccionado, setEventoSeleccionado] = useState(null);
  const [cargandoDetalle, setCargandoDetalle] = useState(false);
  const [errorDetalle, setErrorDetalle] = useState('');
  const solicitudDetalle = useRef(0);

  useEffect(() => {
    let vigente = true;

    const cargarEventos = async () => {
      setCargando(true);
      setError('');

      const params = { pagina, limite };
      Object.entries(filtrosAplicados).forEach(([campo, valor]) => {
        if (String(valor ?? '').trim()) {
          params[campo] = String(valor).trim();
        }
      });

      try {
        const respuesta = await api.get('/auditoria', { params });
        const datos = respuesta.data || {};
        const lista = Array.isArray(datos.eventos) ? datos.eventos : [];
        const meta = datos.paginacion || {};
        const cantidad = Number(
          meta.total ?? meta.total_registros ?? datos.total ?? lista.length
        );
        const paginas = Number(
          meta.totalPaginas ??
          meta.total_paginas ??
          meta.paginas ??
          Math.max(1, Math.ceil(cantidad / limite))
        );

        if (!vigente) return;

        setEventos(lista);
        setTotal(Number.isFinite(cantidad) ? cantidad : lista.length);
        setTotalPaginas(Number.isFinite(paginas) && paginas > 0 ? paginas : 1);
      } catch (err) {
        if (!vigente) return;
        console.error('Error al consultar auditoría:', err);
        setEventos([]);
        setTotal(0);
        setTotalPaginas(1);
        setError(
          err.response?.data?.mensaje ||
          'No fue posible consultar la bitácora de auditoría.'
        );
      } finally {
        if (vigente) setCargando(false);
      }
    };

    cargarEventos();

    return () => {
      vigente = false;
    };
  }, [pagina, limite, filtrosAplicados]);

  const rango = useMemo(() => {
    if (eventos.length === 0) return { inicio: 0, fin: 0 };
    return {
      inicio: (pagina - 1) * limite + 1,
      fin: Math.min((pagina - 1) * limite + eventos.length, total)
    };
  }, [eventos.length, pagina, limite, total]);

  const cambiarFiltro = (campo, valor) => {
    setFiltros((actuales) => ({ ...actuales, [campo]: valor }));
  };

  const aplicarFiltros = (e) => {
    e.preventDefault();
    if (filtros.desde && filtros.hasta && filtros.desde > filtros.hasta) {
      setError('La fecha inicial no puede ser posterior a la fecha final.');
      return;
    }
    setPagina(1);
    setFiltrosAplicados({ ...filtros });
  };

  const limpiarFiltros = () => {
    setFiltros(FILTROS_INICIALES);
    setFiltrosAplicados(FILTROS_INICIALES);
    setPagina(1);
    setError('');
  };

  const abrirDetalle = async (id) => {
    const solicitudActual = ++solicitudDetalle.current;
    setEventoSeleccionado(null);
    setErrorDetalle('');
    setCargandoDetalle(true);

    try {
      const respuesta = await api.get(`/auditoria/${id}`);
      if (solicitudActual !== solicitudDetalle.current) return;
      setEventoSeleccionado(respuesta.data?.evento || null);
      if (!respuesta.data?.evento) {
        setErrorDetalle('La API no devolvió el detalle del evento solicitado.');
      }
    } catch (err) {
      if (solicitudActual !== solicitudDetalle.current) return;
      console.error('Error al consultar detalle de auditoría:', err);
      setErrorDetalle(
        err.response?.data?.mensaje ||
        'No fue posible recuperar el detalle de este evento.'
      );
    } finally {
      if (solicitudActual === solicitudDetalle.current) {
        setCargandoDetalle(false);
      }
    }
  };

  const cerrarDetalle = () => {
    solicitudDetalle.current += 1;
    setEventoSeleccionado(null);
    setErrorDetalle('');
    setCargandoDetalle(false);
  };

  return (
    <div className="dashboard auditoria-dashboard">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <Landmark size={29} />
          <div>
            <strong>REGISTRO</strong>
            <span>DE ACTAS</span>
          </div>
        </div>

        <div className="sidebar-section">MENÚ PRINCIPAL</div>

        <nav className="sidebar-nav">
          <button type="button" className="sidebar-item" onClick={() => navigate('/actas')}>
            <FileSearch size={19} />
            <span>Consultar actas</span>
          </button>
          <button type="button" className="sidebar-item" onClick={() => navigate('/actas/nueva')}>
            <FilePlus2 size={19} />
            <span>Nueva captura</span>
          </button>
          <button type="button" className="sidebar-item sidebar-item-active" aria-current="page">
            <ClipboardList size={19} />
            <span>Auditoría</span>
          </button>
        </nav>

        <button type="button" className="logout-button" onClick={cerrarSesion}>
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

        <section className="auditoria-content">
          <div className="auditoria-encabezado">
            <div>
              <span className="section-eyebrow">ADMINISTRACIÓN DEL SISTEMA</span>
              <h1>Bitácora de auditoría</h1>
              <p>Consulta el historial de operaciones realizadas en el sistema.</p>
            </div>
            <div className="auditoria-encabezado-icono" aria-hidden="true">
              <ShieldCheck size={27} />
            </div>
          </div>

          <div className="auditoria-resumen">
            <div className="auditoria-resumen-icono">
              <ClipboardList size={21} />
            </div>
            <div>
              <span>Eventos encontrados</span>
              <strong>{total.toLocaleString('es-MX')}</strong>
            </div>
            <small>Según los filtros aplicados</small>
          </div>

          <form className="auditoria-filtros" onSubmit={aplicarFiltros}>
            <div className="auditoria-filtros-titulo">
              <div>
                <span className="auditoria-titulo-secundario">Filtros de consulta</span>
                <small>Limita los resultados por usuario, acción, entidad o fecha.</small>
              </div>
              <button type="button" className="auditoria-limpiar" onClick={limpiarFiltros}>
                <RotateCcw size={15} />
                Limpiar
              </button>
            </div>

            <div className="auditoria-filtros-grid">
              <label>
                <span>ID de usuario</span>
                <input
                  type="number"
                  min="1"
                  step="1"
                  value={filtros.usuario}
                  onChange={(e) => cambiarFiltro('usuario', e.target.value)}
                  placeholder="Ej. 4"
                />
              </label>

              <label>
                <span>Acción</span>
                <select value={filtros.accion} onChange={(e) => cambiarFiltro('accion', e.target.value)}>
                  <option value="">Todas las acciones</option>
                  {ACCIONES.map((accion) => (
                    <option value={accion} key={accion}>{etiquetaAccion(accion)}</option>
                  ))}
                </select>
              </label>

              <label>
                <span>Entidad</span>
                <input
                  type="text"
                  value={filtros.entidad}
                  onChange={(e) => cambiarFiltro('entidad', e.target.value)}
                  placeholder="Ej. actas"
                  maxLength={60}
                />
              </label>

              <label>
                <span>Desde</span>
                <div className="auditoria-fecha-input">
                  <CalendarDays size={16} />
                  <input type="date" value={filtros.desde} onChange={(e) => cambiarFiltro('desde', e.target.value)} />
                </div>
              </label>

              <label>
                <span>Hasta</span>
                <div className="auditoria-fecha-input">
                  <CalendarDays size={16} />
                  <input type="date" value={filtros.hasta} onChange={(e) => cambiarFiltro('hasta', e.target.value)} />
                </div>
              </label>
            </div>

            <div className="auditoria-filtros-acciones">
              <button type="submit" className="auditoria-boton-principal">
                <FileSearch size={17} />
                Aplicar filtros
              </button>
            </div>
          </form>

          {error && (
            <div className="auditoria-error" role="alert">
              <AlertCircle size={18} />
              <span>{error}</span>
            </div>
          )}

          <div className="auditoria-tabla-encabezado">
            <div>
              <h2>Registro de operaciones</h2>
              <p>
                {cargando
                  ? 'Consultando eventos…'
                  : total === 0
                    ? 'No hay eventos para mostrar.'
                    : `Mostrando ${rango.inicio}–${rango.fin} de ${total} eventos`}
              </p>
            </div>
            <button
              type="button"
              className="auditoria-actualizar"
              onClick={() => setFiltrosAplicados({ ...filtrosAplicados })}
              disabled={cargando}
              title="Actualizar resultados"
            >
              <RotateCcw size={16} />
              Actualizar
            </button>
          </div>

          <div className="auditoria-tabla-contenedor">
            <table className="auditoria-tabla">
              <thead>
                <tr>
                  <th>FECHA Y HORA</th>
                  <th>USUARIO</th>
                  <th>ACCIÓN</th>
                  <th>ENTIDAD</th>
                  <th>ID REGISTRO</th>
                  <th>DETALLE</th>
                </tr>
              </thead>
              <tbody>
                {cargando ? (
                  <tr>
                    <td colSpan="6" className="auditoria-tabla-vacia">Cargando eventos de auditoría…</td>
                  </tr>
                ) : eventos.length === 0 ? (
                  <tr>
                    <td colSpan="6" className="auditoria-tabla-vacia">
                      <ClipboardList size={28} />
                      <strong>Sin resultados</strong>
                      <span>Prueba cambiando o limpiando los filtros.</span>
                    </td>
                  </tr>
                ) : (
                  eventos.map((evento) => (
                    <tr key={evento.id_evento}>
                      <td>
                        <strong>{fechaLocal(evento.fecha_evento)}</strong>
                        <small>Evento #{evento.id_evento}</small>
                      </td>
                      <td>
                        <strong>{evento.nombre_completo || 'Usuario'}</strong>
                        <small>@{evento.usuario || `ID ${evento.id_usuario}`}</small>
                      </td>
                      <td>
                        <span className={`auditoria-accion auditoria-accion-${String(evento.accion || '').toLowerCase()}`}>
                          {etiquetaAccion(evento.accion)}
                        </span>
                      </td>
                      <td>{evento.entidad_afectada || '—'}</td>
                      <td>{evento.id_registro ?? '—'}</td>
                      <td>
                        <button
                          type="button"
                          className="auditoria-ver-detalle"
                          onClick={() => abrirDetalle(evento.id_evento)}
                        >
                          <Eye size={15} />
                          Ver detalle
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          <div className="auditoria-paginacion">
            <span>Página {pagina} de {totalPaginas}</span>
            <div>
              <button
                type="button"
                onClick={() => setPagina((actual) => Math.max(1, actual - 1))}
                disabled={pagina <= 1 || cargando}
              >
                <ChevronLeft size={16} />
                Anterior
              </button>
              <button
                type="button"
                onClick={() => setPagina((actual) => Math.min(totalPaginas, actual + 1))}
                disabled={pagina >= totalPaginas || cargando}
              >
                Siguiente
                <ChevronRight size={16} />
              </button>
            </div>
          </div>

          <div className="auditoria-nota-seguridad">
            <ShieldCheck size={16} />
            Los datos personales del evento solo se muestran al abrir su detalle. Esta sección está reservada al Administrador.
          </div>
        </section>
      </main>

      {(cargandoDetalle || eventoSeleccionado || errorDetalle) && (
        <div className="auditoria-modal-fondo" role="presentation" onMouseDown={(e) => {
          if (e.target === e.currentTarget) cerrarDetalle();
        }}>
          <section className="auditoria-modal" role="dialog" aria-modal="true" aria-labelledby="auditoria-modal-titulo">
            <header className="auditoria-modal-encabezado">
              <div>
                <span className="section-eyebrow">BITÁCORA DEL SISTEMA</span>
                <h2 id="auditoria-modal-titulo">Detalle del evento</h2>
              </div>
              <button type="button" className="auditoria-modal-cerrar" onClick={cerrarDetalle} aria-label="Cerrar detalle">
                <X size={20} />
              </button>
            </header>

            {cargandoDetalle ? (
              <div className="auditoria-modal-estado">Cargando detalle del evento…</div>
            ) : errorDetalle ? (
              <div className="auditoria-error auditoria-error-modal">
                <AlertCircle size={18} />
                <span>{errorDetalle}</span>
              </div>
            ) : eventoSeleccionado && (
              <div className="auditoria-modal-cuerpo">
                <div className="auditoria-detalle-resumen">
                  <div><span>Evento</span><strong>#{eventoSeleccionado.id_evento}</strong></div>
                  <div><span>Fecha y hora</span><strong>{fechaLocal(eventoSeleccionado.fecha_evento)}</strong></div>
                  <div><span>Usuario</span><strong>{eventoSeleccionado.nombre_completo || '—'} (@{eventoSeleccionado.usuario || eventoSeleccionado.id_usuario})</strong></div>
                  <div><span>Acción</span><strong>{etiquetaAccion(eventoSeleccionado.accion)}</strong></div>
                  <div><span>Entidad</span><strong>{eventoSeleccionado.entidad_afectada || '—'}</strong></div>
                  <div><span>ID de registro</span><strong>{eventoSeleccionado.id_registro ?? '—'}</strong></div>
                </div>

                <div className="auditoria-detalle-bloque">
                  <h3>Descripción</h3>
                  <p>{eventoSeleccionado.detalle || 'Sin descripción adicional.'}</p>
                </div>

                <div className="auditoria-detalle-bloque">
                  <h3>Valores anteriores</h3>
                  <pre>{jsonLegible(eventoSeleccionado.valor_anterior)}</pre>
                </div>

                <div className="auditoria-detalle-bloque">
                  <h3>Valores nuevos</h3>
                  <pre>{jsonLegible(eventoSeleccionado.valor_nuevo)}</pre>
                </div>

                <p className="auditoria-aviso-privacidad">
                  Este detalle puede contener datos personales del acta. Consulta la información únicamente cuando sea necesario para verificar una operación.
                </p>
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
