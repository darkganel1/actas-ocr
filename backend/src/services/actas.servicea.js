
const fs = require('fs/promises');
const path = require('path');
const crypto = require('crypto');
const { pool } = require('../config/database');

const DIRECTORIO_DOCUMENTOS = path.resolve(
  __dirname,
  '../../storage/documentos'
);

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

const convertirFecha = (valor, campo) => {
  if (!valor) {
    throw new Error(`El campo ${campo} es obligatorio.`);
  }

  const fecha = String(valor).trim();
  let coincidencia;

  if ((coincidencia = fecha.match(/^(\d{2})\/(\d{2})\/(\d{4})$/))) {
    return `${coincidencia[3]}-${coincidencia[2]}-${coincidencia[1]}`;
  }

  if ((coincidencia = fecha.match(/^(\d{4})-(\d{2})-(\d{2})$/))) {
    return fecha;
  }

  throw new Error(`El formato de ${campo} no es válido.`);
};

const guardarActa = async ({ archivo, datos, idUsuario }) => {
  if (!archivo || !archivo.buffer) {
    throw new Error('No se recibió el archivo PDF.');
  }

  if (!datos || typeof datos !== 'object' || Array.isArray(datos)) {
    throw new Error('Los datos del acta no son válidos.');
  }

  for (const campo of CAMPOS_OBLIGATORIOS) {
    if (
      datos[campo] === undefined ||
      datos[campo] === null ||
      String(datos[campo]).trim() === ''
    ) {
      throw new Error(`El campo ${campo} es obligatorio.`);
    }
  }

  if (!idUsuario) {
    throw new Error('No se pudo identificar al usuario que realiza la captura.');
  }

  const fechaRegistro = convertirFecha(datos.fecha_registro, 'fecha_registro');
  const fechaNacimiento = convertirFecha(datos.fecha_nacimiento, 'fecha_nacimiento');

  const sha256 = crypto
    .createHash('sha256')
    .update(archivo.buffer)
    .digest('hex');

  const nombreInterno = `${crypto.randomUUID()}.pdf`;
  const rutaRelativa = path.posix.join('storage', 'documentos', nombreInterno);
  const rutaFisica = path.join(DIRECTORIO_DOCUMENTOS, nombreInterno);

  let connection;
  let archivoGuardado = false;

  try {
    await fs.mkdir(DIRECTORIO_DOCUMENTOS, { recursive: true });
    await fs.writeFile(rutaFisica, archivo.buffer, { flag: 'wx' });
    archivoGuardado = true;

    connection = await pool.getConnection();
    await connection.beginTransaction();

    // Detectar duplicados sin bloquear la captura.
    const [duplicados] = await connection.execute(
      `SELECT id_documento
       FROM documentos
       WHERE hash_sha256 = ?
       LIMIT 1`,
      [sha256]
    );

    const [documentoResult] = await connection.execute(
      `INSERT INTO documentos (
        nombre_original,
        nombre_interno,
        ruta_almacenamiento,
        extension,
        mime_type,
        tamano_bytes,
        hash_sha256,
        usuario_carga
      ) VALUES (?, ?, ?, 'pdf', 'application/pdf', ?, ?, ?)`,
      [
        archivo.originalname,
        nombreInterno,
        rutaRelativa,
        archivo.size,
        sha256,
        idUsuario
      ]
    );

    const idDocumento = documentoResult.insertId;

    const columnasActa = [
      'entidad',
      'municipio',
      'oficialia',
      'fecha_registro',
      'libro',
      'numero_acta',
      'folio',
      'nombres',
      'primer_apellido',
      'segundo_apellido',
      'fecha_nacimiento',
      'sexo',
      'lugar_nacimiento',
      'nacionalidad',
      'curp',
      'nombre_padre',
      'primer_apellido_padre',
      'segundo_apellido_padre',
      'curp_padre',
      'nacionalidad_padre',
      'nombre_madre',
      'primer_apellido_madre',
      'segundo_apellido_madre',
      'curp_madre',
      'nacionalidad_madre',
      'identificador_electronico',
      'codigo_verificacion'
    ];

    const valoresActa = columnasActa.map((campo) => {
      if (campo === 'fecha_registro') return fechaRegistro;
      if (campo === 'fecha_nacimiento') return fechaNacimiento;

      const valor = datos[campo];
      return valor === undefined || valor === '' ? null : valor;
    });

    const columnas = [
      'id_documento',
      ...columnasActa,
      'usuario_captura'
    ];

    const valores = [
      idDocumento,
      ...valoresActa,
      idUsuario
    ];

    const placeholders = columnas.map(() => '?').join(', ');

    const [actaResult] = await connection.execute(
      `INSERT INTO actas (${columnas.join(', ')})
       VALUES (${placeholders})`,
      valores
    );

    const idActa = actaResult.insertId;

    const valorNuevo = {
      id_acta: idActa,
      id_documento: idDocumento,
      ...datos
    };

    await connection.execute(
      `INSERT INTO bitacora_auditoria (
        id_usuario,
        accion,
        entidad_afectada,
        id_registro,
        valor_nuevo,
        detalle
      ) VALUES (?, ?, ?, ?, ?, ?)`,
      [
        idUsuario,
        'CREAR',
        'actas',
        idActa,
        JSON.stringify(valorNuevo),
        'Registro de acta mediante procesamiento OCR y revisión manual.'
      ]
    );

    await connection.commit();

    return {
      id_acta: idActa,
      id_documento: idDocumento,
      sha256,
      duplicado: duplicados.length > 0
    };

  } catch (error) {
    if (connection) {
      await connection.rollback();
    }

    if (archivoGuardado) {
      await fs.unlink(rutaFisica).catch(() => {});
    }

    throw error;

  } finally {
    if (connection) {
      connection.release();
    }
  }
};
const listarActas = async ({ busqueda = '', pagina = 1, limite = 10 }) => {
  const paginaSegura = Math.max(1, Number.parseInt(pagina, 10) || 1);
  const limiteSeguro = Math.min(
    50,
    Math.max(1, Number.parseInt(limite, 10) || 10)
  );
  const offset = (paginaSegura - 1) * limiteSeguro;

  const condiciones = ['a.eliminado = 0'];
  const parametros = [];

  if (busqueda.trim()) {
    condiciones.push(`(
      a.nombres LIKE ?
      OR a.primer_apellido LIKE ?
      OR a.segundo_apellido LIKE ?
      OR CONCAT_WS(' ', a.nombres, a.primer_apellido, a.segundo_apellido) LIKE ?
      OR a.curp LIKE ?
      OR a.identificador_electronico LIKE ?
      OR a.numero_acta LIKE ?
    )`);

    const termino = `%${busqueda.trim()}%`;
    parametros.push(
      termino, termino, termino, termino,
      termino, termino, termino
    );
  }

  const where = condiciones.join(' AND ');

  const [conteo] = await pool.execute(
    `SELECT COUNT(*) AS total
     FROM actas a
     WHERE ${where}`,
    parametros
  );

  const [actas] = await pool.execute(
    `SELECT
       a.id_acta,
       a.id_documento,
       a.entidad,
       a.municipio,
       a.oficialia,
       a.fecha_registro,
       a.libro,
       a.numero_acta,
       a.nombres,
       a.primer_apellido,
       a.segundo_apellido,
       a.fecha_nacimiento,
       a.sexo,
       a.curp,
       a.identificador_electronico,
       a.fecha_captura,
       u.usuario AS usuario_captura
     FROM actas a
     INNER JOIN usuarios u ON u.id_usuario = a.usuario_captura
     WHERE ${where}
     ORDER BY a.fecha_captura DESC, a.id_acta DESC
     LIMIT ? OFFSET ?`,
    [...parametros, limiteSeguro, offset]
  );

  return {
    actas,
    paginacion: {
      pagina: paginaSegura,
      limite: limiteSeguro,
      total: conteo[0].total,
      totalPaginas: Math.ceil(conteo[0].total / limiteSeguro)
    }
  };
};

