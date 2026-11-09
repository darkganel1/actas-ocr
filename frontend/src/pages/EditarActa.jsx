import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  ArrowLeft,
  Save,
  LoaderCircle,
  AlertCircle,
  CheckCircle2,
  Landmark,
  FileEdit,
  FileText,
  Eye
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import api from '../services/api';
import './EditarActa.css';

const CAMPOS = {
  entidad: '',
  municipio: '',
  oficialia: '',
  fecha_registro: '',
  libro: '',
  numero_acta: '',
  folio: '',
  nombres: '',
  primer_apellido: '',
  segundo_apellido: '',
  fecha_nacimiento: '',
  sexo: '',
  lugar_nacimiento: '',
  nacionalidad: '',
  curp: '',
  nombre_padre: '',
  primer_apellido_padre: '',
  segundo_apellido_padre: '',
  curp_padre: '',
  nacionalidad_padre: '',
  nombre_madre: '',
  primer_apellido_madre: '',
  segundo_apellido_madre: '',
  curp_madre: '',
  nacionalidad_madre: '',
  identificador_electronico: '',
  codigo_verificacion: ''
};

const ETIQUETAS = {
  entidad: 'Entidad',
  municipio: 'Municipio',
  oficialia: 'Oficialía',
  fecha_registro: 'Fecha de registro',
  libro: 'Libro',
  numero_acta: 'Número de acta',
  folio: 'Folio',
  nombres: 'Nombre(s)',
  primer_apellido: 'Primer apellido',
  segundo_apellido: 'Segundo apellido',
  fecha_nacimiento: 'Fecha de nacimiento',
  sexo: 'Sexo',
  lugar_nacimiento: 'Lugar de nacimiento',
  nacionalidad: 'Nacionalidad',
  curp: 'CURP',
  nombre_padre: 'Nombre(s) del padre',
  primer_apellido_padre: 'Primer apellido del padre',
  segundo_apellido_padre: 'Segundo apellido del padre',
  curp_padre: 'CURP del padre',
  nacionalidad_padre: 'Nacionalidad del padre',
  nombre_madre: 'Nombre(s) de la madre',
  primer_apellido_madre: 'Primer apellido de la madre',
  segundo_apellido_madre: 'Segundo apellido de la madre',
  curp_madre: 'CURP de la madre',
  nacionalidad_madre: 'Nacionalidad de la madre',
  identificador_electronico: 'Identificador electrónico',
  codigo_verificacion: 'Código de verificación'
};

const OBLIGATORIOS = [
  'oficialia', 'fecha_registro', 'libro', 'numero_acta',
  'nombres', 'primer_apellido', 'segundo_apellido',
  'fecha_nacimiento', 'sexo'
];

// Comparte las peticiones simultáneas que StrictMode puede iniciar en desarrollo.
// La lectura del expediente y la descarga del PDF se auditan una sola vez por apertura.
const solicitudesEdicion = new Map();

function obtenerSolicitudActa(id) {
  if (solicitudesEdicion.has(id)) return solicitudesEdicion.get(id);

  const solicitud = Promise.all([
    api.get(`/actas/${id}`),
    api.get(`/actas/${id}/documento`, { responseType: 'blob' })
      .then((respuesta) => ({ respuesta }))
      .catch((error) => ({ error }))
  ]);

  solicitudesEdicion.set(id, solicitud);
  const limpiar = () => {
    if (solicitudesEdicion.get(id) === solicitud) {
      solicitudesEdicion.delete(id);
    }
  };
  solicitud.then(limpiar, limpiar);

  return solicitud;
}

function fechaInput(valor) {
  if (!valor) return '';
  return String(valor).slice(0, 10);
}

