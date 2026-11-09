const bcrypt = require('bcrypt');
const jwt = require('jsonwebtoken');
const crypto = require('crypto');
const { pool } = require('../config/database');

const DURACION_ABSOLUTA_HORAS = 8;

async function registrarEventoAutenticacion(connection, { idUsuario = null, accion, detalle }) {
  await connection.execute(
    `INSERT INTO bitacora_auditoria (
      id_usuario, accion, entidad_afectada, id_registro,
      valor_anterior, valor_nuevo, detalle
    ) VALUES (?, ?, 'autenticacion', NULL, NULL, NULL, ?)`,
    [idUsuario, accion, detalle]
  );
}

async function registrarIntentoFallido({ idUsuario = null, detalle }) {
  let connection;
  try {
    connection = await pool.getConnection();
    await registrarEventoAutenticacion(connection, {
      idUsuario,
      accion: 'LOGIN_FALLIDO',
      detalle
    });
  } catch (error) {
    console.error('No fue posible registrar el intento fallido de acceso:', error);
  } finally {
    if (connection) connection.release();
  }
}

async function login(req, res) {
  const identificador = String(req.body?.usuario ?? '').trim();
  const password = req.body?.password;

  if (!identificador || typeof password !== 'string' || !password) {
    return res.status(400).json({ success: false, message: 'Usuario y contraseña son obligatorios.' });
  }

  try {
    const [usuarios] = await pool.execute(
      `SELECT u.id_usuario, u.id_rol, u.nombre_completo, u.usuario, u.correo,
              u.password_hash, u.activo, r.nombre AS rol
       FROM usuarios u
       INNER JOIN roles r ON r.id_rol = u.id_rol
       WHERE u.usuario = ? OR u.correo = ?
       LIMIT 1`,
      [identificador, identificador]
    );

    if (!usuarios.length) {
      const identificadorSeguro = identificador.replace(/[\r\n\t]/g, ' ').slice(0, 150);
      await registrarIntentoFallido({
        idUsuario: null,
        detalle: `Intento de acceso rechazado: cuenta no encontrada. Identificador proporcionado: ${identificadorSeguro}.`
      });
      return res.status(401).json({ success: false, message: 'Credenciales incorrectas.' });
    }

    const cuenta = usuarios[0];
    if (Number(cuenta.activo) !== 1) {
      await registrarIntentoFallido({ idUsuario: cuenta.id_usuario, detalle: 'Intento de acceso rechazado: cuenta desactivada.' });
      return res.status(403).json({ success: false, message: 'La cuenta está desactivada.' });
    }

    const passwordValida = await bcrypt.compare(password, cuenta.password_hash);
    if (!passwordValida) {
      await registrarIntentoFallido({ idUsuario: cuenta.id_usuario, detalle: 'Intento de acceso fallido: contraseña incorrecta.' });
      return res.status(401).json({ success: false, message: 'Credenciales incorrectas.' });
    }

    const [permisos] = await pool.execute(
      `SELECT p.clave
       FROM roles_permisos rp
       INNER JOIN permisos p ON p.id_permiso = rp.id_permiso
       WHERE rp.id_rol = ?
       ORDER BY p.clave`,
      [cuenta.id_rol]
    );
    const listaPermisos = permisos.map((p) => p.clave);

    const idSesion = crypto.randomUUID();
    const token = jwt.sign(
      { id_usuario: cuenta.id_usuario, sid: idSesion },
      process.env.JWT_SECRET,
      { expiresIn: `${DURACION_ABSOLUTA_HORAS}h` }
    );

    let connection;
    try {
      connection = await pool.getConnection();
      await connection.beginTransaction();

      await connection.execute(
        `INSERT INTO sesiones_usuario
          (id_sesion, id_usuario, ultima_actividad, expira_en)
         VALUES (?, ?, NOW(), DATE_ADD(NOW(), INTERVAL 8 HOUR))`,
        [idSesion, cuenta.id_usuario]
      );
      await connection.execute(
        'UPDATE usuarios SET ultimo_acceso = NOW() WHERE id_usuario = ?',
        [cuenta.id_usuario]
      );
      await registrarEventoAutenticacion(connection, {
        idUsuario: cuenta.id_usuario,
        accion: 'LOGIN_EXITOSO',
        detalle: 'Inicio de sesión exitoso.'
      });

      await connection.commit();
    } catch (error) {
      if (connection) {
        try { await connection.rollback(); } catch (rollbackError) {
          console.error('Error al revertir el inicio de sesión:', rollbackError);
        }
      }
      throw error;
    } finally {
      if (connection) connection.release();
    }

    return res.json({
      success: true,
      message: 'Inicio de sesión correcto.',
      token,
      usuario: {
        id_usuario: cuenta.id_usuario,
        nombre_completo: cuenta.nombre_completo,
        usuario: cuenta.usuario,
        correo: cuenta.correo,
        rol: cuenta.rol,
        permisos: listaPermisos
      }
    });
  } catch (error) {
    console.error('Error en login:', error);
    return res.status(500).json({ success: false, message: 'No fue posible iniciar sesión.' });
  }
}

async function perfil(req, res) {
  return res.json({ success: true, usuario: req.usuario });
}

// El middleware verifica y actualiza ultima_actividad en cada petición protegida.
async function actividad(req, res) {
  return res.json({ success: true, mensaje: 'Actividad de sesión actualizada.' });
}

async function logout(req, res) {
  let connection;
  const cierrePorInactividad = req.body?.motivo === 'INACTIVIDAD';
  const motivoRevocacion = cierrePorInactividad ? 'INACTIVIDAD' : 'CIERRE_MANUAL';
  try {
    connection = await pool.getConnection();
    await connection.beginTransaction();
    const [resultado] = await connection.execute(
      `UPDATE sesiones_usuario
       SET revocada_en = NOW(), motivo_revocacion = ?
       WHERE id_sesion = ? AND revocada_en IS NULL`,
      [motivoRevocacion, req.sesion.id_sesion]
    );
    if (resultado.affectedRows === 1) {
      await registrarEventoAutenticacion(connection, {
        idUsuario: req.usuario.id_usuario,
        accion: cierrePorInactividad ? 'SESION_EXPIRADA_INACTIVIDAD' : 'LOGOUT',
        detalle: cierrePorInactividad
          ? 'Sesión cerrada por 30 minutos sin interacción del usuario.'
          : 'Cierre de sesión solicitado por el usuario.'
      });
    }
    await connection.commit();
    return res.json({ success: true, mensaje: 'Sesión cerrada correctamente.' });
  } catch (error) {
    if (connection) {
      try { await connection.rollback(); } catch (_) { /* no-op */ }
    }
    console.error('Error al cerrar sesión:', error);
    return res.status(500).json({ success: false, message: 'No fue posible cerrar la sesión en el servidor.' });
  } finally {
    if (connection) connection.release();
  }
}

module.exports = { login, perfil, actividad, logout };
