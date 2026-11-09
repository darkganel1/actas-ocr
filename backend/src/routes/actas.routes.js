const express = require('express');
const multer = require('multer');
const rateLimit = require('express-rate-limit');

const router = express.Router();
const { verificarToken } = require('../middlewares/auth.middleware');
const { requierePermiso } = require('../middlewares/permisos.middleware');

const {
  crearActa,
  consultarActas,
  consultarActa,
  visualizarDocumento
} = require('../controllers/actas.controller');

const upload = multer({
  storage: multer.memoryStorage(),
  limits: {
    fileSize: 20 * 1024 * 1024,
    files: 1,
    fields: 5,
    fieldSize: 2 * 1024 * 1024
  }
});

const altaActaLimiter = rateLimit({
  windowMs: 15 * 60 * 1000,
  limit: 10,
  standardHeaders: 'draft-7',
  legacyHeaders: false,
  message: {
    success: false,
    mensaje: 'Se alcanzó el límite de registros desde esta conexión. Intenta más tarde.'
  }
});

const recibirDocumento = (req, res, next) => {
  upload.single('documento')(req, res, (error) => {
    if (!error) return next();

    if (error instanceof multer.MulterError) {
      const status = error.code === 'LIMIT_FILE_SIZE' ? 413 : 400;
      return res.status(status).json({
        success: false,
        mensaje: error.code === 'LIMIT_FILE_SIZE'
          ? 'El archivo supera el límite permitido de 20 MB.'
          : 'La carga del documento no es válida.'
      });
    }

    return next(error);
  });
};

// Registrar acta.
router.post(
  '/',
  verificarToken,
  requierePermiso('actas.capturar'),
  altaActaLimiter,
  recibirDocumento,
  crearActa
);

// Listar y buscar actas.
router.get(
  '/',
  verificarToken,
  requierePermiso('actas.consultar'),
  consultarActas
);

// Visualizar PDF dentro del navegador.
router.get(
  '/:id/documento',
  verificarToken,
  requierePermiso('documentos.ver'),
  visualizarDocumento
);

// Consultar expediente individual.
router.get(
  '/:id',
  verificarToken,
  requierePermiso('actas.consultar'),
  consultarActa
);

module.exports = router;
