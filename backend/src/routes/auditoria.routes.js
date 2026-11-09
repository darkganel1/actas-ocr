
const express = require('express');
const router = express.Router();

const { verificarToken } = require('../middlewares/auth.middleware');
const requiereAdministrador = require('../middlewares/admin.middleware');

const {
  listar,
  obtener
} = require('../controllers/auditoria.controller');

router.use(verificarToken);
router.use(requiereAdministrador);

router.get('/', listar);
router.get('/:id', obtener);

module.exports = router;
