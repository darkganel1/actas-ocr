
import argparse
import sys
from pathlib import Path

import pytesseract
from pdf2image import convert_from_path
from PIL import Image, ImageEnhance, ImageFilter


# Configuración de Tesseract para Windows
TESSERACT_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH

IDIOMA = "spa"
RESOLUCION = 300


def preparar_imagen(imagen):
    """Mejora la imagen para facilitar el reconocimiento OCR."""

    imagen = imagen.convert("L")
    imagen = ImageEnhance.Contrast(imagen).enhance(1.5)
    imagen = ImageEnhance.Sharpness(imagen).enhance(1.5)

    return imagen


def procesar_pdf(archivo_pdf, carpeta_salida):

    archivo_pdf = Path(archivo_pdf)
    carpeta_salida = Path(carpeta_salida)

    if not archivo_pdf.exists():
        raise FileNotFoundError(
            f"No existe el archivo: {archivo_pdf}"
        )

    if not archivo_pdf.is_file() or archivo_pdf.suffix.lower() != ".pdf":
        raise ValueError("El archivo debe ser un PDF.")

    if not Path(TESSERACT_PATH).exists():
        raise FileNotFoundError(
            "No se encontró Tesseract en la ruta configurada."
        )

    carpeta_salida.mkdir(parents=True, exist_ok=True)

    nombre = archivo_pdf.stem
    carpeta_paginas = carpeta_salida / f"{nombre}_paginas"
    carpeta_paginas.mkdir(exist_ok=True)

    print("\n===================================")
    print(" SISTEMA DE DIGITALIZACIÓN DE ACTAS")
    print("===================================")
    print(f"Archivo: {archivo_pdf.name}")
    print(f"Idioma: {IDIOMA}")
    print(f"Resolución: {RESOLUCION} DPI")
    print("\nConvirtiendo PDF a imágenes...")

    paginas = convert_from_path(
        str(archivo_pdf),
        dpi=RESOLUCION,
        fmt="png"
    )

    textos = []

    print(f"Total de páginas: {len(paginas)}")

    for numero, pagina in enumerate(paginas, start=1):

        print(f"\nProcesando página {numero}...")

        imagen = preparar_imagen(pagina)

        ruta_imagen = carpeta_paginas / f"pagina_{numero:03d}.png"
        imagen.save(ruta_imagen)

        texto = pytesseract.image_to_string(
            imagen,
            lang=IDIOMA,
            config="--psm 3"
        )

        textos.append(
            f"\n\n========== PÁGINA {numero} ==========\n\n"
            + texto
        )

        print("Reconocimiento completado.")

    texto_completo = "\n".join(textos)

    archivo_txt = carpeta_salida / f"{nombre}_ocr.txt"

    archivo_txt.write_text(
        texto_completo,
        encoding="utf-8"
    )

    print("\n===================================")
    print(" PROCESAMIENTO TERMINADO")
    print("===================================")
    print(f"Texto generado: {archivo_txt}")
    print(f"Páginas procesadas: {len(paginas)}")
    print(f"Caracteres reconocidos: {len(texto_completo)}")

    return archivo_txt


if __name__ == "__main__":

    parser = argparse.ArgumentParser(
        description="Procesador OCR de actas de nacimiento."
    )

    parser.add_argument(
        "pdf",
        help="Ruta del archivo PDF que se procesará."
    )

    parser.add_argument(
        "--salida",
        default="storage/temporales",
        help="Carpeta donde se guardará el resultado."
    )

    args = parser.parse_args()

    try:
        procesar_pdf(args.pdf, args.salida)

    except Exception as error:
        print(f"\nERROR: {error}")
        sys.exit(1)
