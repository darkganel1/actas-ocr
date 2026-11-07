import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ArrowLeft,
  FileText,
  Upload,
  ScanText,
  Save,
  LoaderCircle,
  AlertCircle,
  CheckCircle2,
  Eye,
  RotateCcw
} from 'lucide-react';
import api from '../services/api';

const CAMPOS_INICIALES = {
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

const MAPEO_OCR = {
  oficialia: 'oficialia',
  fecha_registro: 'fecha_registro',
  libro: 'libro',
  numero_acta: 'numero_acta',
  nombre: 'nombres',
  primer_apellido: 'primer_apellido',
  segundo_apellido: 'segundo_apellido',
  fecha_nacimiento: 'fecha_nacimiento',
  sexo: 'sexo',
  lugar_nacimiento: 'lugar_nacimiento',
  nacionalidad: 'nacionalidad',
  folio: 'folio',
  curp: 'curp',
  identificador_electronico: 'identificador_electronico',
  codigo_verificacion: 'codigo_verificacion'
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

const CAMPOS_OBLIGATORIOS = [
  'oficialia',
  'fecha_registro',
  'libro',
  'numero_acta',
  'nombres',
  'primer_apellido',
  'segundo_apellido',
  'fecha_nacimiento',
  'sexo'
];

function valorOCR(campos, nombre) {
  const dato = campos?.[nombre];

  if (dato && typeof dato === 'object' && 'valor' in dato) {
    return dato.valor ?? '';
  }

  return dato ?? '';
}

function obtenerConfianza(campos, nombre) {
  const confianza = campos?.[nombre]?.confianza;

  if (confianza === null || confianza === undefined || confianza === '') {
    return null;
  }

  const numero = Number(confianza);
  return Number.isFinite(numero) ? numero : null;
}

function estadoConfianza(confianza) {
  if (
    confianza === null ||
    confianza === undefined ||
    !Number.isFinite(Number(confianza))
  ) {
    return {
      clase: 'sin-dato',
      texto: 'Sin confianza'
    };
  }

  const valor = Number(confianza);

  if (valor >= 85) {
    return {
      clase: 'alta',
      texto: `Alta ${valor.toFixed(0)}%`
    };
  }

  if (valor >= 60) {
    return {
      clase: 'media',
      texto: `Media ${valor.toFixed(0)}%`
    };
  }

  return {
    clase: 'baja',
    texto: `Baja ${valor.toFixed(0)}%`
  };
}

function Campo({
  nombre,
  value,
  onChange,
  tipo = 'text',
  obligatorio = false,
  confianza,
  ayuda
}) {
  const estado = estadoConfianza(confianza);

  return (
    <div className="nueva-campo">
      <label htmlFor={nombre}>
        {ETIQUETAS[nombre] || nombre}
        {obligatorio && <span className="campo-obligatorio"> *</span>}
      </label>

      <div className="campo-control">
        <input
          id={nombre}
          name={nombre}
          type={tipo}
          value={value ?? ''}
          onChange={(e) => onChange(nombre, e.target.value)}
          required={obligatorio}
          placeholder="Capturar información"
          autoComplete="off"
        />

        {confianza !== undefined && (
          <span className={`confianza ${estado.clase}`}>
            {estado.texto}
          </span>
        )}
      </div>

      {ayuda && <small className="campo-ayuda">{ayuda}</small>}
    </div>
  );
}

export default function NuevaActa() {
  const navigate = useNavigate();

  const [archivo, setArchivo] = useState(null);
  const [vistaPDF, setVistaPDF] = useState('');
  const [datos, setDatos] = useState(CAMPOS_INICIALES);
  const [confianzas, setConfianzas] = useState({});
  const [resultadoOCR, setResultadoOCR] = useState(null);
  const [sha256, setSha256] = useState('');
  const [procesando, setProcesando] = useState(false);
  const [guardando, setGuardando] = useState(false);
  const [mensaje, setMensaje] = useState(null);
  const [errores, setErrores] = useState([]);

  useEffect(() => {
    return () => {
      if (vistaPDF) URL.revokeObjectURL(vistaPDF);
    };
  }, [vistaPDF]);

  const camposPendientes = useMemo(() => {
    return CAMPOS_OBLIGATORIOS.filter(
      (campo) => !String(datos[campo] ?? '').trim()
    );
  }, [datos]);

  const seleccionarArchivo = (e) => {
    const seleccionado = e.target.files?.[0];

    if (!seleccionado) return;

    if (seleccionado.type !== 'application/pdf') {
      setMensaje({
        tipo: 'error',
        texto: 'Selecciona un archivo PDF válido.'
      });
      e.target.value = '';
      return;
    }

    if (seleccionado.size > 20 * 1024 * 1024) {
      setMensaje({
        tipo: 'error',
        texto: 'El archivo supera el límite permitido de 20 MB.'
      });
      e.target.value = '';
      return;
    }

    setArchivo(seleccionado);
    setVistaPDF(URL.createObjectURL(seleccionado));
    setDatos(CAMPOS_INICIALES);
    setConfianzas({});
    setResultadoOCR(null);
    setSha256('');
    setErrores([]);
    setMensaje(null);
  };

  const cambiarDato = (nombre, valor) => {
    setDatos((actuales) => ({
      ...actuales,
      [nombre]: valor
    }));
  };

  const procesarDocumento = async () => {
    if (!archivo) {
      setMensaje({
        tipo: 'error',
        texto: 'Primero selecciona un documento PDF.'
      });
      return;
    }

    setProcesando(true);
    setMensaje(null);
    setErrores([]);

    try {
      const formulario = new FormData();
      formulario.append('documento', archivo);

      const respuesta = await api.post(
        '/documentos/procesar',
        formulario,
        {
          headers: {
            'Content-Type': 'multipart/form-data'
          },
          timeout: 600000
        }
      );

      const resultado = respuesta.data.resultado;
      const camposOCR = resultado?.campos || {};

      const nuevosDatos = { ...CAMPOS_INICIALES };
      const nuevasConfianzas = {};

      Object.entries(MAPEO_OCR).forEach(([campoOCR, campoFormulario]) => {
        nuevosDatos[campoFormulario] = valorOCR(camposOCR, campoOCR);
        nuevasConfianzas[campoFormulario] = obtenerConfianza(
          camposOCR,
          campoOCR
        );
      });

      setDatos(nuevosDatos);
      setConfianzas(nuevasConfianzas);
      setResultadoOCR(resultado);
      setSha256(respuesta.data.sha256 || '');

      setMensaje({
        tipo: 'exito',
        texto: 'Documento procesado. Revisa y corrige todos los campos antes de guardar.'
      });
    } catch (error) {
      console.error('Error al procesar documento:', error);

      setMensaje({
        tipo: 'error',
        texto:
          error.response?.data?.mensaje ||
          'No fue posible procesar el documento. Revisa el servidor OCR.'
      });
    } finally {
      setProcesando(false);
    }
  };

  const guardarActa = async (e) => {
    e.preventDefault();

    if (!archivo || !resultadoOCR) {
      setMensaje({
        tipo: 'error',
        texto: 'Debes seleccionar y procesar un documento antes de guardarlo.'
      });
      return;
    }

    const faltantes = CAMPOS_OBLIGATORIOS.filter(
      (campo) => !String(datos[campo] ?? '').trim()
    );

    if (faltantes.length > 0) {
      setErrores(faltantes.map((campo) => ETIQUETAS[campo]));
      setMensaje({
        tipo: 'error',
        texto: 'Completa los campos obligatorios señalados.'
      });
      return;
    }

    setGuardando(true);
    setMensaje(null);
    setErrores([]);

    try {
      const formulario = new FormData();
      formulario.append('documento', archivo);
      formulario.append('datos', JSON.stringify(datos));

      const respuesta = await api.post('/actas', formulario, {
        headers: {
          'Content-Type': 'multipart/form-data'
        },
        timeout: 120000
      });

      const idActa =
        respuesta.data.id_acta ||
        respuesta.data.acta?.id_acta;

      if (respuesta.data.duplicado) {
        setMensaje({
          tipo: 'advertencia',
          texto: 'El documento ya existe en el sistema. Se registró la advertencia de duplicidad.'
        });
      }

      if (idActa) {
        navigate(`/actas/${idActa}`);
      } else {
        setMensaje({
          tipo: 'exito',
          texto: respuesta.data.mensaje || 'Acta guardada correctamente.'
        });
      }
    } catch (error) {
      console.error('Error al guardar acta:', error);

      setMensaje({
        tipo: 'error',
        texto:
          error.response?.data?.mensaje ||
          'No fue posible guardar el acta.'
      });
    } finally {
      setGuardando(false);
    }
  };

  const reiniciar = () => {
    setArchivo(null);
    setVistaPDF('');
    setDatos(CAMPOS_INICIALES);
    setConfianzas({});
    setResultadoOCR(null);
    setSha256('');
    setErrores([]);
    setMensaje(null);

    const input = document.getElementById('archivo-pdf');
    if (input) input.value = '';
  };

  const seccion = (titulo, campos) => (
    <section className="nueva-seccion">
      <h3>{titulo}</h3>
      <div className="nueva-grid">
        {campos.map((campo) => (
          <Campo
            key={campo}
            nombre={campo}
            value={datos[campo]}
            onChange={cambiarDato}
            confianza={resultadoOCR ? confianzas[campo] : undefined}
            obligatorio={CAMPOS_OBLIGATORIOS.includes(campo)}
          />
        ))}
      </div>
    </section>
  );

  return (
    <div className="nueva-acta-page">
      <div className="nueva-encabezado">
        <button
          type="button"
          className="nueva-volver"
          onClick={() => navigate('/actas')}
        >
          <ArrowLeft size={18} />
          Regresar
        </button>

        <div>
          <h1>Nueva captura de acta</h1>
          <p>Procesamiento OCR y revisión de información registral</p>
        </div>
      </div>

      {mensaje && (
        <div className={`nueva-mensaje ${mensaje.tipo}`}>
          {mensaje.tipo === 'exito' ? (
            <CheckCircle2 size={19} />
          ) : (
            <AlertCircle size={19} />
          )}
          <span>{mensaje.texto}</span>
        </div>
      )}

      <div className="nueva-contenido">
        <aside className="nueva-documento">
          <div className="nueva-panel-titulo">
            <FileText size={19} />
            <h2>Documento original</h2>
          </div>

          <label className="nueva-selector-archivo" htmlFor="archivo-pdf">
            <Upload size={23} />
            <strong>Seleccionar archivo PDF</strong>
            <span>Máximo 20 MB</span>
          </label>

          <input
            id="archivo-pdf"
            type="file"
            accept="application/pdf,.pdf"
            onChange={seleccionarArchivo}
            hidden
          />

          {archivo && (
            <div className="nueva-archivo-info">
              <FileText size={17} />
              <div>
                <strong>{archivo.name}</strong>
                <small>{(archivo.size / 1024 / 1024).toFixed(2)} MB</small>
              </div>
            </div>
          )}

          <button
            type="button"
            className="nueva-btn-procesar"
            onClick={procesarDocumento}
            disabled={!archivo || procesando || guardando}
          >
            {procesando ? (
              <>
                <LoaderCircle className="girar" size={18} />
                Procesando OCR...
              </>
            ) : (
              <>
                <ScanText size={18} />
                Procesar documento
              </>
            )}
          </button>

          <button
            type="button"
            className="nueva-btn-secundario"
            onClick={reiniciar}
            disabled={procesando || guardando}
          >
            <RotateCcw size={16} />
            Reiniciar captura
          </button>

          <div className="nueva-visor">
            {vistaPDF ? (
            <iframe
  src={`${vistaPDF}#toolbar=0&navpanes=0&scrollbar=0&zoom=page-fit`}
  title="Vista previa completa del acta"
/>
            ) : (
              <div className="nueva-visor-vacio">
                <Eye size={35} />
                <span>La vista previa del PDF aparecerá aquí</span>
              </div>
            )}
          </div>

          {sha256 && (
            <div className="nueva-hash">
              <strong>SHA-256</strong>
              <small>{sha256}</small>
            </div>
          )}
        </aside>

        <main className="nueva-formulario">
          <div className="nueva-panel-titulo">
            <ScanText size={19} />
            <h2>Información del acta</h2>
          </div>

          {!resultadoOCR && (
            <div className="nueva-aviso">
              Selecciona el documento y ejecuta el procesamiento OCR para
              cargar los datos detectados. También puedes revisar el PDF
              antes de procesarlo.
            </div>
          )}

          {resultadoOCR && (
            <>
              <div className="nueva-leyenda">
                <strong>Confianza OCR:</strong>
                <span className="confianza alta">Alta ≥ 85%</span>
                <span className="confianza media">Media 60–84%</span>
                <span className="confianza baja">Baja menor a 60%</span>
                <span className="confianza sin-dato">Sin dato</span>
              </div>

              <p className="nueva-nota-revision">
                Los valores detectados deben cotejarse con el documento
                original. La confianza no garantiza que el dato sea correcto.
              </p>
            </>
          )}

          <form onSubmit={guardarActa}>
            {seccion('Datos registrales', [
              'entidad',
              'municipio',
              'oficialia',
              'fecha_registro',
              'libro',
              'numero_acta',
              'folio'
            ])}

            {seccion('Datos de la persona registrada', [
              'nombres',
              'primer_apellido',
              'segundo_apellido',
              'fecha_nacimiento',
              'sexo',
              'lugar_nacimiento',
              'nacionalidad',
              'curp'
            ])}

            {seccion('Datos del padre', [
              'nombre_padre',
              'primer_apellido_padre',
              'segundo_apellido_padre',
              'curp_padre',
              'nacionalidad_padre'
            ])}

            {seccion('Datos de la madre', [
              'nombre_madre',
              'primer_apellido_madre',
              'segundo_apellido_madre',
              'curp_madre',
              'nacionalidad_madre'
            ])}

            {seccion('Identificadores del documento', [
              'identificador_electronico',
              'codigo_verificacion'
            ])}

            {errores.length > 0 && (
              <div className="nueva-errores">
                <strong>Campos obligatorios pendientes:</strong>
                <ul>
                  {errores.map((error) => <li key={error}>{error}</li>)}
                </ul>
              </div>
            )}

            <div className="nueva-resumen">
              <span>
                Campos obligatorios pendientes: <strong>{camposPendientes.length}</strong>
              </span>
              <span>
                {resultadoOCR ? 'OCR procesado' : 'OCR pendiente'}
              </span>
            </div>

            <div className="nueva-acciones">
              <button
                type="button"
                className="nueva-btn-secundario"
                onClick={() => navigate('/actas')}
                disabled={guardando}
              >
                Cancelar
              </button>

              <button
                type="submit"
                className="nueva-btn-guardar"
                disabled={!resultadoOCR || guardando || procesando}
              >
                {guardando ? (
                  <>
                    <LoaderCircle className="girar" size={18} />
                    Guardando...
                  </>
                ) : (
                  <>
                    <Save size={18} />
                    Guardar acta
                  </>
                )}
              </button>
            </div>
          </form>
        </main>
      </div>
    </div>
  );
}