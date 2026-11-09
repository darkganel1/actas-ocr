const express = require('express');
const rateLimit = require('express-rate-limit');
const { login, perfil, actividad, logout } = require('../controllers/auth.controller');
const { cambiarPassword } = require('../controllers/password.controller');
const { verificarToken } = require('../middlewares/auth.middleware');

const router = express.Router();

const loginLimiter = rateLimit({
  windowMs: 15 * 60 * 1000,
  limit: 10,
  standardHeaders: 'draft-7',
  legacyHeaders: false,
  message: { success: false, message: 'Demasiados intentos. Intenta nuevamente más tarde.' }
});

router.post('/login', loginLimiter, login);
router.get('/perfil', verificarToken, perfil);
router.post('/actividad', verificarToken, actividad);
router.post('/logout', verificarToken, logout);
router.patch('/cambiar-password', verificarToken, cambiarPassword);

module.exports = router;
