const { pool } = require('../config/database');
const bcrypt = require('bcrypt');

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

// Listar usuarios
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

    res.json({
      success: true,
      usuarios
    });
  } catch (error) {
    console.error('Error al listar usuarios:', error);
    res.status(500).json({
      success: false,
      mensaje: 'Error al consultar los usuarios.'
    });
  }
};

// Consultar un usuario
const obtenerUsuario = async (req, res) => {
  try {
    const { id } = req.params;

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
      return res.status(404).json({
        success: false,
        mensaje: 'Usuario no encontrado.'
      });
    }

    res.json({
      success: true,
      usuario: usuarios[0]
    });
  } catch (error) {
    console.error('Error al consultar usuario:', error);
    res.status(500).json({
      success: false,
      mensaje: 'Error al consultar el usuario.'
    });
  }
};

// Crear usuario Capturista y auditar la operación en la misma transacción.
const crearUsuario = async (req, res) => {
  const {
    nombre_completo,
    usuario,
    correo,
    password
  } = req.body;

  if (!nombre_completo || !usuario || !correo || !password) {
    return res.status(400).json({
      success: false,
      mensaje: 'Todos los campos son obligatorios.'
    });
  }

  if (typeof password !== 'string' || password.length < 12) {
    return res.status(400).json({
      success: false,
      mensaje: 'La contraseña debe tener al menos 12 caracteres.'
    });
  }

  let connection;
  let transaccionIniciada = false;

  try {
    const nombre = nombre_completo.trim();
    const username = usuario.trim();
    const email = correo.trim().toLowerCase();

    const [existentes] = await pool.query(
      `SELECT id_usuario
       FROM usuarios
       WHERE usuario = ? OR correo = ?
       LIMIT 1`,
      [username, email]
    );

    if (existentes.length > 0) {
      return res.status(409).json({
        success: false,
        mensaje: 'El nombre de usuario o correo ya está registrado.'
      });
    }

    const [roles] = await pool.query(
      `SELECT id_rol FROM roles WHERE nombre = 'Capturista' LIMIT 1`
    );

    if (roles.length === 0) {
      return res.status(500).json({
        success: false,
        mensaje: 'No existe el rol Capturista en la base de datos.'
      });
    }

    const passwordHash = await bcrypt.hash(password, 12);

    connection = await pool.getConnection();
    await connection.beginTransaction();
    transaccionIniciada = true;

    const [resultado] = await connection.query(`
      INSERT INTO usuarios (
        id_rol,
        nombre_completo,
        usuario,
        correo,
        password_hash,
        activo
      )
      VALUES (?, ?, ?, ?, ?, 1)
    `, [
      roles[0].id_rol,
      nombre,
      username,
      email,
      passwordHash
    ]);

    const idNuevoUsuario = resultado.insertId;

    await registrarEventoUsuario(connection, {
      idUsuarioActor: req.usuario.id_usuario,
      accion: 'CREAR',
      idUsuarioAfectado: idNuevoUsuario,
      valorAnterior: null,
      // Minimizar datos personales en la bitácora. Nunca guardar password/hash.
      valorNuevo: {
        id_usuario: idNuevoUsuario,
        usuario: username,
        rol: 'Capturista',
        activo: true
      },
      detalle: 'Creación de cuenta Capturista por un administrador.'
    });

    await connection.commit();
    transaccionIniciada = false;

    return res.status(201).json({
      success: true,
      mensaje: 'Usuario Capturista creado correctamente.',
      id_usuario: idNuevoUsuario
    });
  } catch (error) {
    if (connection && transaccionIniciada) {
      await connection.rollback();
      transaccionIniciada = false;
    }

    console.error('Error al crear usuario:', error);

    if (error.code === 'ER_DUP_ENTRY') {
      return res.status(409).json({
        success: false,
        mensaje: 'El usuario o correo ya está registrado.'
      });
    }

    return res.status(500).json({
      success: false,
      mensaje: 'Error al crear el usuario.'
    });
  } finally {
    if (connection) connection.release();
  }
};

// Activar o desactivar usuario y registrar el cambio atómicamente.
const cambiarEstadoUsuario = async (req, res) => {
  const { id } = req.params;
  const { activo } = req.body;

  if (!/^\d+$/.test(String(id)) || Number(id) <= 0) {
    return res.status(400).json({
      success: false,
      mensaje: 'El identificador de usuario no es válido.'
    });
  }

  if (typeof activo !== 'boolean' && activo !== 0 && activo !== 1) {
    return res.status(400).json({
      success: false,
      mensaje: 'El estado debe ser true o false.'
    });
  }

  const nuevoEstado = activo ? 1 : 0;
  const idAdministrador = Number(req.usuario.id_usuario);
  const idUsuarioAfectado = Number(id);

  if (idUsuarioAfectado === idAdministrador && nuevoEstado === 0) {
    return res.status(400).json({
      success: false,
      mensaje: 'No puedes desactivar tu propia cuenta.'
    });
  }

  let connection;
  let transaccionIniciada = false;

  try {
    connection = await pool.getConnection();
    await connection.beginTransaction();
    transaccionIniciada = true;

    // Bloquea el registro para evitar cambios concurrentes inconsistentes.
    const [usuarios] = await connection.query(
      `SELECT id_usuario, usuario, activo
       FROM usuarios
       WHERE id_usuario = ?
       LIMIT 1
       FOR UPDATE`,
      [idUsuarioAfectado]
    );

    if (usuarios.length === 0) {
      await connection.rollback();
      transaccionIniciada = false;
      return res.status(404).json({
        success: false,
        mensaje: 'Usuario no encontrado.'
      });
    }

    const usuarioActual = usuarios[0];
    const estadoAnterior = Number(usuarioActual.activo) === 1 ? 1 : 0;

    if (estadoAnterior === nuevoEstado) {
      await connection.commit();
      transaccionIniciada = false;
      return res.json({
        success: true,
        mensaje: nuevoEstado
          ? 'El usuario ya se encontraba activo.'
          : 'El usuario ya se encontraba desactivado.'
      });
    }

    await connection.query(
      `UPDATE usuarios SET activo = ? WHERE id_usuario = ?`,
      [nuevoEstado, idUsuarioAfectado]
    );

    const accion = nuevoEstado === 1 ? 'ACTIVAR' : 'DESACTIVAR';

    await registrarEventoUsuario(connection, {
      idUsuarioActor: idAdministrador,
      accion,
      idUsuarioAfectado,
      valorAnterior: { activo: Boolean(estadoAnterior) },
      valorNuevo: { activo: Boolean(nuevoEstado) },
      detalle: nuevoEstado === 1
        ? 'Activación de cuenta por un administrador.'
        : 'Desactivación de cuenta por un administrador.'
    });

    await connection.commit();
    transaccionIniciada = false;

    return res.json({
      success: true,
      mensaje: nuevoEstado
        ? 'Usuario activado correctamente.'
        : 'Usuario desactivado correctamente.'
    });
  } catch (error) {
    if (connection && transaccionIniciada) {
      await connection.rollback();
      transaccionIniciada = false;
    }

    console.error('Error al cambiar estado:', error);
    return res.status(500).json({
      success: false,
      mensaje: 'Error al actualizar el estado del usuario.'
    });
  } finally {
    if (connection) connection.release();
  }
};

module.exports = {
  listarUsuarios,
  obtenerUsuario,
  crearUsuario,
  cambiarEstadoUsuario
};
