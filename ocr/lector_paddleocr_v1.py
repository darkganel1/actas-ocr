import argparse
import json
import sys
from pathlib import Path

import pypdfium2 as pdfium
from paddleocr import PaddleOCR


BASE_DIR = Path(__file__).resolve().parent.parent

DEFAULT_PDF = (
    BASE_DIR
    / "storage"
    / "originales"
    / "acta_prueba elsa.pdf"
)

OUTPUT_DIR = (
    BASE_DIR
    / "storage"
    / "paddleocr"
    / "acta_prueba_elsa_1920"
)

DPI = 300


def convertir_pdf(pdf_path, output_dir):
    documento = pdfium.PdfDocument(str(pdf_path))
    imagenes = []

    print(f"\nPDF: {pdf_path.name}")
    print(f"Paginas: {len(documento)}")
    print(f"Resolucion: {DPI} DPI")

    for indice in range(len(documento)):
        pagina = documento[indice]

        bitmap = pagina.render(scale=DPI / 72)
        imagen = bitmap.to_pil().convert("RGB")

        image_path = output_dir / f"pagina_{indice + 1:03d}.png"
        imagen.save(image_path, optimize=True)

        imagenes.append(image_path)

        print(f"Pagina {indice + 1}: {imagen.width} x {imagen.height}")

    documento.close()
    return imagenes


def convertir_json(obj):
    if hasattr(obj, "tolist"):
        return obj.tolist()

    if isinstance(obj, dict):
        return {str(k): convertir_json(v) for k, v in obj.items()}

    if isinstance(obj, (list, tuple)):
        return [convertir_json(v) for v in obj]

    return obj


def procesar_pdf(pdf_path, output_dir):

    output_dir.mkdir(parents=True, exist_ok=True)

    print("\nInicializando PaddleOCR...")
    print("Modelo: PP-OCRv5")
    print("Idioma: Espanol")
    print("Dispositivo: CPU")

    ocr = PaddleOCR(
        lang="es",
        ocr_version="PP-OCRv5",
        text_det_limit_side_len=1920,
        text_det_limit_type="max",
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )

    imagenes = convertir_pdf(pdf_path, output_dir)

    resultados_completos = []
    texto_completo = []

    for indice, imagen_path in enumerate(imagenes, start=1):

        print(f"\nProcesando pagina {indice}...")

        resultados = ocr.predict(str(imagen_path))

        if not resultados:
            print("No se obtuvieron resultados.")
            continue

        resultado = resultados[0]

        datos = resultado.json

        if "res" in datos:
            datos = datos["res"]

        textos = datos.get("rec_texts", [])
        confianzas = datos.get("rec_scores", [])
        cajas = datos.get("rec_boxes", [])
        poligonos = datos.get("rec_polys", [])

        lineas = []

        for posicion, texto in enumerate(textos):

            confianza = (
                float(confianzas[posicion])
                if posicion < len(confianzas)
                else None
            )

            caja = (
                cajas[posicion]
                if posicion < len(cajas)
                else None
            )

            poligono = (
                poligonos[posicion]
                if posicion < len(poligonos)
                else None
            )

            linea = {
                "texto": str(texto),
                "confianza": confianza,
                "coordenadas": convertir_json(caja),
                "poligono": convertir_json(poligono),
            }

            lineas.append(linea)
            texto_completo.append(str(texto))

        resultados_completos.append({
            "pagina": indice,
            "imagen": imagen_path.name,
            "total_lineas": len(lineas),
            "lineas": lineas,
        })

        print(f"Lineas reconocidas: {len(lineas)}")

        # Guardar imagen con las detecciones
        resultado.save_to_img(save_path=str(output_dir))

    archivo_json = output_dir / "resultado_paddleocr.json"
    archivo_txt = output_dir / "resultado_paddleocr.txt"

    documento_resultado = {
        "motor": "PaddleOCR",
        "version": "3.2.0",
        "modelo": "PP-OCRv5",
        "idioma": "es",
        "dispositivo": "CPU",
        "archivo_original": pdf_path.name,
        "dpi": DPI,
        "total_paginas": len(imagenes),
        "total_lineas": sum(
            pagina["total_lineas"]
            for pagina in resultados_completos
        ),
        "paginas": resultados_completos,
    }

    with open(archivo_json, "w", encoding="utf-8") as archivo:
        json.dump(
            documento_resultado,
            archivo,
            ensure_ascii=False,
            indent=4,
        )

    with open(archivo_txt, "w", encoding="utf-8") as archivo:
        archivo.write("\n".join(texto_completo))

    print("\n" + "=" * 50)
    print("PROCESAMIENTO TERMINADO")
    print("=" * 50)

    print(f"Paginas: {len(imagenes)}")
    print(f"Lineas: {documento_resultado['total_lineas']}")
    print(f"JSON: {archivo_json}")
    print(f"TXT: {archivo_txt}")
    print(f"Resultados: {output_dir}")


def main():

    parser = argparse.ArgumentParser(
        description="Lector de actas con PaddleOCR 3.2"
    )

    parser.add_argument(
        "pdf",
        nargs="?",
        default=str(DEFAULT_PDF),
        help="Ruta del documento PDF"
    )

    args = parser.parse_args()

    pdf_path = Path(args.pdf).resolve()

    if not pdf_path.is_file():
        print(f"ERROR: No existe el archivo: {pdf_path}")
        sys.exit(1)

    if pdf_path.suffix.lower() != ".pdf":
        print("ERROR: El archivo debe ser PDF.")
        sys.exit(1)

    procesar_pdf(pdf_path, OUTPUT_DIR)


if __name__ == "__main__":
    main()

