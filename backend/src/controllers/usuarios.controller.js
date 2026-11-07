
const { pool } = require('../config/database');
const bcrypt = require('bcrypt');

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

// Crear usuario Capturista
const crearUsuario = async (req, res) => {
  try {
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

    if (password.length < 12) {
      return res.status(400).json({
        success: false,
        mensaje: 'La contraseña debe tener al menos 12 caracteres.'
      });
    }

    const [existentes] = await pool.query(
      `SELECT id_usuario
       FROM usuarios
       WHERE usuario = ? OR correo = ?
       LIMIT 1`,
      [usuario.trim(), correo.trim().toLowerCase()]
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

    const [resultado] = await pool.query(`
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
      nombre_completo.trim(),
      usuario.trim(),
      correo.trim().toLowerCase(),
      passwordHash
    ]);

    res.status(201).json({
      success: true,
      mensaje: 'Usuario Capturista creado correctamente.',
      id_usuario: resultado.insertId
    });

  } catch (error) {
    console.error('Error al crear usuario:', error);

    if (error.code === 'ER_DUP_ENTRY') {
      return res.status(409).json({
        success: false,
        mensaje: 'El usuario o correo ya está registrado.'
      });
    }

    res.status(500).json({
      success: false,
      mensaje: 'Error al crear el usuario.'
    });
  }
};

// Activar o desactivar usuario
const cambiarEstadoUsuario = async (req, res) => {
  try {
    const { id } = req.params;
    const { activo } = req.body;

    if (typeof activo !== 'boolean' && activo !== 0 && activo !== 1) {
      return res.status(400).json({
        success: false,
        mensaje: 'El estado debe ser true o false.'
      });
    }

    const nuevoEstado = activo ? 1 : 0;
    const idAdministrador = req.usuario.id_usuario;

    if (Number(id) === Number(idAdministrador) && nuevoEstado === 0) {
      return res.status(400).json({
        success: false,
        mensaje: 'No puedes desactivar tu propia cuenta.'
      });
    }

    const [resultado] = await pool.query(
      `UPDATE usuarios SET activo = ? WHERE id_usuario = ?`,
      [nuevoEstado, id]
    );

    if (resultado.affectedRows === 0) {
      return res.status(404).json({
        success: false,
        mensaje: 'Usuario no encontrado.'
      });
    }

    res.json({
      success: true,
      mensaje: nuevoEstado
        ? 'Usuario activado correctamente.'
        : 'Usuario desactivado correctamente.'
    });

  } catch (error) {
    console.error('Error al cambiar estado:', error);
    res.status(500).json({
      success: false,
      mensaje: 'Error al actualizar el estado del usuario.'
    });
  }
};

module.exports = {
  listarUsuarios,
  obtenerUsuario,
  crearUsuario,
  cambiarEstadoUsuario
};
