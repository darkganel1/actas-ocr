
require('dotenv').config();

const app = require('./app');
const { probarConexion, pool } = require('./config/database');

const PORT = Number(process.env.PORT || 3000);

let server;

async function iniciarServidor() {
    try {
        await probarConexion();

        server = app.listen(PORT, () => {
            console.log('----------------------------------');
            console.log(' SISTEMA DE REGISTRO DE ACTAS');
            console.log('----------------------------------');
            console.log(`Servidor: http://localhost:${PORT}`);
            console.log(`Diagnóstico: http://localhost:${PORT}/api/health`);
            console.log('Estado: iniciado');
        });

    } catch (error) {
        console.error('No fue posible iniciar el backend.');
        console.error(error.message);
        process.exit(1);
    }
}

async function cerrarServidor() {
    console.log('\nCerrando servidor...');

    if (server) {
        server.close(async () => {
            await pool.end();
            console.log('Conexiones cerradas.');
            process.exit(0);
        });
    } else {
        await pool.end();
        process.exit(0);
    }
}

process.on('SIGINT', cerrarServidor);
process.on('SIGTERM', cerrarServidor);

iniciarServidor();
