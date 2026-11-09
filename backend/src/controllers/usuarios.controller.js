const { pool } = require('../config/database');
const bcrypt = require('bcrypt');

const idValido = (id) => /^\d+$/.test(String(id)) && Number(id) > 0;

/**
 * Registra una operación administrativa sobre usuarios.
 * Nunca incluir contraseñas ni hashes en valor_anterior/valor_nuevo.
 */
const registrarEventoUsuario = async (
  connection,
  {
    idUsuarioActor,
    accion,
    idUsuarioAfectado,
    valorAnterior = null,
    valorNuevo = null,
    detalle
  }
) => {
  await connection.query(
    `INSERT INTO bitacora_auditoria (
      id_usuario,
      accion,
      entidad_afectada,
      id_registro,
      valor_anterior,
      valor_nuevo,
      detalle
    ) VALUES (?, ?, 'usuarios', ?, ?, ?, ?)`,
    [
      idUsuarioActor,
      accion,
      idUsuarioAfectado,
      valorAnterior === null ? null : JSON.stringify(valorAnterior),
      valorNuevo === null ? null : JSON.stringify(valorNuevo),
      detalle
    ]
  );
};

// Listar usuarios. Nunca devuelve password_hash.
const listarUsuarios = async (req, res) => {
  try {
    const [usuarios] = await pool.query(`
      SELECT
        u.id_usuario,
        u.nombre_completo,
        u.usuario,
        u.correo,
        u.activo,
        u.fecha_creacion,
        u.ultimo_acceso,
        r.nombre AS rol
      FROM usuarios u
      INNER JOIN roles r ON r.id_rol = u.id_rol
      ORDER BY u.id_usuario DESC
    `);

    return res.json({ success: true, usuarios });
  } catch (error) {
    console.error('Error al listar usuarios:', error);
    return res.status(500).json({
      success: false,
      mensaje: 'Error al consultar los usuarios.'
    });
  }
};

// Consultar un usuario.
const obtenerUsuario = async (req, res) => {
  const { id } = req.params;
  if (!idValido(id)) {
    return res.status(400).json({ success: false, mensaje: 'El identificador no es válido.' });
  }

  try {
    const [usuarios] = await pool.query(`
      SELECT
        u.id_usuario,
        u.nombre_completo,
        u.usuario,
        u.correo,
        u.activo,
        u.fecha_creacion,
        u.ultimo_acceso,
        r.nombre AS rol
      FROM usuarios u
      INNER JOIN roles r ON r.id_rol = u.id_rol
      WHERE u.id_usuario = ?
      LIMIT 1
    `, [id]);

    if (usuarios.length === 0) {
      return res.status(404).json({ success: false, mensaje: 'Usuario no encontrado.' });
    }

    return res.json({ success: true, usuario: usuarios[0] });
  } catch (error) {
    console.error('Error al consultar usuario:', error);
    return res.status(500).json({ success: false, mensaje: 'Error al consultar el usuario.' });
  }
};

