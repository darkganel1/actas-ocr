
const { pool } = require('../config/database');

const listarEventos = async ({
  usuario = '',
  accion = '',
  entidad = '',
  desde = '',
  hasta = '',
  pagina = 1,
  limite = 20
}) => {
  const paginaSegura = Math.max(1, parseInt(pagina, 10) || 1);
  const limiteSeguro = Math.min(100, Math.max(1, parseInt(limite, 10) || 20));
  const offset = (paginaSegura - 1) * limiteSeguro;

  const condiciones = [];
  const parametros = [];

  if (usuario) {
    condiciones.push(`(
      u.nombre_completo LIKE ?
      OR u.usuario LIKE ?
    )`);
    parametros.push(`%${usuario}%`, `%${usuario}%`);
  }

  if (accion) {
    condiciones.push('b.accion = ?');
    parametros.push(accion);
  }

  if (entidad) {
    condiciones.push('b.entidad_afectada = ?');
    parametros.push(entidad);
  }

  if (desde) {
    condiciones.push('b.fecha_evento >= ?');
    parametros.push(`${desde} 00:00:00`);
  }

  if (hasta) {
    condiciones.push('b.fecha_evento <= ?');
    parametros.push(`${hasta} 23:59:59`);
  }

  const where = condiciones.length
    ? `WHERE ${condiciones.join(' AND ')}`
    : '';

  const [conteo] = await pool.execute(
    `SELECT COUNT(*) AS total
     FROM bitacora_auditoria b
LEFT JOIN usuarios u ON u.id_usuario = b.id_usuario
     ${where}`,
    parametros
  );

  const [eventos] = await pool.execute(
    `SELECT
       b.id_evento,
       b.id_usuario,
       u.nombre_completo,
       u.usuario,
       b.accion,
       b.entidad_afectada,
       b.id_registro,
       b.fecha_evento,
       b.valor_anterior,
       b.valor_nuevo,
       b.detalle
     FROM bitacora_auditoria b
LEFT JOIN usuarios u ON u.id_usuario = b.id_usuario
     ${where}
     ORDER BY b.fecha_evento DESC, b.id_evento DESC
     LIMIT ? OFFSET ?`,
    [...parametros, limiteSeguro, offset]
  );

  return {
    eventos,
    paginacion: {
      pagina: paginaSegura,
      limite: limiteSeguro,
      total: conteo[0].total,
      totalPaginas: Math.ceil(conteo[0].total / limiteSeguro)
    }
  };
};

const obtenerEvento = async (id) => {
  const [eventos] = await pool.execute(
    `SELECT
       b.id_evento,
       b.id_usuario,
       u.nombre_completo,
       u.usuario,
       b.accion,
       b.entidad_afectada,
       b.id_registro,
       b.fecha_evento,
       b.valor_anterior,
       b.valor_nuevo,
       b.detalle
     FROM bitacora_auditoria b
LEFT JOIN usuarios u ON u.id_usuario = b.id_usuario
     WHERE b.id_evento = ?
     LIMIT 1`,
    [id]
  );

  return eventos[0] || null;
};

module.exports = {
  listarEventos,
  obtenerEvento
};
