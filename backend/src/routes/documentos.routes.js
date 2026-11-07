
const express = require('express');
const multer = require('multer');

const router = express.Router();

const { verificarToken } = require('../middlewares/auth.middleware');
const { requierePermiso } = require('../middlewares/permisos.middleware');

const {
  procesarDocumento
} = require('../controllers/documentos.controller');

const upload = multer({
  storage: multer.memoryStorage(),
  limits: {
    fileSize: 20 * 1024 * 1024,
    files: 1
  }
});



router.post(
  '/procesar',
  verificarToken,
  requierePermiso('actas.capturar'),
  upload.single('documento'),
  procesarDocumento
);

module.exports = router;

