const express = require('express');
const router = express.Router();

const { verificarToken } = require('../middlewares/auth.middleware');
const requiereAdministrador = require('../middlewares/admin.middleware');
const {
  actualizarActa,
  eliminarActa
} = require('../controllers/actas.controller');

// Aplicar autenticación y rol solo a las rutas administrativas.
// Así los GET/POST siguen pasando al router normal de actas.
router.put('/:id', verificarToken, requiereAdministrador, actualizarActa);
router.delete('/:id', verificarToken, requiereAdministrador, eliminarActa);

module.exports = router;
