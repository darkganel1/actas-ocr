
const requiereAdministrador = (req, res, next) => {
  if (!req.usuario) {
    return res.status(401).json({
      success: false,
      mensaje: 'Debes iniciar sesión.'
    });
  }

  if (req.usuario.rol !== 'Administrador') {
    return res.status(403).json({
      success: false,
      mensaje: 'No tienes permisos para gestionar usuarios.'
    });
  }

  next();
};

module.exports = requiereAdministrador;