export default function EditarActa() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { usuario } = useAuth();

  const [datos, setDatos] = useState(CAMPOS);
  const [cargando, setCargando] = useState(true);
  const [cargandoPDF, setCargandoPDF] = useState(true);
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState('');
  const [errorPDF, setErrorPDF] = useState('');
  const [mensaje, setMensaje] = useState('');
  const [nombreDocumento, setNombreDocumento] = useState('Documento original');
  const [pdfUrl, setPdfUrl] = useState('');

  useEffect(() => {
    let vigente = true;
    let urlTemporal = '';

    const cargar = async () => {
      setCargando(true);
      setCargandoPDF(true);
      setError('');
      setErrorPDF('');
      setPdfUrl('');

      try {
        const [respuestaActa, resultadoPDF] = await obtenerSolicitudActa(id);
        if (!respuestaActa.data?.success || !respuestaActa.data?.acta) {
          throw new Error('No fue posible recuperar los datos del acta.');
        }

        const acta = respuestaActa.data.acta;
        const iniciales = { ...CAMPOS };
        Object.keys(CAMPOS).forEach((campo) => {
          iniciales[campo] =
            campo === 'fecha_registro' || campo === 'fecha_nacimiento'
              ? fechaInput(acta[campo])
              : acta[campo] ?? '';
        });

        if (vigente) {
          setDatos(iniciales);
          setNombreDocumento(acta.nombre_original || 'Documento original conservado');
          setCargando(false);
        }

        if (resultadoPDF.error) {
          if (vigente) {
            setErrorPDF(
              resultadoPDF.error.response?.data?.mensaje ||
              'No fue posible cargar la vista previa del PDF.'
            );
          }
        } else {
          const archivoPDF = new Blob(
            [resultadoPDF.respuesta.data],
            { type: 'application/pdf' }
          );
          urlTemporal = URL.createObjectURL(archivoPDF);

          if (vigente) {
            setPdfUrl(urlTemporal);
          } else {
            URL.revokeObjectURL(urlTemporal);
          }
        }
      } catch (err) {
        if (vigente) {
          setError(
            err.response?.data?.mensaje ||
            err.message ||
            'No fue posible cargar el acta.'
          );
        }
      } finally {
        if (vigente) {
          setCargando(false);
          setCargandoPDF(false);
        }
      }
    };

    cargar();

    return () => {
      vigente = false;
      if (urlTemporal) URL.revokeObjectURL(urlTemporal);
    };
  }, [id]);

  const cambiarDato = (campo, valor) => {
    setDatos((actuales) => ({ ...actuales, [campo]: valor }));
  };

  const guardar = async (e) => {
    e.preventDefault();
    setError('');
    setMensaje('');

    const faltantes = OBLIGATORIOS.filter(
      (campo) => !String(datos[campo] ?? '').trim()
    );
    if (faltantes.length) {
      setError(`Completa los campos obligatorios: ${faltantes.map((c) => ETIQUETAS[c]).join(', ')}.`);
      return;
    }

    setGuardando(true);
    try {
      const respuesta = await api.put(`/actas/${id}`, datos);
      if (!respuesta.data?.success) {
        throw new Error(respuesta.data?.mensaje || 'No fue posible actualizar el acta.');
      }
      navigate(`/actas/${id}`, { replace: true });
    } catch (err) {
      setError(
        err.response?.data?.mensaje ||
        err.message ||
        'No fue posible guardar los cambios.'
      );
    } finally {
      setGuardando(false);
    }
  };

  const seccion = (titulo, campos) => (
    <section className="editar-acta-seccion" key={titulo}>
      <h2>{titulo}</h2>
      <div className="editar-acta-grid">
        {campos.map((campo) => {
          const esFecha = campo === 'fecha_registro' || campo === 'fecha_nacimiento';
          const obligatorio = OBLIGATORIOS.includes(campo);
          return (
            <label className="editar-acta-campo" key={campo}>
              <span>{ETIQUETAS[campo]}{obligatorio && <b> *</b>}</span>
              <input
                type={esFecha ? 'date' : 'text'}
                name={campo}
                value={datos[campo] ?? ''}
                onChange={(e) => cambiarDato(campo, e.target.value)}
                required={obligatorio}
                maxLength={campo === 'curp' || campo === 'curp_padre' || campo === 'curp_madre' ? 18 : undefined}
                autoComplete="off"
              />
            </label>
          );
        })}
      </div>
    </section>
  );

  if (cargando) {
    return (
      <div className="editar-acta-estado">
        <LoaderCircle className="editar-acta-girar" size={28} />
        <span>Cargando información del acta…</span>
      </div>
    );
  }

  if (error && !Object.values(datos).some(Boolean)) {
    return (
      <div className="editar-acta-estado editar-acta-estado-error">
        <AlertCircle size={28} />
        <strong>No fue posible abrir la edición</strong>
        <span>{error}</span>
        <button type="button" onClick={() => navigate(`/actas/${id}`)}>Regresar al expediente</button>
      </div>
    );
  }

  return (
    <div className="editar-acta-page">
      <header className="editar-acta-topbar">
        <div className="editar-acta-marca">
          <Landmark size={25} />
          <div><strong>REGISTRO DE ACTAS</strong><span>EDICIÓN ADMINISTRATIVA</span></div>
        </div>
        <div className="editar-acta-usuario">
          <strong>{usuario?.nombre_completo}</strong>
          <small>{usuario?.rol}</small>
        </div>
      </header>

      <main className="editar-acta-contenido">
        <button type="button" className="editar-acta-regresar" onClick={() => navigate(`/actas/${id}`)}>
          <ArrowLeft size={17} /> Regresar al expediente
        </button>

        <div className="editar-acta-encabezado">
          <div className="editar-acta-icono"><FileEdit size={24} /></div>
          <div>
            <span>ADMINISTRACIÓN / CORRECCIÓN DE REGISTRO</span>
            <h1>Editar acta #{id}</h1>
            <p>Consulta el documento original y modifica los datos capturados.</p>
          </div>
        </div>

        {error && <div className="editar-acta-alerta"><AlertCircle size={18} />{error}</div>}
        {mensaje && <div className="editar-acta-exito"><CheckCircle2 size={18} />{mensaje}</div>}

        <div className="editar-acta-layout">
          <aside className="editar-acta-documento-panel">
            <div className="editar-acta-panel-titulo">
              <FileText size={19} />
              <h2>Documento original</h2>
            </div>

            <div className="editar-acta-archivo-info">
              <FileText size={17} />
              <div>
                <strong>{nombreDocumento}</strong>
                <small>PDF asociado al acta #{id}. Se conserva sin modificaciones.</small>
              </div>
            </div>

            <div className="editar-acta-visor">
              {pdfUrl ? (
                <iframe
                  src={`${pdfUrl}#toolbar=0&navpanes=0&scrollbar=0&zoom=page-fit`}
                  title={`Vista previa del documento original del acta ${id}`}
                />
              ) : cargandoPDF ? (
                <div className="editar-acta-visor-estado">
                  <LoaderCircle className="editar-acta-girar" size={27} />
                  <span>Cargando documento PDF…</span>
                </div>
              ) : (
                <div className="editar-acta-visor-estado">
                  <Eye size={30} />
                  <strong>Vista previa no disponible</strong>
                  <span>{errorPDF || 'No se recibió el documento original.'}</span>
                </div>
              )}
            </div>
          </aside>

          <main className="editar-acta-formulario">
            <div className="editar-acta-panel-titulo">
              <FileEdit size={19} />
              <h2>Datos para editar</h2>
            </div>

            <form onSubmit={guardar}>
              {seccion('Datos registrales', ['entidad', 'municipio', 'oficialia', 'fecha_registro', 'libro', 'numero_acta', 'folio'])}
              {seccion('Datos de la persona registrada', ['nombres', 'primer_apellido', 'segundo_apellido', 'fecha_nacimiento', 'sexo', 'lugar_nacimiento', 'nacionalidad', 'curp'])}
              {seccion('Datos del padre', ['nombre_padre', 'primer_apellido_padre', 'segundo_apellido_padre', 'curp_padre', 'nacionalidad_padre'])}
              {seccion('Datos de la madre', ['nombre_madre', 'primer_apellido_madre', 'segundo_apellido_madre', 'curp_madre', 'nacionalidad_madre'])}
              {seccion('Identificadores del documento', ['identificador_electronico', 'codigo_verificacion'])}

              <div className="editar-acta-acciones">
                <button type="button" className="editar-acta-cancelar" onClick={() => navigate(`/actas/${id}`)} disabled={guardando}>
                  Cancelar
                </button>
                <button type="submit" className="editar-acta-guardar" disabled={guardando}>
                  {guardando ? <><LoaderCircle size={17} className="editar-acta-girar" /> Guardando…</> : <><Save size={17} /> Guardar cambios</>}
                </button>
              </div>
            </form>
          </main>
        </div>
      </main>
    </div>
  );
}
