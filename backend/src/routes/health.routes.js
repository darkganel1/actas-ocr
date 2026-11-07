
const express = require('express');
const router = express.Router();
const { pool } = require('../config/database');

router.get('/', async (req, res) => {
    try {
        await pool.query('SELECT 1');

        res.json({
            success: true,
            message: 'Backend funcionando correctamente.',
            database: 'connected',
            timestamp: new Date().toISOString()
        });

    } catch (error) {
        console.error('Error verificando MySQL:', error.message);

        res.status(503).json({
            success: false,
            message: 'Backend disponible, pero la base de datos no responde.',
            database: 'disconnected'
        });
    }
});

module.exports = router;