// Crear usuario Capturista y auditar la operación en la misma transacción.
const crearUsuario = async (req, res) => {
  const { nombre_completo, usuario, correo, password } = req.body;

  if (!nombre_completo || !usuario || !correo || !password) {
    return res.status(400).json({ success: false, mensaje: 'Todos los campos son obligatorios.' });
  }
  if (typeof password !== 'string' || password.length < 12) {
    return res.status(400).json({ success: false, mensaje: 'La contraseña debe tener al menos 12 caracteres.' });
  }

  let connection;
  let transaccionIniciada = false;

  try {
    const nombre = String(nombre_completo).trim();
    const username = String(usuario).trim();
    const email = String(correo).trim().toLowerCase();

    if (!nombre || !username || !email) {
      return res.status(400).json({ success: false, mensaje: 'Nombre, usuario y correo son obligatorios.' });
    }

    const [existentes] = await pool.query(
      `SELECT id_usuario FROM usuarios WHERE usuario = ? OR correo = ? LIMIT 1`,
      [username, email]
    );
    if (existentes.length > 0) {
      return res.status(409).json({ success: false, mensaje: 'El nombre de usuario o correo ya está registrado.' });
    }

    const [roles] = await pool.query(
      `SELECT id_rol FROM roles WHERE nombre = 'Capturista' LIMIT 1`
    );
    if (roles.length === 0) {
      return res.status(500).json({ success: false, mensaje: 'No existe el rol Capturista en la base de datos.' });
    }

    const passwordHash = await bcrypt.hash(password, 12);
    connection = await pool.getConnection();
    await connection.beginTransaction();
    transaccionIniciada = true;

    const [resultado] = await connection.query(`
      INSERT INTO usuarios (id_rol, nombre_completo, usuario, correo, password_hash, activo)
      VALUES (?, ?, ?, ?, ?, 1)
    `, [roles[0].id_rol, nombre, username, email, passwordHash]);

    const idNuevoUsuario = resultado.insertId;
    await registrarEventoUsuario(connection, {
      idUsuarioActor: req.usuario.id_usuario,
      accion: 'CREAR',
      idUsuarioAfectado: idNuevoUsuario,
      valorNuevo: { id_usuario: idNuevoUsuario, nombre_completo: nombre, usuario: username, correo: email, rol: 'Capturista', activo: true },
      detalle: 'Creación de cuenta Capturista por un administrador.'
    });

    await connection.commit();
    transaccionIniciada = false;
    return res.status(201).json({ success: true, mensaje: 'Usuario Capturista creado correctamente.', id_usuario: idNuevoUsuario });
  } catch (error) {
    if (connection && transaccionIniciada) await connection.rollback();
    console.error('Error al crear usuario:', error);
    if (error.code === 'ER_DUP_ENTRY') {
      return res.status(409).json({ success: false, mensaje: 'El usuario o correo ya está registrado.' });
    }
    return res.status(500).json({ success: false, mensaje: 'Error al crear el usuario.' });
  } finally {
    if (connection) connection.release();
  }
};

// Modificar datos básicos de cuenta. El rol y el estado no se modifican aquí.
const actualizarUsuario = async (req, res) => {
  const { id } = req.params;
  const { nombre_completo, usuario, correo } = req.body;

  if (!idValido(id)) {
    return res.status(400).json({ success: false, mensaje: 'El identificador de usuario no es válido.' });
  }
  if (
    typeof nombre_completo !== 'string' || !nombre_completo.trim() ||
    typeof usuario !== 'string' || !usuario.trim() ||
    typeof correo !== 'string' || !correo.trim()
  ) {
    return res.status(400).json({ success: false, mensaje: 'Nombre, usuario y correo son obligatorios.' });
  }

  const idAfectado = Number(id);
  const nombreNuevo = nombre_completo.trim();
  const usuarioNuevo = usuario.trim();
  const correoNuevo = correo.trim().toLowerCase();
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(correoNuevo)) {
    return res.status(400).json({ success: false, mensaje: 'El correo electrónico no tiene un formato válido.' });
  }

  let connection;
  let transaccionIniciada = false;
  try {
    connection = await pool.getConnection();
    await connection.beginTransaction();
    transaccionIniciada = true;

    const [filas] = await connection.query(
      `SELECT id_usuario, nombre_completo, usuario, correo FROM usuarios WHERE id_usuario = ? LIMIT 1 FOR UPDATE`,
      [idAfectado]
    );
    if (!filas.length) {
      await connection.rollback();
      transaccionIniciada = false;
      return res.status(404).json({ success: false, mensaje: 'Usuario no encontrado.' });
    }

    const anterior = filas[0];
    const [duplicados] = await connection.query(
      `SELECT id_usuario FROM usuarios WHERE (usuario = ? OR correo = ?) AND id_usuario <> ? LIMIT 1`,
      [usuarioNuevo, correoNuevo, idAfectado]
    );
    if (duplicados.length) {
      await connection.rollback();
      transaccionIniciada = false;
      return res.status(409).json({ success: false, mensaje: 'El nombre de usuario o correo ya pertenece a otra cuenta.' });
    }

    const nuevo = {
      nombre_completo: nombreNuevo,
      usuario: usuarioNuevo,
      correo: correoNuevo
    };
    const anteriorAudit = {
      nombre_completo: anterior.nombre_completo,
      usuario: anterior.usuario,
      correo: anterior.correo
    };

    const huboCambios = Object.keys(nuevo).some((campo) => String(nuevo[campo]) !== String(anteriorAudit[campo] ?? ''));
    if (!huboCambios) {
      await connection.commit();
      transaccionIniciada = false;
      return res.json({ success: true, mensaje: 'No se detectaron cambios en la cuenta.', usuario: { id_usuario: idAfectado, ...nuevo } });
    }

    await connection.query(
      `UPDATE usuarios SET nombre_completo = ?, usuario = ?, correo = ? WHERE id_usuario = ?`,
      [nombreNuevo, usuarioNuevo, correoNuevo, idAfectado]
    );

    await registrarEventoUsuario(connection, {
      idUsuarioActor: req.usuario.id_usuario,
      accion: 'ACTUALIZAR',
      idUsuarioAfectado: idAfectado,
      valorAnterior: anteriorAudit,
      valorNuevo: nuevo,
      detalle: 'Actualización de datos de cuenta por un administrador.'
    });

    await connection.commit();
    transaccionIniciada = false;
    return res.json({ success: true, mensaje: 'Datos del usuario actualizados correctamente.', usuario: { id_usuario: idAfectado, ...nuevo } });
  } catch (error) {
    if (connection && transaccionIniciada) await connection.rollback();
    console.error('Error al actualizar usuario:', error);
    if (error.code === 'ER_DUP_ENTRY') {
      return res.status(409).json({ success: false, mensaje: 'El nombre de usuario o correo ya está registrado.' });
    }
    return res.status(500).json({ success: false, mensaje: 'Error al actualizar los datos del usuario.' });
  } finally {
    if (connection) connection.release();
  }
};

