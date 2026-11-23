# -*- coding: utf-8 -*-
"""
Lector experimental PaddleOCR V3 - base de integración.
No modifica lector_inteligente_v19.py ni lector_paddleocr_v2.py.

V3-Base:
- Una pasada OCR general por página.
- Conserva las cajas originales de PaddleOCR (nivel línea).
- Convierte coordenadas a x/y/w/h sin inventar cajas por palabra.
- Clasifica de forma orientativa los dos formatos de acta de nacimiento.
- Genera JSON, TXT e imagen de evidencia.
- No ejecuta Tesseract.
"""
import argparse
import json
import re
from pathlib import Path
from statistics import median

import pypdfium2 as pdfium
from PIL import Image, ImageDraw
from paddleocr import PaddleOCR

BASE = Path(__file__).resolve().parent.parent
PDF_DEFAULT = BASE / "storage" / "originales" / "acta_prueba elsa.pdf"
DPI_DEFAULT = 300
OCR_LIMIT_DEFAULT = 1920


def normalizar_texto(texto):
    texto = str(texto or "").upper()
    texto = texto.replace("Á", "A").replace("É", "E").replace("Í", "I")
    texto = texto.replace("Ó", "O").replace("Ú", "U").replace("Ü", "U")
    return re.sub(r"\s+", " ", texto).strip()


def a_lista(valor):
    if hasattr(valor, "tolist"):
        return valor.tolist()
    return valor


def normalizar_resultado_paddle(resultado, pagina_num):
    """Normaliza salida PP-OCRv5 sin convertir cajas de línea en palabras."""
    datos = resultado.json
    if "res" in datos:
        datos = datos["res"]

    textos = datos.get("rec_texts", []) or []
    scores = datos.get("rec_scores", []) or []
    cajas = datos.get("rec_boxes", []) or []

    lineas = []
    for i, texto in enumerate(textos):
        texto = str(texto).strip()
        if not texto:
            continue

        score = float(scores[i]) if i < len(scores) else None
        caja = a_lista(cajas[i]) if i < len(cajas) else None

        x1 = y1 = x2 = y2 = None
        if isinstance(caja, (list, tuple)) and len(caja) >= 4:
            x1, y1, x2, y2 = [int(round(float(v))) for v in caja[:4]]

        lineas.append({
            "texto": texto,
            "confianza": score,  # PaddleOCR devuelve normalmente 0..1
            "coordenadas_xyxy": [x1, y1, x2, y2] if x1 is not None else None,
            "x": x1,
            "y": y1,
            "w": max(0, x2 - x1) if x1 is not None else None,
            "h": max(0, y2 - y1) if y1 is not None else None,
            "pagina": pagina_num,
            "unidad_geometrica": "linea",
            "motor": "PaddleOCR PP-OCRv5",
        })
    return lineas


def ejecutar_ocr(ocr, imagen, limite):
    resultados = ocr.predict(
        input=str(imagen),
        text_det_limit_side_len=limite,
        text_det_limit_type="max",
    )
    if not resultados:
        return []
    return normalizar_resultado_paddle(resultados[0], pagina_num=1)


def clasificar_formato(lineas):
    """Clasificación heurística; no decide la validez del documento."""
    textos = [normalizar_texto(x["texto"]) for x in lineas]
    conjunto = " | ".join(textos)

    marcadores_moderno = [
        "SOY MEXICO", "DIRECTOR GENERAL DEL REGISTRO",
        "IDENTIFICADOR ELECTRONICO", "CODIGO DE VERIFICACION",
    ]
    marcadores_antiguo = [
        "FOLIO", "ENC. DE DPCHO.", "DIRECCION GENERAL DEL REGISTRO CIVIL",
    ]

    puntos_moderno = sum(m in conjunto for m in marcadores_moderno)
    puntos_antiguo = sum(m in conjunto for m in marcadores_antiguo)

    if puntos_antiguo > puntos_moderno:
        tipo = "acta_nacimiento_formato_antiguo"
    elif puntos_moderno > puntos_antiguo:
        tipo = "acta_nacimiento_formato_moderno"
    else:
        tipo = "acta_nacimiento_formato_no_determinado"

    return {
        "tipo_estimado": tipo,
        "puntos_formato_moderno": puntos_moderno,
        "puntos_formato_antiguo": puntos_antiguo,
        "criterio": "Marcadores textuales; requiere validación en más documentos",
    }


