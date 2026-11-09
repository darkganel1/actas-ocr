import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import {
  ArrowLeft,
  FileText,
  User,
  Users,
  Landmark,
  CalendarDays,
  MapPin,
  RefreshCw,
  AlertCircle,
  Pencil,
  Trash2,
  LoaderCircle
} from 'lucide-react';

import { useAuth } from '../context/AuthContext';
import api from '../services/api';
import './ActasAdmin.css';

// Comparte la misma carga mientras está en curso. Evita doble consulta y doble
// auditoría cuando React.StrictMode vuelve a montar el efecto en desarrollo.
const solicitudesExpediente = new Map();

function obtenerDatosExpediente(id) {
  if (solicitudesExpediente.has(id)) return solicitudesExpediente.get(id);

  const solicitud = Promise.all([
    api.get(`/actas/${id}`),
    api.get(`/actas/${id}/documento`, { responseType: 'blob' })
  ]);

  solicitudesExpediente.set(id, solicitud);
  solicitud.then(
    () => {
      if (solicitudesExpediente.get(id) === solicitud) solicitudesExpediente.delete(id);
    },
    () => {
      if (solicitudesExpediente.get(id) === solicitud) solicitudesExpediente.delete(id);
    }
  );

  return solicitud;
}

const DetalleActa = () => {
  const { id } = useParams();
  const navigate = useNavigate();
  const { usuario, cerrarSesion } = useAuth();

  const [acta, setActa] = useState(null);
  const [pdfUrl, setPdfUrl] = useState('');
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState('');
  const [errorAccion, setErrorAccion] = useState('');
  const [eliminando, setEliminando] = useState(false);
  const [confirmarEliminacion, setConfirmarEliminacion] = useState(false);

  useEffect(() => {
    let activo = true;
    let urlTemporal = '';

    const cargarExpediente = async () => {
      setCargando(true);
      setError('');

      try {
        const [respuestaActa, respuestaPDF] = await obtenerDatosExpediente(id);

        if (!respuestaActa.data.success) {
          throw new Error('No fue posible recuperar el expediente.');
        }

        const archivoPDF = new Blob(
          [respuestaPDF.data],
          { type: 'application/pdf' }
        );

        urlTemporal = URL.createObjectURL(archivoPDF);

        if (activo) {
          setActa(respuestaActa.data.acta);
          setPdfUrl(urlTemporal);
        } else {
          URL.revokeObjectURL(urlTemporal);
        }

      } catch (err) {
        if (activo) {
          setError(
            err.response?.data?.mensaje ||
            'No fue posible cargar el expediente o su documento PDF.'
          );
        }

      } finally {
        if (activo) {
          setCargando(false);
        }
      }
    };

    cargarExpediente();

    return () => {
      activo = false;

      if (urlTemporal) {
        URL.revokeObjectURL(urlTemporal);
      }
    };
  }, [id]);

  const eliminarActa = async () => {
    setEliminando(true);
    setErrorAccion('');

    try {
      const respuesta = await api.delete(`/actas/${id}`);
      if (!respuesta.data?.success) {
        throw new Error(respuesta.data?.mensaje || 'No fue posible eliminar el acta.');
      }

      if (respuesta.data?.pdf_eliminado_fisicamente === false) {
        setConfirmarEliminacion(false);
        setErrorAccion(
          respuesta.data?.advertencia ||
          'El acta fue eliminada, pero el PDF requiere una purga manual.'
        );
        navigate('/actas', { replace: true, state: { avisoEliminacion: respuesta.data?.advertencia } });
        return;
      }

      navigate('/actas', {
        replace: true,
        state: { avisoEliminacion: respuesta.data?.mensaje }
      });
    } catch (err) {
      const status = err.response?.status;
      const mensajeServidor =
        err.response?.data?.mensaje ||
        err.response?.data?.message;

      setErrorAccion(
        mensajeServidor ||
        (status === 404
          ? 'La ruta administrativa no está registrada en el backend. Verifica el montaje de actas-admin.routes.js en app.js.'
          : err.message || 'No fue posible eliminar el acta.')
      );
    } finally {
      setEliminando(false);
      setConfirmarEliminacion(false);
    }
  };

  const mostrar = (valor) => {
    return valor === null || valor === undefined || valor === ''
      ? 'No registrado'
      : String(valor);
  };

  const fecha = (valor) => {
    if (!valor) return 'No registrada';

    const partes = String(valor).substring(0, 10).split('-');

    if (partes.length !== 3) return valor;

    return `${partes[2]}/${partes[1]}/${partes[0]}`;
  };

  const nombreCompleto = (persona, primerApellido, segundoApellido) => {
    return [
      persona,
      primerApellido,
      segundoApellido
    ].filter(Boolean).join(' ') || 'No registrado';
  };

  const inicial = usuario?.nombre_completo?.charAt(0) || 'U';

  if (cargando) {
    return (
      <div className="detalle-loading">
        <RefreshCw size={25} className="detalle-spinner" />
        <p>Cargando expediente...</p>
      </div>
    );
  }

  if (error || !acta) {
    return (
      <div className="detalle-error-page">
        <AlertCircle size={35} />
        <h2>No fue posible abrir el expediente</h2>
        <p>{error || 'El expediente solicitado no estÃ¡ disponible.'}</p>

        <button onClick={() => navigate('/actas')}>
          <ArrowLeft size={17} />
          Regresar al listado
        </button>
      </div>
    );
  }

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
          MENÃš PRINCIPAL
        </div>

        <nav className="sidebar-nav">
          <button
            className="sidebar-item"
            onClick={() => navigate('/inicio')}
          >
            <ArrowLeft size={19} />
            <span>Panel principal</span>
          </button>

          <button
            className="sidebar-item sidebar-item-active"
            onClick={() => navigate('/actas')}
          >
            <FileText size={19} />
            <span>Consultar actas</span>
          </button>
        </nav>

        <button className="logout-button" onClick={cerrarSesion}>
          <ArrowLeft size={19} />
          Cerrar sesiÃ³n
        </button>
      </aside>

      <main className="dashboard-main">

        <header className="topbar">
          <span>Sistema de GestiÃ³n Documental</span>

          <div className="user-info">
            <div className="user-avatar">{inicial}</div>
            <div>
              <strong>{usuario?.nombre_completo}</strong>
              <small>{usuario?.rol}</small>
            </div>
          </div>
        </header>

        <section className="detalle-content">

          <div className="detalle-heading">
            <div>
              <span className="section-eyebrow">
                GESTIÃ“N DOCUMENTAL / EXPEDIENTE
              </span>



              <p>
                Consulta de informaciÃ³n registral y documento original.
              </p>
            </div>

            <div className="detalle-admin-actions">
              {usuario?.rol === 'Administrador' && (
                <>
                  <button
                    type="button"
                    className="detalle-admin-edit-button"
                    onClick={() => navigate(`/actas/${id}/editar`)}
                  >
                    <Pencil size={16} />
                    Editar acta
                  </button>
                  <button
                    type="button"
                    className="detalle-admin-delete-button"
                    onClick={() => setConfirmarEliminacion(true)}
                    disabled={eliminando}
                  >
                    {eliminando ? <LoaderCircle size={16} className="detalle-admin-spinner" /> : <Trash2 size={16} />}
                    {eliminando ? 'Eliminando…' : 'Eliminar acta'}
                  </button>
                </>
              )}
              <button
                type="button"
                className="detalle-back-button"
                onClick={() => navigate('/actas')}
              >
                <ArrowLeft size={17} />
                Regresar
              </button>
            </div>
          </div>

          {errorAccion && (
            <div className="detalle-admin-error" role="alert">
              <AlertCircle size={17} />
              <span>{errorAccion}</span>
            </div>
          )}

          <div className="detalle-layout">

            <div className="detalle-information">

              <article className="detalle-panel">
                <div className="detalle-panel-title">
                  <Landmark size={19} />
                  <h2>Datos registrales</h2>
                </div>

                <div className="detalle-fields">
                  <div>
                    <label>Entidad</label>
                    <span>{mostrar(acta.entidad)}</span>
                  </div>

                  <div>
                    <label>Municipio</label>
                    <span>{mostrar(acta.municipio)}</span>
                  </div>

                  <div>
                    <label>OficialÃ­a</label>
                    <span>{mostrar(acta.oficialia)}</span>
                  </div>

                  <div>
                    <label>Fecha de registro</label>
                    <span>{fecha(acta.fecha_registro)}</span>
                  </div>

                  <div>
                    <label>Libro</label>
                    <span>{mostrar(acta.libro)}</span>
                  </div>

                  <div>
                    <label>NÃºmero de acta</label>
                    <span>{mostrar(acta.numero_acta)}</span>
                  </div>

                  <div>
                    <label>Folio</label>
                    <span>{mostrar(acta.folio)}</span>
                  </div>
                </div>
              </article>

              <article className="detalle-panel">
                <div className="detalle-panel-title">
                  <User size={19} />
                  <h2>Datos de la persona registrada</h2>
                </div>

                <div className="detalle-fields">
                  <div className="detalle-field-full">
                    <label>Nombre completo</label>
                    <span>
                      {nombreCompleto(
                        acta.nombres,
                        acta.primer_apellido,
                        acta.segundo_apellido
                      )}
                    </span>
                  </div>

                  <div>
                    <label>Fecha de nacimiento</label>
                    <span>{fecha(acta.fecha_nacimiento)}</span>
                  </div>

                  <div>
                    <label>Sexo</label>
                    <span>{mostrar(acta.sexo)}</span>
                  </div>

                  <div>
                    <label>Lugar de nacimiento</label>
                    <span>{mostrar(acta.lugar_nacimiento)}</span>
                  </div>

                  <div>
                    <label>Nacionalidad</label>
                    <span>{mostrar(acta.nacionalidad)}</span>
                  </div>

                  <div className="detalle-field-full">
                    <label>CURP</label>
                    <span>{mostrar(acta.curp)}</span>
                  </div>
                </div>
              </article>

              <article className="detalle-panel">
                <div className="detalle-panel-title">
                  <Users size={19} />
                  <h2>Datos de los padres</h2>
                </div>

                <div className="detalle-parent">
                  <h3>Padre</h3>

                  <div className="detalle-fields">
                    <div className="detalle-field-full">
                      <label>Nombre completo</label>
                      <span>
                        {nombreCompleto(
                          acta.nombre_padre,
                          acta.primer_apellido_padre,
                          acta.segundo_apellido_padre
                        )}
                      </span>
                    </div>

                    <div>
                      <label>CURP</label>
                      <span>{mostrar(acta.curp_padre)}</span>
                    </div>

                    <div>
                      <label>Nacionalidad</label>
                      <span>{mostrar(acta.nacionalidad_padre)}</span>
                    </div>
                  </div>
                </div>

                <div className="detalle-parent">
                  <h3>Madre</h3>

                  <div className="detalle-fields">
                    <div className="detalle-field-full">
                      <label>Nombre completo</label>
                      <span>
                        {nombreCompleto(
                          acta.nombre_madre,
                          acta.primer_apellido_madre,
                          acta.segundo_apellido_madre
                        )}
                      </span>
                    </div>

                    <div>
                      <label>CURP</label>
                      <span>{mostrar(acta.curp_madre)}</span>
                    </div>

                    <div>
                      <label>Nacionalidad</label>
                      <span>{mostrar(acta.nacionalidad_madre)}</span>
                    </div>
                  </div>
                </div>
              </article>

              <article className="detalle-panel">
                <div className="detalle-panel-title">
                  <CalendarDays size={19} />
                  <h2>InformaciÃ³n de captura</h2>
                </div>

                <div className="detalle-fields">
                  <div>
                    <label>Fecha de captura</label>
                    <span>{fecha(acta.fecha_captura)}</span>
                  </div>

                  <div>
                    <label>Usuario capturista</label>
                    <span>{mostrar(acta.usuario_captura)}</span>
                  </div>

                  <div className="detalle-field-full">
                    <label>Identificador electrÃ³nico</label>
                    <span>{mostrar(acta.identificador_electronico)}</span>
                  </div>

                  <div className="detalle-field-full">
                    <label>CÃ³digo de verificaciÃ³n</label>
                    <span>{mostrar(acta.codigo_verificacion)}</span>
                  </div>
                </div>
              </article>

            </div>

            <aside className="detalle-pdf-panel">
              <div className="detalle-pdf-heading">
                <FileText size={19} />
                <div>
                  <strong>Documento original</strong>
                  <small>{mostrar(acta.nombre_original)}</small>
                </div>
              </div>

            {pdfUrl ? (
  <iframe
    className="detalle-pdf-viewer"
    src={`${pdfUrl}#toolbar=0&navpanes=0&scrollbar=0&zoom=page-fit`}
    title={`Documento del expediente ${acta.id_acta}`}
  />
) : (
  <div className="detalle-pdf-empty">
    No se pudo visualizar el documento.
  </div>
)}
            </aside>

          </div>

        </section>
      </main>

      {confirmarEliminacion && (
        <div
          className="acta-confirmacion-fondo"
          role="presentation"
          onMouseDown={(e) => {
            if (e.target === e.currentTarget && !eliminando) {
              setConfirmarEliminacion(false);
            }
          }}
        >
          <section
            className="acta-confirmacion-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="acta-confirmacion-titulo"
          >
            <div className="acta-confirmacion-icono">
              <Trash2 size={24} />
            </div>

            <span className="acta-confirmacion-etiqueta">
              ACCIÓN PERMANENTE
            </span>
            <h2 id="acta-confirmacion-titulo">
              Eliminar acta #{id}
            </h2>

            <p>
              Esta acción eliminará permanentemente el registro del acta y
              su archivo PDF del almacenamiento. No estarán disponibles para
              consulta ni podrán recuperarse desde el sistema.
            </p>

            <div className="acta-confirmacion-nota">
              <strong>¿Qué se conservará?</strong>
              <span>
                Únicamente el evento de auditoría, con una copia histórica de
                los datos y los metadatos necesarios para dejar constancia de
                quién realizó la eliminación y cuándo.
              </span>
            </div>

            <div className="acta-confirmacion-acciones">
              <button
                type="button"
                className="acta-confirmacion-cancelar"
                onClick={() => setConfirmarEliminacion(false)}
                disabled={eliminando}
              >
                Cancelar
              </button>
              <button
                type="button"
                className="acta-confirmacion-eliminar"
                onClick={eliminarActa}
                disabled={eliminando}
              >
                {eliminando ? (
                  <>
                    <LoaderCircle size={17} className="detalle-admin-spinner" />
                    Eliminando…
                  </>
                ) : (
                  <>
                    <Trash2 size={17} />
                    Eliminar permanentemente
                  </>
                )}
              </button>
            </div>
          </section>
        </div>
      )}
    </div>
  );
};

export default DetalleActa;