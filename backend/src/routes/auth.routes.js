
const express = require('express');
const rateLimit = require('express-rate-limit');

const {
    login,
    perfil
} = require('../controllers/auth.controller');

const {
    verificarToken
} = require('../middlewares/auth.middleware');

const router = express.Router();

const loginLimiter = rateLimit({
    windowMs: 15 * 60 * 1000,
    limit: 10,
    standardHeaders: 'draft-7',
    legacyHeaders: false,
    message: {
        success: false,
        message: 'Demasiados intentos. Intenta nuevamente más tarde.'
    }
});

router.post('/login', loginLimiter, login);

router.get('/perfil', verificarToken, perfil);

module.exports = router;
