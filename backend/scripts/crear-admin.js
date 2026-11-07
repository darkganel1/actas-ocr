
require('dotenv').config();

const readline = require('readline');
const bcrypt = require('bcrypt');
const { pool } = require('../src/config/database');

const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout
});

function preguntar(texto) {
    return new Promise(resolve => {
        rl.question(texto, resolve);
    });
}

async function crearAdministrador() {
    try {
        console.log('\n=== CREAR ADMINISTRADOR INICIAL ===\n');

        const nombre = (await preguntar('Nombre completo: ')).trim();
        const usuario = (await preguntar('Nombre de usuario: ')).trim();
        const correo = (await preguntar('Correo electrónico: ')).trim().toLowerCase();
        const password = await preguntar('Contraseña: ');

        if (!nombre || !usuario || !correo || !password) {
            throw new Error('Todos los campos son obligatorios.');
        }

        if (password.length < 12) {
            throw new Error('La contraseña debe tener al menos 12 caracteres.');
        }

        const [existentes] = await pool.execute(
            `SELECT id_usuario FROM usuarios
             WHERE usuario = ? OR correo = ?
             LIMIT 1`,
            [usuario, correo]
        );

        if (existentes.length) {
            throw new Error('El usuario o correo ya está registrado.');
        }

        const [roles] = await pool.execute(
            `SELECT id_rol FROM roles
             WHERE nombre = 'Administrador'
             LIMIT 1`
        );

        if (!roles.length) {
            throw new Error('No existe el rol Administrador.');
        }

        const hash = await bcrypt.hash(password, 12);

        await pool.execute(
            `INSERT INTO usuarios
            (id_rol, nombre_completo, usuario, correo, password_hash, activo)
            VALUES (?, ?, ?, ?, ?, 1)`,
            [
                roles[0].id_rol,
                nombre,
                usuario,
                correo,
                hash
            ]
        );

        console.log('\nAdministrador creado correctamente.');

    } catch (error) {
        console.error('\nNo se pudo crear el administrador:', error.message);
        process.exitCode = 1;

    } finally {
        rl.close();
        await pool.end();
    }
}

crearAdministrador();
