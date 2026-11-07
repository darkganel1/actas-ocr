
function requierePermiso(clavePermiso) {
    return (req, res, next) => {
        if (!req.usuario) {
            return res.status(401).json({
                success: false,
                message: 'Usuario no autenticado.'
            });
        }

        if (!req.usuario.permisos.includes(clavePermiso)) {
            return res.status(403).json({
                success: false,
                message: 'No tienes permiso para realizar esta acción.'
            });
        }

        next();
    };
}

module.exports = {
    requierePermiso
};