// Restablecimiento administrativo de contraseña. La clave nunca se escribe en la bitácora.
const restablecerPasswordUsuario = async (req, res) => {
  const { id } = req.params;
  const { password_nueva } = req.body;

  if (!idValido(id)) {
    return res.status(400).json({ success: false, mensaje: 'El identificador de usuario no es válido.' });
  }
  if (typeof password_nueva !== 'string' || password_nueva.length < 12) {
    return res.status(400).json({ success: false, mensaje: 'La nueva contraseña debe tener al menos 12 caracteres.' });
  }

  let connection;
  let transaccionIniciada = false;
  try {
    connection = await pool.getConnection();
    await connection.beginTransaction();
    transaccionIniciada = true;

    const [filas] = await connection.query(
      `SELECT id_usuario, usuario FROM usuarios WHERE id_usuario = ? LIMIT 1 FOR UPDATE`,
      [Number(id)]
    );
    if (!filas.length) {
      await connection.rollback();
      transaccionIniciada = false;
      return res.status(404).json({ success: false, mensaje: 'Usuario no encontrado.' });
    }

    const hash = await bcrypt.hash(password_nueva, 12);
    await connection.query(
      `UPDATE usuarios SET password_hash = ? WHERE id_usuario = ?`,
      [hash, Number(id)]
    );

    // El restablecimiento administrativo invalida todas las sesiones del usuario.
    await connection.query(
      `UPDATE sesiones_usuario
       SET revocada_en = NOW(), motivo_revocacion = 'PASSWORD_RESTABLECIDA'
       WHERE id_usuario = ? AND revocada_en IS NULL`,
      [Number(id)]
    );

    await registrarEventoUsuario(connection, {
      idUsuarioActor: req.usuario.id_usuario,
      accion: 'RESTABLECER_PASSWORD',
      idUsuarioAfectado: Number(id),
      valorAnterior: null,
      valorNuevo: { password_actualizada: true },
      detalle: 'Restablecimiento administrativo de contraseña. El valor de la contraseña no se almacena.'
    });

    await connection.commit();
    transaccionIniciada = false;
    return res.json({ success: true, mensaje: 'Contraseña restablecida correctamente.' });
  } catch (error) {
    if (connection && transaccionIniciada) await connection.rollback();
    console.error('Error al restablecer contraseña:', error);
    return res.status(500).json({ success: false, mensaje: 'Error al restablecer la contraseña.' });
  } finally {
    if (connection) connection.release();
  }
};

