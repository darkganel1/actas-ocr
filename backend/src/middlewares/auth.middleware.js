
const jwt = require('jsonwebtoken');
const { pool } = require('../config/database');

async function verificarToken(req, res, next) {
    try {
        const authorization = req.headers.authorization;

        if (!authorization || !authorization.startsWith('Bearer ')) {
            return res.status(401).json({
                success: false,
                message: 'Se requiere autenticación.'
            });
        }

        const token = authorization.split(' ')[1];

        const decoded = jwt.verify(token, process.env.JWT_SECRET);

        const [usuarios] = await pool.execute(
            `SELECT
                u.id_usuario,
                u.id_rol,
                u.nombre_completo,
                u.usuario,
                u.correo,
                u.activo,
                r.nombre AS rol
             FROM usuarios u
             INNER JOIN roles r ON r.id_rol = u.id_rol
             WHERE u.id_usuario = ?
             LIMIT 1`,
            [decoded.id_usuario]
        );

        if (!usuarios.length || !usuarios[0].activo) {
            return res.status(401).json({
                success: false,
                message: 'La cuenta no está disponible.'
            });
        }

        const cuenta = usuarios[0];

        const [permisos] = await pool.execute(
            `SELECT p.clave
             FROM roles_permisos rp
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
            permisos: permisos.map(p => p.clave)
        };

        next();

    } catch (error) {
        if (
            error.name === 'TokenExpiredError' ||
            error.name === 'JsonWebTokenError'
        ) {
            return res.status(401).json({
                success: false,
                message: 'Token inválido o vencido.'
            });
        }

        console.error('Error de autenticación:', error);

        return res.status(500).json({
            success: false,
            message: 'Error al validar la sesión.'
        });
    }
}

module.exports = {
    verificarToken
};