def agrupar_lineas_geometricas(lineas):
    """Agrupa cajas de texto en renglones aproximados usando su geometría."""
    validas = [x for x in lineas if x.get("y") is not None and x.get("h") is not None]
    validas.sort(key=lambda z: (z["y"] + z["h"] / 2, z["x"] or 0))
    grupos = []

    for item in validas:
        centro_y = item["y"] + item["h"] / 2
        mejor = None
        mejor_dist = None

        for grupo in grupos[-10:]:
            centro_grupo = median([z["y"] + z["h"] / 2 for z in grupo])
            tolerancia = max(10, min(30, median([z["h"] for z in grupo + [item]]) * 0.75))
            distancia = abs(centro_y - centro_grupo)
            if distancia <= tolerancia and (mejor_dist is None or distancia < mejor_dist):
                mejor, mejor_dist = grupo, distancia

        if mejor is None:
            grupos.append([item])
        else:
            mejor.append(item)

    salida = []
    for grupo in grupos:
        grupo.sort(key=lambda z: z["x"] if z["x"] is not None else 0)
        salida.append({
            "texto": " ".join(z["texto"] for z in grupo),
            "confianza_promedio": sum(
                z["confianza"] for z in grupo if z["confianza"] is not None
            ) / max(1, sum(z["confianza"] is not None for z in grupo)),
            "coordenadas": {
                "x1": min(z["x"] for z in grupo),
                "y1": min(z["y"] for z in grupo),
                "x2": max(z["x"] + z["w"] for z in grupo),
                "y2": max(z["y"] + z["h"] for z in grupo),
            },
            "elementos": [z["texto"] for z in grupo],
        })
    return salida


def extraer_candidatos(lineas):
    """Extrae patrones inequívocos como candidatos, sin asignar campos por suposición."""
    candidatos = []
    patrones = {
        "curp": re.compile(r"\b[A-ZÑ]{4}\d{6}[HM][A-Z]{5}[A-Z0-9]\d\b", re.I),
        "fecha": re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{4}\b"),
        "identificador_numerico": re.compile(r"\b\d{18,22}\b"),
    }

    for linea in lineas:
        texto = linea["texto"]
        for tipo, patron in patrones.items():
            for match in patron.finditer(texto):
                candidatos.append({
                    "tipo": tipo,
                    "valor": match.group(0),
                    "texto_origen": texto,
                    "confianza_ocr": linea["confianza"],
                    "coordenadas_xyxy": linea["coordenadas_xyxy"],
                    "estado": "candidato_pendiente_de_asignacion_semantica",
                })
    return candidatos


