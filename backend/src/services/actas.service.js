
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
    `SELECT d.id_documento, d.ruta_almacenamiento, d.mime_type, d.nombre_original
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
    id_documento: filas[0].id_documento,
    ruta: rutaArchivo,
    mime_type: filas[0].mime_type,
    nombre_original: filas[0].nombre_original
  };
};

// Campos que el administrador puede corregir. No se permite cambiar id_documento,
// usuario_captura ni metadatos de almacenamiento desde este endpoint.
const CAMPOS_EDITABLES = [
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

const LIMITES_CAMPOS = {
  entidad: 80,
  municipio: 120,
  oficialia: 30,
  libro: 30,
  numero_acta: 30,
  folio: 50,
  nombres: 150,
  primer_apellido: 100,
  segundo_apellido: 100,
  sexo: 20,
  lugar_nacimiento: 200,
  nacionalidad: 80,
  curp: 18,
  nombre_padre: 150,
  primer_apellido_padre: 100,
  segundo_apellido_padre: 100,
  curp_padre: 18,
  nacionalidad_padre: 80,
  nombre_madre: 150,
  primer_apellido_madre: 100,
  segundo_apellido_madre: 100,
  curp_madre: 18,
  nacionalidad_madre: 80,
  identificador_electronico: 100,
  codigo_verificacion: 100
};

const normalizarFechaEdicion = (valor, campo) => {
  const fecha = convertirFecha(valor, campo);
  const [anio, mes, dia] = fecha.split('-').map(Number);
  const comprobacion = new Date(Date.UTC(anio, mes - 1, dia));

  if (
    comprobacion.getUTCFullYear() !== anio ||
    comprobacion.getUTCMonth() + 1 !== mes ||
    comprobacion.getUTCDate() !== dia
  ) {
    throw new Error(`La fecha de ${campo} no es válida.`);
  }

  return fecha;
};

const normalizarDatosEdicion = (datos) => {
  if (!datos || typeof datos !== 'object' || Array.isArray(datos)) {
    throw new Error('Los datos del acta no son válidos.');
  }

  const normalizados = {};

  for (const campo of CAMPOS_EDITABLES) {
    let valor = datos[campo];

    if (campo === 'fecha_registro' || campo === 'fecha_nacimiento') {
      normalizados[campo] = normalizarFechaEdicion(valor, campo);
      continue;
    }

    valor = valor === undefined || valor === null
      ? ''
      : String(valor).trim();

    if (CAMPOS_OBLIGATORIOS.includes(campo) && !valor) {
      throw new Error(`El campo ${campo} es obligatorio.`);
    }

    if (valor && LIMITES_CAMPOS[campo] && valor.length > LIMITES_CAMPOS[campo]) {
      throw new Error(`El campo ${campo} supera el máximo de ${LIMITES_CAMPOS[campo]} caracteres.`);
    }

    normalizados[campo] = valor === '' ? null : valor;
  }

  return normalizados;
};

const valorAuditoria = (valor, campo) => {
  if (valor === null || valor === undefined) return null;

  if (valor instanceof Date) {
    if (campo === 'fecha_registro' || campo === 'fecha_nacimiento') {
      const anio = valor.getFullYear();
      const mes = String(valor.getMonth() + 1).padStart(2, '0');
      const dia = String(valor.getDate()).padStart(2, '0');
      return `${anio}-${mes}-${dia}`;
    }
    return valor.toISOString();
  }

  return String(valor);
};

const actualizarActaPorAdministrador = async ({ idActa, datos, idUsuario }) => {
  const idSeguro = Number(idActa);
  const actorSeguro = Number(idUsuario);

  if (!Number.isSafeInteger(idSeguro) || idSeguro <= 0) {
    const error = new Error('El identificador del acta no es válido.');
    error.statusCode = 400;
    throw error;
  }

  if (!Number.isSafeInteger(actorSeguro) || actorSeguro <= 0) {
    const error = new Error('No se pudo identificar al administrador.');
    error.statusCode = 401;
    throw error;
  }

  const nuevosValores = normalizarDatosEdicion(datos);
  let connection;
  let transaccionIniciada = false;

  try {
    connection = await pool.getConnection();
    await connection.beginTransaction();
    transaccionIniciada = true;

    const [filas] = await connection.execute(
      `SELECT ${CAMPOS_EDITABLES.join(', ')}
       FROM actas
       WHERE id_acta = ? AND eliminado = 0
       LIMIT 1
       FOR UPDATE`,
      [idSeguro]
    );

    if (!filas.length) {
      const error = new Error('No se encontró un acta activa con ese identificador.');
      error.statusCode = 404;
      throw error;
    }

    const anterior = filas[0];
    const valorAnterior = {};
    const valorNuevo = {};
    const camposModificados = [];

    for (const campo of CAMPOS_EDITABLES) {
      const anteriorNormalizado = valorAuditoria(anterior[campo], campo);
      const nuevoNormalizado = nuevosValores[campo];

      if (anteriorNormalizado !== nuevoNormalizado) {
        camposModificados.push(campo);
        valorAnterior[campo] = anteriorNormalizado;
        valorNuevo[campo] = nuevoNormalizado;
      }
    }

    if (camposModificados.length === 0) {
      await connection.commit();
      transaccionIniciada = false;
      return { actualizado: false, campos_modificados: [] };
    }

    const asignaciones = CAMPOS_EDITABLES.map((campo) => `${campo} = ?`).join(', ');
    const valores = CAMPOS_EDITABLES.map((campo) => nuevosValores[campo]);

    await connection.execute(
      `UPDATE actas
       SET ${asignaciones},
           usuario_ultima_modificacion = ?,
           fecha_ultima_modificacion = NOW()
       WHERE id_acta = ? AND eliminado = 0`,
      [...valores, actorSeguro, idSeguro]
    );

    await connection.execute(
      `INSERT INTO bitacora_auditoria (
        id_usuario,
        accion,
        entidad_afectada,
        id_registro,
        valor_anterior,
        valor_nuevo,
        detalle
      ) VALUES (?, 'ACTUALIZAR', 'actas', ?, ?, ?, ?)`,
      [
        actorSeguro,
        idSeguro,
        JSON.stringify(valorAnterior),
        JSON.stringify(valorNuevo),
        `Corrección administrativa del acta. Campos modificados: ${camposModificados.join(', ')}.`
      ]
    );

    await connection.commit();
    transaccionIniciada = false;

    return {
      actualizado: true,
      campos_modificados: camposModificados
    };
  } catch (error) {
    if (connection && transaccionIniciada) {
      await connection.rollback();
      transaccionIniciada = false;
    }
    throw error;
  } finally {
    if (connection) connection.release();
  }
};


// Eliminación física del acta y de su registro de documento.
// La bitácora conserva una copia histórica de los campos del acta y los metadatos
// del PDF. El archivo se mueve temporalmente antes del commit para poder restaurarlo
// si falla la transacción; solo se destruye definitivamente después del commit.
const eliminarActaPermanentemente = async ({ idActa, idUsuario }) => {
  const idSeguro = Number(idActa);
  const actorSeguro = Number(idUsuario);

  if (!Number.isSafeInteger(idSeguro) || idSeguro <= 0) {
    const error = new Error('El identificador del acta no es válido.');
    error.statusCode = 400;
    throw error;
  }

  if (!Number.isSafeInteger(actorSeguro) || actorSeguro <= 0) {
    const error = new Error('No se pudo identificar al administrador.');
    error.statusCode = 401;
    throw error;
  }

  let connection;
  let transaccionIniciada = false;
  let rutaOriginal = null;
  let rutaTemporal = null;
  let archivoMovido = false;
  let idEventoAuditoria = null;
  let pdfYaNoExistia = false;

  try {
    connection = await pool.getConnection();
    await connection.beginTransaction();
    transaccionIniciada = true;

    const [filas] = await connection.execute(
      `SELECT
         a.*,
         d.nombre_original,
         d.nombre_interno,
         d.ruta_almacenamiento,
         d.tamano_bytes,
         d.hash_sha256,
         d.mime_type
       FROM actas a
       INNER JOIN documentos d ON d.id_documento = a.id_documento
       WHERE a.id_acta = ?
       LIMIT 1
       FOR UPDATE`,
      [idSeguro]
    );

    if (!filas.length) {
      const error = new Error('No se encontró el acta solicitada.');
      error.statusCode = 404;
      throw error;
    }

    const fila = filas[0];

    // Comprueba que el archivo esté dentro del directorio privado esperado.
    const directorioDocumentos = path.resolve(DIRECTORIO_DOCUMENTOS);
    rutaOriginal = path.resolve(
      __dirname,
      '../..',
      fila.ruta_almacenamiento
    );

    if (path.dirname(rutaOriginal) !== directorioDocumentos) {
      const error = new Error('La ruta del PDF no es válida. Se canceló la eliminación.');
      error.statusCode = 500;
      throw error;
    }

    // Construye la evidencia histórica que permanecerá en bitacora_auditoria.
    const snapshotActa = {};
    for (const campo of CAMPOS_EDITABLES) {
      snapshotActa[campo] = valorAuditoria(fila[campo], campo);
    }

    snapshotActa.id_acta = Number(fila.id_acta);
    snapshotActa.id_documento = Number(fila.id_documento);
    snapshotActa.usuario_captura = Number(fila.usuario_captura);
    snapshotActa.fecha_captura = valorAuditoria(fila.fecha_captura, 'fecha_captura');
    snapshotActa.documento = {
      nombre_original: fila.nombre_original,
      tamano_bytes: Number(fila.tamano_bytes),
      sha256: fila.hash_sha256,
      mime_type: fila.mime_type
    };

    // Renombrar dentro del mismo directorio es atómico en el mismo volumen.
    // Permite restaurar el PDF si alguna operación SQL o el commit falla.
    rutaTemporal = path.join(
      directorioDocumentos,
      `.eliminando-${crypto.randomUUID()}.tmp`
    );

    try {
      await fs.rename(rutaOriginal, rutaTemporal);
      archivoMovido = true;
    } catch (error) {
      if (error.code === 'ENOENT') {
        pdfYaNoExistia = true;
      } else {
        throw error;
      }
    }

    // Se elimina primero el acta para respetar la llave foránea hacia documentos.
    await connection.execute(
      `DELETE FROM actas WHERE id_acta = ?`,
      [idSeguro]
    );

    await connection.execute(
      `DELETE FROM documentos WHERE id_documento = ?`,
      [fila.id_documento]
    );

    const valorNuevoPendiente = {
      eliminado_permanentemente: true,
      id_acta: idSeguro,
      id_documento: Number(fila.id_documento),
      pdf_eliminado_fisicamente: pdfYaNoExistia ? true : null
    };

    const [evento] = await connection.execute(
      `INSERT INTO bitacora_auditoria (
        id_usuario,
        accion,
        entidad_afectada,
        id_registro,
        valor_anterior,
        valor_nuevo,
        detalle
      ) VALUES (?, 'ELIMINAR', 'actas', ?, ?, ?, ?)`,
      [
        actorSeguro,
        idSeguro,
        JSON.stringify(snapshotActa),
        JSON.stringify(valorNuevoPendiente),
        'Eliminación física administrativa del acta. Se conserva el snapshot histórico y los metadatos del documento en la bitácora; la purga física del PDF se confirma después del commit.'
      ]
    );

    idEventoAuditoria = evento.insertId;

    await connection.commit();
    transaccionIniciada = false;

    // El registro y metadatos ya fueron eliminados de MySQL; ahora se destruye
    // el archivo temporal. Si falla, se informa explícitamente para no afirmar
    // que el PDF fue borrado cuando aún existe en almacenamiento.
    let pdfEliminadoFisicamente = pdfYaNoExistia;
    let advertencia = null;

    if (archivoMovido) {
      try {
        await fs.unlink(rutaTemporal);
        pdfEliminadoFisicamente = true;
      } catch (error) {
        pdfEliminadoFisicamente = false;
        advertencia = 'El acta y sus metadatos fueron eliminados, pero no fue posible borrar el PDF temporal. Se requiere limpieza manual del archivo de cuarentena.';
        console.error('No se pudo purgar el PDF temporal:', error);
      }
    }

    // Completa el resultado real de la purga en el mismo evento de auditoría.
    
    // Registra el resultado final mediante un NUEVO evento.
    // La bitácora es inmutable: nunca se utiliza UPDATE.
    try {
      const detalleResultado = pdfEliminadoFisicamente
        ? 'Resultado final: eliminación administrativa del acta y del PDF completada. Se conserva el snapshot histórico en la bitácora.'
        : 'Resultado final: acta y metadatos eliminados de MySQL, pero el PDF permanece en cuarentena temporal y requiere purga manual.';

      const valorNuevoFinal = {
        resultado: 'RESULTADO_FINAL',
        id_evento_origen: Number(idEventoAuditoria),
        eliminado_permanentemente: true,
        id_acta: idSeguro,
        id_documento: Number(fila.id_documento),
        pdf_eliminado_fisicamente: pdfEliminadoFisicamente
      };

      await pool.execute(
        `INSERT INTO bitacora_auditoria (
          id_usuario,
          accion,
          entidad_afectada,
          id_registro,
          valor_anterior,
          valor_nuevo,
          detalle
        ) VALUES (?, 'ELIMINAR', 'actas', ?, NULL, ?, ?)`,
        [
          actorSeguro,
          idSeguro,
          JSON.stringify(valorNuevoFinal),
          detalleResultado
        ]
      );

    } catch (error) {
      console.error(
        'No se pudo registrar el resultado final en auditoría:',
        error
      );

      advertencia = advertencia ||
        'La eliminación se completó, pero no fue posible registrar el evento final de auditoría.';
    }


    return {
      eliminado: true,
      id_acta: idSeguro,
      id_documento: Number(fila.id_documento),
      pdf_eliminado_fisicamente: pdfEliminadoFisicamente,
      advertencia
    };
  } catch (error) {
    if (connection && transaccionIniciada) {
      try {
        await connection.rollback();
      } catch (rollbackError) {
        console.error('Error al revertir la eliminación del acta:', rollbackError);
      } finally {
        transaccionIniciada = false;
      }
    }

    // Si no se confirmó la transacción, restaura el PDF a su ubicación original.
    if (archivoMovido && rutaTemporal && rutaOriginal) {
      try {
        await fs.rename(rutaTemporal, rutaOriginal);
      } catch (restauracionError) {
        console.error(
          'CRÍTICO: no se pudo restaurar el PDF después de cancelar la eliminación:',
          restauracionError
        );
      }
    }

    throw error;
  } finally {
    if (connection) connection.release();
  }
};


module.exports = {
  guardarActa,
  listarActas,
  obtenerActaPorId,
  obtenerDocumentoActa,
  actualizarActaPorAdministrador,
  eliminarActaPermanentemente
};
