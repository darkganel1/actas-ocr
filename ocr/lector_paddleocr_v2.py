import argparse
import json
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageDraw
from paddleocr import PaddleOCR

BASE = Path(__file__).resolve().parent.parent
PDF_DEFAULT = BASE / "storage" / "originales" / "acta_prueba elsa.pdf"
OUTPUT = BASE / "storage" / "paddleocr" / "acta_prueba_elsa_v2"

DPI = 300

# Regiones expresadas como porcentajes de la página.
REGIONES = {
    "encabezado": (0.60, 0.02, 0.98, 0.30),
    "registro": (0.05, 0.23, 0.97, 0.30),
    "persona_registrada": (0.05, 0.30, 0.97, 0.43),
    "filiacion": (0.05, 0.44, 0.97, 0.59),
    "certificacion": (0.05, 0.60, 0.97, 0.80),
}


def normalizar_resultado(resultado):
    datos = resultado.json

    if "res" in datos:
        datos = datos["res"]

    textos = datos.get("rec_texts", [])
    scores = datos.get("rec_scores", [])
    cajas = datos.get("rec_boxes", [])

    lineas = []

    for i, texto in enumerate(textos):
        score = float(scores[i]) if i < len(scores) else None
        caja = cajas[i].tolist() if hasattr(cajas[i], "tolist") else (
            cajas[i] if i < len(cajas) else None
        )

        lineas.append({
            "texto": str(texto),
            "confianza": score,
            "coordenadas": caja,
        })

    return lineas


def ejecutar_ocr(ocr, imagen, limite):
    resultados = ocr.predict(
        str(imagen),
        text_det_limit_side_len=limite,
        text_det_limit_type="max",
    )

    if not resultados:
        return []

    return normalizar_resultado(resultados[0])


def procesar(pdf_path):

    OUTPUT.mkdir(parents=True, exist_ok=True)

    documento = pdfium.PdfDocument(str(pdf_path))

    print(f"Documento: {pdf_path.name}")
    print(f"Paginas: {len(documento)}")

    print("\nInicializando PP-OCRv5...")

    ocr = PaddleOCR(
        lang="es",
        ocr_version="PP-OCRv5",
        text_det_limit_side_len=1920,
        text_det_limit_type="max",
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )

    paginas = []

    for indice in range(len(documento)):

        pagina = documento[indice]
        imagen = pagina.render(scale=DPI / 72).to_pil().convert("RGB")

        imagen_path = OUTPUT / f"pagina_{indice + 1:03d}.png"
        imagen.save(imagen_path)

        print(f"\nProcesando pagina {indice + 1}...")

        # Primera pasada: documento completo.
        lineas_generales = ejecutar_ocr(ocr, imagen_path, 1920)

        print(f"Detecciones generales: {len(lineas_generales)}")

        # Segunda pasada: regiones independientes.
        resultados_regiones = {}

        ancho, alto = imagen.size

        for nombre, (x1, y1, x2, y2) in REGIONES.items():

            caja = (
                int(x1 * ancho),
                int(y1 * alto),
                int(x2 * ancho),
                int(y2 * alto),
            )

            recorte = imagen.crop(caja)

            recorte_path = OUTPUT / (
                f"pagina_{indice + 1:03d}_{nombre}.png"
            )

            recorte.save(recorte_path)

            lineas = ejecutar_ocr(ocr, recorte_path, 1280)

            resultados_regiones[nombre] = {
                "recorte": recorte_path.name,
                "coordenadas_pagina": list(caja),
                "total_lineas": len(lineas),
                "lineas": lineas,
            }

            print(f"{nombre}: {len(lineas)} detecciones")

        paginas.append({
            "pagina": indice + 1,
            "imagen": imagen_path.name,
            "ocr_general": lineas_generales,
            "regiones": resultados_regiones,
        })

        # Imagen de visualización de las regiones.
        visual = imagen.copy()
        dibujo = ImageDraw.Draw(visual)

        for nombre, (x1, y1, x2, y2) in REGIONES.items():

            caja = (
                int(x1 * ancho),
                int(y1 * alto),
                int(x2 * ancho),
                int(y2 * alto),
            )

            dibujo.rectangle(caja, outline="red", width=5)
            dibujo.text(
                (caja[0] + 5, caja[1] + 5),
                nombre,
                fill="red",
                stroke_width=2,
                stroke_fill="white",
            )

        visual.save(OUTPUT / f"pagina_{indice + 1:03d}_regiones.png")

    documento.close()

    salida = {
        "motor": "PaddleOCR",
        "version": "3.2.0",
        "modelo": "PP-OCRv5",
        "idioma": "es",
        "dpi": DPI,
        "estrategia": "OCR general + reconocimiento por regiones",
        "archivo_original": pdf_path.name,
        "paginas": paginas,
    }

    json_path = OUTPUT / "resultado_paddleocr_v2.json"
    txt_path = OUTPUT / "resultado_paddleocr_v2.txt"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(salida, f, ensure_ascii=False, indent=2)

    with open(txt_path, "w", encoding="utf-8") as f:

        for pagina in paginas:

            f.write(f"\n===== PAGINA {pagina['pagina']} =====\n")

            f.write("\n--- OCR GENERAL ---\n")

            for linea in pagina["ocr_general"]:
                f.write(linea["texto"] + "\n")

            for nombre, region in pagina["regiones"].items():

                f.write(f"\n--- {nombre.upper()} ---\n")

                for linea in region["lineas"]:
                    f.write(linea["texto"] + "\n")

    print("\n================================")
    print("PADDLEOCR V2 FINALIZADO")
    print("================================")
    print(f"JSON: {json_path}")
    print(f"TXT: {txt_path}")
    print(f"Resultados: {OUTPUT}")


if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", nargs="?", default=str(PDF_DEFAULT))
    args = parser.parse_args()

    ruta = Path(args.pdf).resolve()

    if not ruta.is_file():
        raise FileNotFoundError(ruta)

    procesar(ruta)
