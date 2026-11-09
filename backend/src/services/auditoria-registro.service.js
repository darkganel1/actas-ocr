const { pool } = require('../config/database');

/**
 * Registra una operación sin copiar datos personales del acta.
 * El identificador del usuario proviene de req.usuario, validado por JWT.
 */
async function registrarEventoAuditoria({
  idUsuario,
  accion,
  entidad,
  idRegistro = null,
  valorAnterior = null,
  valorNuevo = null,
  detalle
}) {
  const actor = Number(idUsuario);

  if (!Number.isSafeInteger(actor) || actor <= 0) {
    throw new Error('No se pudo identificar al usuario que realiza la consulta.');
  }

  if (!accion || !entidad || !detalle) {
    throw new Error('Faltan datos obligatorios para registrar la auditoría.');
  }

  await pool.execute(
    `INSERT INTO bitacora_auditoria (
      id_usuario,
      accion,
      entidad_afectada,
      id_registro,
      valor_anterior,
      valor_nuevo,
      detalle
    ) VALUES (?, ?, ?, ?, ?, ?, ?)`,
    [
      actor,
      accion,
      entidad,
      idRegistro,
      valorAnterior === null ? null : JSON.stringify(valorAnterior),
      valorNuevo === null ? null : JSON.stringify(valorNuevo),
      detalle
    ]
  );
}

module.exports = { registrarEventoAuditoria };
