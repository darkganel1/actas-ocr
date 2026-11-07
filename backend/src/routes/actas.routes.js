
const express = require('express');
const multer = require('multer');

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
    files: 1
  }
});

// Registrar acta.
router.post(
  '/',
  verificarToken,
  requierePermiso('actas.capturar'),
  upload.single('documento'),
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
