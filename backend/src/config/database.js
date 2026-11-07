
const mysql = require('mysql2/promise');

const pool = mysql.createPool({
    host: process.env.DB_HOST,
    port: Number(process.env.DB_PORT || 3306),
    database: process.env.DB_NAME,
    user: process.env.DB_USER,
    password: process.env.DB_PASSWORD,

    waitForConnections: true,
    connectionLimit: 10,
    queueLimit: 0,

    charset: 'utf8mb4'
});

async function probarConexion() {
    let connection;

    try {
        connection = await pool.getConnection();
        await connection.query('SELECT 1');
        console.log('MySQL conectado correctamente.');
    } finally {
        if (connection) connection.release();
    }
}

module.exports = {
    pool,
    probarConexion
};