const obtenerActaPorId = async (idActa) => {
  const [filas] = await pool.execute(
    `SELECT
       a.*,
       d.nombre_original,
       d.nombre_interno,
       d.extension,
       d.mime_type,
       d.tamano_bytes,
       d.fecha_carga,
       u.usuario AS usuario_captura
     FROM actas a
     INNER JOIN documentos d
       ON d.id_documento = a.id_documento
     INNER JOIN usuarios u
       ON u.id_usuario = a.usuario_captura
     WHERE a.id_acta = ?
       AND a.eliminado = 0
     LIMIT 1`,
    [idActa]
  );

  return filas[0] || null;
};

const obtenerDocumentoActa = async (idActa) => {
  const [filas] = await pool.execute(
    `SELECT d.ruta_almacenamiento, d.mime_type, d.nombre_original
     FROM actas a
     INNER JOIN documentos d
       ON d.id_documento = a.id_documento
     WHERE a.id_acta = ?
       AND a.eliminado = 0
     LIMIT 1`,
    [idActa]
  );

  if (!filas.length) return null;

  const directorio = path.resolve(DIRECTORIO_DOCUMENTOS);
  const rutaArchivo = path.resolve(
    __dirname,
    '../..',
    filas[0].ruta_almacenamiento
  );

  // Impide que una ruta manipulada permita salir del almacenamiento privado.
  if (path.dirname(rutaArchivo) !== directorio) {
    throw new Error('La ruta del documento no es válida.');
  }

  return {
    ruta: rutaArchivo,
    mime_type: filas[0].mime_type,
    nombre_original: filas[0].nombre_original
  };
};
module.exports = {
  guardarActa,
  listarActas,
  obtenerActaPorId,
  obtenerDocumentoActa
};
