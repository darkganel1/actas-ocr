const jwt = require('jsonwebtoken');
const { pool } = require('../config/database');

async function revocarPorInactividad(idSesion, idUsuario) {
  let connection;
  try {
    connection = await pool.getConnection();
    await connection.beginTransaction();
    const [resultado] = await connection.execute(
      `UPDATE sesiones_usuario
       SET revocada_en = NOW(), motivo_revocacion = 'INACTIVIDAD'
       WHERE id_sesion = ? AND id_usuario = ? AND revocada_en IS NULL
         AND ultima_actividad <= DATE_SUB(NOW(), INTERVAL 30 MINUTE)`,
      [idSesion, idUsuario]
    );
    if (resultado.affectedRows === 1) {
      await connection.execute(
        `INSERT INTO bitacora_auditoria
          (id_usuario, accion, entidad_afectada, id_registro, valor_anterior, valor_nuevo, detalle)
         VALUES (?, 'SESION_EXPIRADA_INACTIVIDAD', 'autenticacion', NULL, NULL, NULL,
                 'Sesión cerrada por superar 30 minutos sin actividad.')`,
        [idUsuario]
      );
    }
    await connection.commit();
  } catch (error) {
    if (connection) {
      try { await connection.rollback(); } catch (_) { /* no-op */ }
    }
    console.error('No fue posible registrar la expiración por inactividad:', error);
  } finally {
    if (connection) connection.release();
  }
}

async function verificarToken(req, res, next) {
  try {
    const authorization = req.headers.authorization;
    if (!authorization || !authorization.startsWith('Bearer ')) {
      return res.status(401).json({ success: false, message: 'Se requiere autenticación.', code: 'AUTH_REQUIRED' });
    }

    const token = authorization.slice(7).trim();
    if (!token) {
      return res.status(401).json({ success: false, message: 'Token no proporcionado.', code: 'AUTH_REQUIRED' });
    }

    const decoded = jwt.verify(token, process.env.JWT_SECRET);
    if (!decoded.sid || !decoded.id_usuario) {
      return res.status(401).json({ success: false, message: 'La sesión anterior ya no es válida. Inicia sesión nuevamente.', code: 'SESSION_INVALID' });
    }

    const [sesiones] = await pool.execute(
      `SELECT id_sesion, id_usuario, revocada_en,
              (expira_en <= NOW()) AS vencida,
              (ultima_actividad <= DATE_SUB(NOW(), INTERVAL 30 MINUTE)) AS inactiva
       FROM sesiones_usuario
       WHERE id_sesion = ? AND id_usuario = ?
       LIMIT 1`,
      [decoded.sid, decoded.id_usuario]
    );

    if (!sesiones.length || sesiones[0].revocada_en) {
      return res.status(401).json({ success: false, message: 'La sesión fue cerrada o revocada. Inicia sesión nuevamente.', code: 'SESSION_REVOKED' });
    }

    const sesion = sesiones[0];
    if (Number(sesion.vencida) === 1) {
      await pool.execute(
        `UPDATE sesiones_usuario SET revocada_en = NOW(), motivo_revocacion = 'EXPIRACION'
         WHERE id_sesion = ? AND revocada_en IS NULL`,
        [decoded.sid]
      );
      return res.status(401).json({ success: false, message: 'La sesión alcanzó su duración máxima. Inicia sesión nuevamente.', code: 'SESSION_EXPIRED' });
    }

    if (Number(sesion.inactiva) === 1) {
      await revocarPorInactividad(decoded.sid, decoded.id_usuario);
      return res.status(401).json({ success: false, message: 'La sesión se cerró por 30 minutos de inactividad.', code: 'SESSION_IDLE_TIMEOUT' });
    }

    // Actualiza el reloj del servidor solo para una sesión vigente y no revocada.
    const [actividadResult] = await pool.execute(
      `UPDATE sesiones_usuario SET ultima_actividad = NOW()
       WHERE id_sesion = ? AND id_usuario = ? AND revocada_en IS NULL
         AND expira_en > NOW()
         AND ultima_actividad > DATE_SUB(NOW(), INTERVAL 30 MINUTE)`,
      [decoded.sid, decoded.id_usuario]
    );
    if (actividadResult.affectedRows !== 1) {
      return res.status(401).json({ success: false, message: 'La sesión ya no está vigente. Inicia sesión nuevamente.', code: 'SESSION_INVALID' });
    }

    const [usuarios] = await pool.execute(
      `SELECT u.id_usuario, u.id_rol, u.nombre_completo, u.usuario, u.correo, u.activo,
              r.nombre AS rol
       FROM usuarios u
       INNER JOIN roles r ON r.id_rol = u.id_rol
       WHERE u.id_usuario = ?
       LIMIT 1`,
      [decoded.id_usuario]
    );

    if (!usuarios.length || Number(usuarios[0].activo) !== 1) {
      await pool.execute(
        `UPDATE sesiones_usuario SET revocada_en = NOW(), motivo_revocacion = 'CUENTA_NO_DISPONIBLE'
         WHERE id_usuario = ? AND revocada_en IS NULL`,
        [decoded.id_usuario]
      );
      return res.status(401).json({ success: false, message: 'La cuenta no está disponible.', code: 'ACCOUNT_DISABLED' });
    }

    const cuenta = usuarios[0];
    const [permisos] = await pool.execute(
      `SELECT p.clave FROM roles_permisos rp
       INNER JOIN permisos p ON p.id_permiso = rp.id_permiso
       WHERE rp.id_rol = ?`,
      [cuenta.id_rol]
    );

    req.usuario = {
      id_usuario: cuenta.id_usuario,
      nombre_completo: cuenta.nombre_completo,
      usuario: cuenta.usuario,
      correo: cuenta.correo,
      rol: cuenta.rol,
      permisos: permisos.map((p) => p.clave)
    };
    req.sesion = { id_sesion: sesion.id_sesion };
    return next();
  } catch (error) {
    if (error.name === 'TokenExpiredError' || error.name === 'JsonWebTokenError') {
      return res.status(401).json({ success: false, message: 'Token inválido o vencido.', code: 'TOKEN_INVALID' });
    }
    console.error('Error de autenticación:', error);
    return res.status(500).json({ success: false, message: 'Error al validar la sesión.' });
  }
}

module.exports = { verificarToken };
