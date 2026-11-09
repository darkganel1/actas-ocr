
const express = require('express');
const helmet = require('helmet');
const cors = require('cors');
const rateLimit = require('express-rate-limit');

const healthRoutes = require('./routes/health.routes');
const authRoutes = require('./routes/auth.routes');
const usuariosRoutes = require('./routes/usuarios.routes');
const documentosRoutes = require('./routes/documentos.routes');
const actasRoutes = require('./routes/actas.routes');
const auditoriaRoutes = require('./routes/auditoria.routes');
const actasAdminRoutes = require('./routes/actas-admin.routes');


const app = express();

app.disable('x-powered-by');
app.use(helmet());

app.use(cors({
    origin: process.env.FRONTEND_URL || 'http://localhost:5173'
}));

app.use(express.json({ limit: '2mb' }));
app.use(express.urlencoded({
    extended: true,
    limit: '2mb'
}));

const apiLimiter = rateLimit({
    windowMs: 15 * 60 * 1000,
    limit: 300,
    standardHeaders: 'draft-7',
    legacyHeaders: false
});

app.use('/api', apiLimiter);

app.get('/', (req, res) => {
    res.json({
        name: 'Sistema de Registro de Actas',
        version: '1.0.0',
        status: 'running'
    });
});

app.use('/api/health', healthRoutes);
app.use('/api/auth', authRoutes);
app.use('/api/usuarios', usuariosRoutes);
app.use('/api/documentos', documentosRoutes);
app.use('/api/actas', actasRoutes);
app.use('/api/auditoria', auditoriaRoutes);
   app.use('/api/actas', actasAdminRoutes);
  
app.use((req, res) => {
    res.status(404).json({
        success: false,
        message: 'Ruta no encontrada.'
    });
});

app.use((err, req, res, next) => {
    console.error('Error del servidor:', err);

    res.status(500).json({
        success: false,
        message: 'Error interno del servidor.'
    });
});

module.exports = app;
