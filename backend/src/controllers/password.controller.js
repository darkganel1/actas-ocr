const bcrypt = require('bcrypt');
const { pool } = require('../config/database');

// Cambio de contraseña por el propio usuario autenticado.
// No registra nunca la contraseña ni su hash en la bitácora.
const cambiarPassword = async (req, res) => {
  const { password_actual, password_nueva } = req.body;

  if (
    typeof password_actual !== 'string' || !password_actual ||
    typeof password_nueva !== 'string' || password_nueva.length < 12
  ) {
    return res.status(400).json({
      success: false,
      mensaje: 'Indica tu contraseña actual y una nueva contraseña de al menos 12 caracteres.'
    });
  }

  let connection;
  let transaccionIniciada = false;
  try {
    connection = await pool.getConnection();
    await connection.beginTransaction();
    transaccionIniciada = true;

    const [filas] = await connection.execute(
      `SELECT id_usuario, password_hash, activo
       FROM usuarios WHERE id_usuario = ? LIMIT 1 FOR UPDATE`,
      [req.usuario.id_usuario]
    );

    if (!filas.length || Number(filas[0].activo) !== 1) {
      await connection.rollback();
      transaccionIniciada = false;
      return res.status(403).json({ success: false, mensaje: 'La cuenta no está disponible.' });
    }

    const cuenta = filas[0];
    const passwordValida = await bcrypt.compare(password_actual, cuenta.password_hash);
    if (!passwordValida) {
      await connection.rollback();
      transaccionIniciada = false;
      return res.status(401).json({ success: false, mensaje: 'La contraseña actual es incorrecta.' });
    }

    const mismaPassword = await bcrypt.compare(password_nueva, cuenta.password_hash);
    if (mismaPassword) {
      await connection.rollback();
      transaccionIniciada = false;
      return res.status(400).json({ success: false, mensaje: 'La nueva contraseña debe ser diferente de la actual.' });
    }

    const hashNuevo = await bcrypt.hash(password_nueva, 12);
    await connection.execute(
      'UPDATE usuarios SET password_hash = ? WHERE id_usuario = ?',
      [hashNuevo, cuenta.id_usuario]
    );

    // Revoca las demás sesiones del usuario, pero conserva la sesión actual.
    await connection.execute(
      `UPDATE sesiones_usuario
       SET revocada_en = NOW(), motivo_revocacion = 'PASSWORD_CAMBIADA'
       WHERE id_usuario = ? AND id_sesion <> ? AND revocada_en IS NULL`,
      [cuenta.id_usuario, req.sesion.id_sesion]
    );

    await connection.execute(
      `INSERT INTO bitacora_auditoria (
        id_usuario, accion, entidad_afectada, id_registro,
        valor_anterior, valor_nuevo, detalle
      ) VALUES (?, 'CAMBIAR_PASSWORD', 'usuarios', ?, NULL, ?, ?)`,
      [
        cuenta.id_usuario,
        cuenta.id_usuario,
        JSON.stringify({ password_actualizada: true }),
        'Cambio de contraseña realizado por el propio usuario. El valor de la contraseña no se almacena.'
      ]
    );

    await connection.commit();
    transaccionIniciada = false;
    return res.json({ success: true, mensaje: 'Tu contraseña se actualizó correctamente.' });
  } catch (error) {
    if (connection && transaccionIniciada) await connection.rollback();
    console.error('Error al cambiar contraseña:', error);
    return res.status(500).json({ success: false, mensaje: 'No fue posible cambiar la contraseña.' });
  } finally {
    if (connection) connection.release();
  }
};

module.exports = { cambiarPassword };
