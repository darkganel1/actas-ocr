const fs = require('fs/promises');
const os = require('os');
const path = require('path');
const { execFile } = require('child_process');
const { promisify } = require('util');

const ejecutar = promisify(execFile);
const TAMANO_MAXIMO = 20 * 1024 * 1024;
const MAX_PAGINAS = Math.max(1, Number.parseInt(process.env.PDF_MAX_PAGES || '100', 10));

function crearError(mensaje, statusCode = 400) {
  const error = new Error(mensaje);
  error.statusCode = statusCode;
  return error;
}

function resolverPdfinfo() {
  if (process.env.PDFINFO_PATH && process.env.PDFINFO_PATH.trim()) {
    return path.resolve(process.env.PDFINFO_PATH.trim());
  }

  const poppler = process.env.OCR_POPPLER_PATH;
  if (poppler && poppler.trim()) {
    const ruta = path.resolve(poppler.trim());
    if (/pdfinfo(?:\.exe)?$/i.test(ruta)) return ruta;
    return path.join(ruta, process.platform === 'win32' ? 'pdfinfo.exe' : 'pdfinfo');
  }

  return process.platform === 'win32' ? 'pdfinfo.exe' : 'pdfinfo';
}

/**
 * Comprueba la estructura real del PDF con Poppler (pdfinfo).
 * No confía únicamente en la extensión ni en el MIME enviado por el navegador.
 * El archivo temporal usa un nombre fijo dentro de un directorio aleatorio y se elimina siempre.
 */
async function validarPDF(archivo) {
  if (!archivo || !Buffer.isBuffer(archivo.buffer)) {
    throw crearError('No se recibió un archivo PDF válido.', 400);
  }

  const buffer = archivo.buffer;
  const nombre = String(archivo.originalname || '');

  if (!/\.pdf$/i.test(nombre)) {
    throw crearError('El archivo debe tener extensión PDF.', 400);
  }

  if (buffer.length === 0) {
    throw crearError('El archivo PDF está vacío.', 400);
  }

  if (buffer.length > TAMANO_MAXIMO) {
    throw crearError('El PDF supera el límite permitido de 20 MB.', 413);
  }

  // El encabezado PDF debe aparecer dentro de los primeros 1024 bytes.
  const encabezado = buffer.subarray(0, Math.min(buffer.length, 1024));
  if (encabezado.indexOf(Buffer.from('%PDF-')) === -1) {
    throw crearError('El contenido del archivo no corresponde a un PDF.', 400);
  }

  // Un PDF completo debe contener su marcador EOF cerca del final.
  const cola = buffer.subarray(Math.max(0, buffer.length - 2048));
  if (cola.indexOf(Buffer.from('%%EOF')) === -1) {
    throw crearError('El PDF está incompleto o dañado (no se encontró %%EOF).', 400);
  }

  let directorioTemporal;
  try {
    directorioTemporal = await fs.mkdtemp(path.join(os.tmpdir(), 'actas-pdf-validacion-'));
    const rutaPDF = path.join(directorioTemporal, 'documento.pdf');

    await fs.writeFile(rutaPDF, buffer, { flag: 'wx', mode: 0o600 });

    const ejecutable = resolverPdfinfo();
    const { stdout } = await ejecutar(ejecutable, ['-enc', 'UTF-8', rutaPDF], {
      windowsHide: true,
      timeout: 15000,
      maxBuffer: 1024 * 1024
    });

    const salida = String(stdout || '');
    const coincidenciaPaginas = salida.match(/^Pages:\s*(\d+)\s*$/mi);
    if (!coincidenciaPaginas) {
      throw crearError('No se pudo verificar la estructura interna del PDF.', 400);
    }

    const paginas = Number(coincidenciaPaginas[1]);
    if (!Number.isSafeInteger(paginas) || paginas < 1) {
      throw crearError('El PDF no contiene páginas válidas.', 400);
    }

    const coincidenciaCifrado = salida.match(/^Encrypted:\s*(yes|no)/mi);
    if (coincidenciaCifrado && coincidenciaCifrado[1].toLowerCase() === 'yes') {
      throw crearError('No se permiten PDF protegidos con contraseña.', 400);
    }

    if (paginas > MAX_PAGINAS) {
      throw crearError(`El PDF supera el máximo permitido de ${MAX_PAGINAS} páginas.`, 413);
    }

    return { valido: true, paginas, bytes: buffer.length };
  } catch (error) {
    if (error.statusCode) throw error;

    if (error.code === 'ENOENT') {
      console.error('No se encontró pdfinfo. Configura PDFINFO_PATH u OCR_POPPLER_PATH.');
      throw crearError('El servidor no tiene disponible pdfinfo de Poppler para validar el PDF.', 503);
    }

    if (error.killed || error.code === 'ETIMEDOUT') {
      throw crearError('El PDF tardó demasiado en validarse o tiene una estructura demasiado compleja.', 422);
    }

    // pdfinfo termina con código distinto de cero cuando no puede interpretar el archivo.
    if (typeof error.code === 'number' || error.stderr) {
      throw crearError('El PDF está dañado, incompleto o no tiene una estructura válida.', 400);
    }

    console.error('Error validando PDF:', error);
    throw crearError('No fue posible validar el documento PDF.', 500);
  } finally {
    if (directorioTemporal) {
      await fs.rm(directorioTemporal, { recursive: true, force: true }).catch((error) => {
        console.error('No se pudo limpiar el directorio temporal de validación:', error.message);
      });
    }
  }
}

module.exports = { validarPDF };