def procesar(pdf_path, dpi, limite, output_root=None):
    pdf_path = Path(pdf_path).resolve()
    if not pdf_path.is_file():
        raise FileNotFoundError(f"No existe el PDF: {pdf_path}")

    raiz_salida = Path(output_root).resolve() if output_root else (
        BASE / "storage" / "paddleocr" / f"{pdf_path.stem}_v3"
    )
    raiz_salida.mkdir(parents=True, exist_ok=True)

    documento = pdfium.PdfDocument(str(pdf_path))
    print(f"Documento: {pdf_path.name}")
    print(f"Páginas: {len(documento)}")
    print("Inicializando PaddleOCR PP-OCRv5...")

    ocr = PaddleOCR(
        lang="es",
        ocr_version="PP-OCRv5",
        text_det_limit_side_len=limite,
        text_det_limit_type="max",
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )

    paginas = []
    for indice in range(len(documento)):
        numero = indice + 1
        imagen = documento[indice].render(scale=dpi / 72).to_pil().convert("RGB")
        imagen_path = raiz_salida / f"pagina_{numero:03d}.png"
        imagen.save(imagen_path)

        print(f"Procesando página {numero}...")
        resultados = ocr.predict(
            input=str(imagen_path),
            text_det_limit_side_len=limite,
            text_det_limit_type="max",
        )
        lineas = normalizar_resultado_paddle(resultados[0], numero) if resultados else []
        for linea in lineas:
            linea["pagina"] = numero

        renglones = agrupar_lineas_geometricas(lineas)
        formato = clasificar_formato(lineas)
        candidatos = extraer_candidatos(lineas)

        evidencia = imagen.copy()
        dibujo = ImageDraw.Draw(evidencia)
        for linea in lineas:
            caja = linea.get("coordenadas_xyxy")
            if caja and None not in caja:
                x1, y1, x2, y2 = caja
                dibujo.rectangle((x1, y1, x2, y2), outline="red", width=2)
        evidencia_path = raiz_salida / f"pagina_{numero:03d}_evidencia.png"
        evidencia.save(evidencia_path)

        paginas.append({
            "pagina": numero,
            "imagen": imagen_path.name,
            "evidencia": evidencia_path.name,
            "ancho": imagen.width,
            "alto": imagen.height,
            "formato": formato,
            "total_detecciones": len(lineas),
            "total_renglones_geometricos": len(renglones),
            "ocr_lineas": lineas,
            "renglones_geometricos": renglones,
            "candidatos_patron": candidatos,
        })
        print(f"  Detecciones: {len(lineas)} | renglones: {len(renglones)}")
        print(f"  Formato estimado: {formato['tipo_estimado']}")

    documento.close()

    salida = {
        "lector": "lector_paddleocr_v3_base",
        "estado": "experimental_no_produccion",
        "motor": "PaddleOCR",
        "modelo": "PP-OCRv5",
        "idioma": "es",
        "dpi": dpi,
        "limite_deteccion": limite,
        "estrategia": "una pasada general por página; sin Tesseract",
        "archivo_original": pdf_path.name,
        "paginas": paginas,
        "nota": (
            "Las detecciones conservan geometría por línea. "
            "La asignación semántica de todos los campos y la integración "
            "completa de extractores V19 siguen pendientes de validación."
        ),
    }

    json_path = raiz_salida / "resultado_paddleocr_v3.json"
    txt_path = raiz_salida / "resultado_paddleocr_v3.txt"
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(salida, f, ensure_ascii=False, indent=2)

    with txt_path.open("w", encoding="utf-8") as f:
        for pagina in paginas:
            f.write(f"\n===== PÁGINA {pagina['pagina']} =====\n")
            f.write(f"FORMATO: {pagina['formato']['tipo_estimado']}\n")
            f.write("\n--- OCR GENERAL ---\n")
            for linea in pagina["ocr_lineas"]:
                f.write(
                    f"{linea['texto']} "
                    f"[conf={linea['confianza']}] "
                    f"[caja={linea['coordenadas_xyxy']}]\n"
                )
            f.write("\n--- CANDIDATOS DE PATRÓN ---\n")
            for candidato in pagina["candidatos_patron"]:
                f.write(
                    f"{candidato['tipo']}: {candidato['valor']} "
                    f"[conf={candidato['confianza_ocr']}]\n"
                )

    print("\nPADDLEOCR V3 BASE FINALIZADO")
    print(f"JSON: {json_path}")
    print(f"TXT:  {txt_path}")
    print(f"Salida: {raiz_salida}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Lector experimental PaddleOCR V3 Base para actas de nacimiento."
    )
    parser.add_argument("pdf", nargs="?", default=str(PDF_DEFAULT))
    parser.add_argument("--dpi", type=int, default=DPI_DEFAULT)
    parser.add_argument("--limite", type=int, default=OCR_LIMIT_DEFAULT)
    parser.add_argument("--salida", default=None)
    args = parser.parse_args()
    procesar(args.pdf, args.dpi, args.limite, args.salida)
