const express = require('express');
const router = express.Router();

const { verificarToken } = require('../middlewares/auth.middleware');
const requiereAdministrador = require('../middlewares/admin.middleware');

const {
  listarUsuarios,
  obtenerUsuario,
  crearUsuario,
  cambiarEstadoUsuario
} = require('../controllers/usuarios.controller');

router.use(verificarToken);
router.use(requiereAdministrador);

router.get('/', listarUsuarios);
router.get('/:id', obtenerUsuario);
router.post('/', crearUsuario);
router.patch('/:id/estado', cambiarEstadoUsuario);

module.exports = router;