// Activar o desactivar cuenta y proteger al último Administrador activo.
const cambiarEstadoUsuario = async (req, res) => {
  const { id } = req.params;
  const { activo } = req.body;

  if (!idValido(id)) {
    return res.status(400).json({ success: false, mensaje: 'El identificador de usuario no es válido.' });
  }
  if (typeof activo !== 'boolean' && activo !== 0 && activo !== 1) {
    return res.status(400).json({ success: false, mensaje: 'El estado debe ser true o false.' });
  }

  const nuevoEstado = activo ? 1 : 0;
  const idAdministrador = Number(req.usuario.id_usuario);
  const idUsuarioAfectado = Number(id);
  if (idUsuarioAfectado === idAdministrador && nuevoEstado === 0) {
    return res.status(400).json({ success: false, mensaje: 'No puedes desactivar tu propia cuenta.' });
  }

  let connection;
  let transaccionIniciada = false;
  try {
    connection = await pool.getConnection();
    await connection.beginTransaction();
    transaccionIniciada = true;

    // Serializa cambios de estado de Administradores para impedir desactivar al último.
    const [rolAdmin] = await connection.query(
      `SELECT id_rol FROM roles WHERE nombre = 'Administrador' LIMIT 1 FOR UPDATE`
    );
    if (!rolAdmin.length) {
      await connection.rollback();
      transaccionIniciada = false;
      return res.status(500).json({ success: false, mensaje: 'No existe el rol Administrador en la base de datos.' });
    }

    const [filas] = await connection.query(
      `SELECT u.id_usuario, u.usuario, u.activo, u.id_rol, r.nombre AS rol
       FROM usuarios u INNER JOIN roles r ON r.id_rol = u.id_rol
       WHERE u.id_usuario = ? LIMIT 1 FOR UPDATE`,
      [idUsuarioAfectado]
    );
    if (!filas.length) {
      await connection.rollback();
      transaccionIniciada = false;
      return res.status(404).json({ success: false, mensaje: 'Usuario no encontrado.' });
    }

    const usuarioActual = filas[0];
    const estadoAnterior = Number(usuarioActual.activo) === 1 ? 1 : 0;
    if (estadoAnterior === nuevoEstado) {
      await connection.commit();
      transaccionIniciada = false;
      return res.json({ success: true, mensaje: nuevoEstado ? 'El usuario ya se encontraba activo.' : 'El usuario ya se encontraba desactivado.' });
    }

    if (usuarioActual.rol === 'Administrador' && nuevoEstado === 0) {
      const [administradoresActivos] = await connection.query(
        `SELECT u.id_usuario FROM usuarios u
         WHERE u.id_rol = ? AND u.activo = 1
         FOR UPDATE`,
        [rolAdmin[0].id_rol]
      );
      if (administradoresActivos.length <= 1) {
        await connection.rollback();
        transaccionIniciada = false;
        return res.status(409).json({ success: false, mensaje: 'No se puede desactivar al último Administrador activo del sistema.' });
      }
    }

    await connection.query(`UPDATE usuarios SET activo = ? WHERE id_usuario = ?`, [nuevoEstado, idUsuarioAfectado]);

    if (nuevoEstado === 0) {
      // Desactivar una cuenta revoca todas sus sesiones en la misma transacción.
      await connection.query(
        `UPDATE sesiones_usuario
         SET revocada_en = NOW(), motivo_revocacion = 'CUENTA_DESACTIVADA'
         WHERE id_usuario = ? AND revocada_en IS NULL`,
        [idUsuarioAfectado]
      );
    }

    const accion = nuevoEstado === 1 ? 'ACTIVAR' : 'DESACTIVAR';
    await registrarEventoUsuario(connection, {
      idUsuarioActor: idAdministrador,
      accion,
      idUsuarioAfectado,
      valorAnterior: { activo: Boolean(estadoAnterior) },
      valorNuevo: { activo: Boolean(nuevoEstado) },
      detalle: nuevoEstado === 1 ? 'Activación de cuenta por un administrador.' : 'Desactivación de cuenta por un administrador.'
    });

    await connection.commit();
    transaccionIniciada = false;
    return res.json({ success: true, mensaje: nuevoEstado ? 'Usuario activado correctamente.' : 'Usuario desactivado correctamente.' });
  } catch (error) {
    if (connection && transaccionIniciada) await connection.rollback();
    console.error('Error al cambiar estado:', error);
    return res.status(500).json({ success: false, mensaje: 'Error al actualizar el estado del usuario.' });
  } finally {
    if (connection) connection.release();
  }
};

module.exports = {
  listarUsuarios,
  obtenerUsuario,
  crearUsuario,
  actualizarUsuario,
  restablecerPasswordUsuario,
  cambiarEstadoUsuario
};
