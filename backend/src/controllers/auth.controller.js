
const bcrypt = require('bcrypt');
const jwt = require('jsonwebtoken');
const { pool } = require('../config/database');

async function login(req, res) {
    try {
        const { usuario, password } = req.body;

        if (!usuario || !password) {
            return res.status(400).json({
                success: false,
                message: 'Usuario y contraseña son obligatorios.'
            });
        }

        const [usuarios] = await pool.execute(
            `SELECT
                u.id_usuario,
                u.nombre_completo,
                u.usuario,
                u.correo,
                u.password_hash,
                u.activo,
                r.nombre AS rol
             FROM usuarios u
             INNER JOIN roles r ON r.id_rol = u.id_rol
             WHERE u.usuario = ? OR u.correo = ?
             LIMIT 1`,
            [usuario.trim(), usuario.trim()]
        );

        if (!usuarios.length) {
            return res.status(401).json({
                success: false,
                message: 'Credenciales incorrectas.'
            });
        }

        const cuenta = usuarios[0];

        if (!cuenta.activo) {
            return res.status(403).json({
                success: false,
                message: 'La cuenta está desactivada.'
            });
        }

        const passwordValida = await bcrypt.compare(
            password,
            cuenta.password_hash
        );

        if (!passwordValida) {
            return res.status(401).json({
                success: false,
                message: 'Credenciales incorrectas.'
            });
        }

        const [permisos] = await pool.execute(
            `SELECT p.clave
             FROM roles_permisos rp
             INNER JOIN permisos p ON p.id_permiso = rp.id_permiso
             INNER JOIN usuarios u ON u.id_rol = rp.id_rol
             WHERE u.id_usuario = ?
             ORDER BY p.clave`,
            [cuenta.id_usuario]
        );

        const listaPermisos = permisos.map(p => p.clave);

        const token = jwt.sign(
            {
                id_usuario: cuenta.id_usuario
            },
            process.env.JWT_SECRET,
            {
                expiresIn: process.env.JWT_EXPIRES_IN || '8h'
            }
        );

        await pool.execute(
            'UPDATE usuarios SET ultimo_acceso = NOW() WHERE id_usuario = ?',
            [cuenta.id_usuario]
        );

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

        return res.status(500).json({
            success: false,
            message: 'No fue posible iniciar sesión.'
        });
    }
}

async function perfil(req, res) {
    return res.json({
        success: true,
        usuario: req.usuario
    });
}

module.exports = {
    login,
    perfil
};
