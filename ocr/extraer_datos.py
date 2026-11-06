
import re
import sys
from pathlib import Path
from collections import Counter

import pytesseract
from PIL import Image, ImageOps, ImageEnhance, ImageFilter

pytesseract.pytesseract.tesseract_cmd = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)

# Para números y fechas utilizamos el modelo inglés.
IDIOMA = "eng"

COLUMNAS = {
    "oficialia": (0.600, 0.675),
    "fecha_registro": (0.655, 0.785),
    "libro": (0.765, 0.850),
    "numero_acta": (0.825, 0.945),
}

FILA_VALORES = (0.238, 0.267)

PATRONES = {
    "oficialia": r"^\d{4}$",
    "fecha_registro": r"^\d{1,2}/\d{1,2}/\d{4}$",
    "libro": r"^\d{1,3}$",
    "numero_acta": r"^\d{1,5}$",
}


def preparar_imagen(imagen):

    # No aplicar umbral binario agresivo.
    imagen = ImageOps.grayscale(imagen)
    imagen = ImageOps.autocontrast(imagen)

    # Ampliar sin perder los tonos originales.
    ancho, alto = imagen.size

    imagen = imagen.resize(
        (ancho * 4, alto * 4),
        Image.Resampling.LANCZOS
    )

    imagen = ImageEnhance.Contrast(imagen).enhance(1.4)

    # Agregar margen blanco para evitar que los bordes
    # de las celdas interfieran con el OCR.
    imagen = ImageOps.expand(
        imagen,
        border=30,
        fill=255
    )

    return imagen


def validar_texto(texto, campo):

    texto = texto.strip()
    texto = texto.replace(" ", "")
    texto = texto.replace("\n", "")

    # Eliminar caracteres ajenos a números y diagonales.
    texto = re.sub(r"[^0-9/]", "", texto)

    patron = PATRONES[campo]

    if re.fullmatch(patron, texto):
        return texto

    return None


def reconocer_celda(imagen, campo, carpeta):

    imagen_procesada = preparar_imagen(imagen)

    imagen_procesada.save(
        carpeta / f"{campo}_mejorada.png"
    )

    configuraciones = [7, 8, 13]

    candidatos = []

    print(f"\nProcesando: {campo}")

    for psm in configuraciones:

        config = (
            f"--oem 1 --psm {psm} "
            "-c tessedit_char_whitelist=0123456789/"
        )

        texto = pytesseract.image_to_string(
            imagen_procesada,
            lang=IDIOMA,
            config=config
        )

        valor = validar_texto(texto, campo)

        print(
            f"PSM {psm}: "
            f"bruto={repr(texto.strip())} "
            f"validado={valor}"
        )

        if valor:
            candidatos.append(valor)

    if not candidatos:
        return ""

    # Preferir el resultado válido más completo.
    candidatos.sort(
        key=len,
        reverse=True
    )

    resultado = candidatos[0]

    print(f"Resultado seleccionado: {resultado}")

    return resultado


def extraer_tabla(ruta_imagen):

    ruta_imagen = Path(ruta_imagen)

    if not ruta_imagen.exists():
        raise FileNotFoundError(ruta_imagen)

    imagen = Image.open(ruta_imagen).convert("RGB")

    ancho, alto = imagen.size

    y1 = int(alto * FILA_VALORES[0])
    y2 = int(alto * FILA_VALORES[1])

    carpeta = (
        ruta_imagen.parent / "campos_registrales_v2"
    )

    carpeta.mkdir(exist_ok=True)

    resultados = {}

    for campo, (x1_rel, x2_rel) in COLUMNAS.items():

        x1 = int(ancho * x1_rel)
        x2 = int(ancho * x2_rel)

        # Recorte original sin aplicar filtros.
        celda = imagen.crop(
            (x1, y1, x2, y2)
        )

        celda.save(
            carpeta / f"{campo}_original.png"
        )

        valor = reconocer_celda(
            celda,
            campo,
            carpeta
        )

        resultados[campo] = valor

    return resultados


if __name__ == "__main__":

    if len(sys.argv) < 2:
        print(
            "Uso: python extraer_datos.py "
            "ruta_imagen.png"
        )
        sys.exit(1)

    try:

        datos = extraer_tabla(sys.argv[1])

        print("\n================================")
        print(" RESULTADO DE EXTRACCIÓN")
        print("================================")

        for campo, valor in datos.items():

            print(
                f"{campo}: "
                f"{valor if valor else 'PENDIENTE DE REVISIÓN'}"
            )

    except Exception as error:

        print(f"ERROR: {error}")
        sys.exit(1)
