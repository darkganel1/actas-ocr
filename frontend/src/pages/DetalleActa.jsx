
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
  AlertCircle
} from 'lucide-react';

import { useAuth } from '../context/AuthContext';
import api from '../services/api';

const DetalleActa = () => {
  const { id } = useParams();
  const navigate = useNavigate();
  const { usuario, cerrarSesion } = useAuth();

  const [acta, setActa] = useState(null);
  const [pdfUrl, setPdfUrl] = useState('');
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let activo = true;
    let urlTemporal = '';

    const cargarExpediente = async () => {
      setCargando(true);
      setError('');

      try {
        const [respuestaActa, respuestaPDF] = await Promise.all([
          api.get(`/actas/${id}`),
          api.get(`/actas/${id}/documento`, {
            responseType: 'blob'
          })
        ]);

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
        <p>{error || 'El expediente solicitado no está disponible.'}</p>

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
          Cerrar sesión
        </button>
      </aside>

      <main className="dashboard-main">

        <header className="topbar">
          <span>Sistema de Gestión Documental</span>

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
                GESTIÓN DOCUMENTAL / EXPEDIENTE
              </span>

              <h1>Expediente #{acta.id_acta}</h1>

              <p>
                Consulta de información registral y documento original.
              </p>
            </div>

            <button
              className="detalle-back-button"
              onClick={() => navigate('/actas')}
            >
              <ArrowLeft size={17} />
              Regresar
            </button>
          </div>

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
                    <label>Oficialía</label>
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
                    <label>Número de acta</label>
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
                  <h2>Información de captura</h2>
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
                    <label>Identificador electrónico</label>
                    <span>{mostrar(acta.identificador_electronico)}</span>
                  </div>

                  <div className="detalle-field-full">
                    <label>Código de verificación</label>
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
    </div>
  );
};

export default DetalleActa;
