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




def centro(caja):
    if not caja or len(caja) < 4 or any(v is None for v in caja):
        return None, None
    return (caja[0] + caja[2]) / 2, (caja[1] + caja[3]) / 2


def buscar_linea(lineas, expresiones, y_min=0, y_max=None):
    for linea in lineas:
        t = normalizar_texto(linea["texto"])
        y = linea.get("y") or 0
        if y < y_min or (y_max is not None and y > y_max):
            continue
        if any(e in t for e in expresiones):
            return linea
    return None


def valor_encima_de_etiqueta(lineas, etiqueta, campo, max_gap=115, tolerancia_x=170):
    """Busca una detección completa encima de la etiqueta, sin fabricar cajas de palabra."""
    if etiqueta is None:
        return None
    ex = etiqueta["x"] + etiqueta["w"] / 2
    ey_top = etiqueta["y"]
    opciones = []
    etiquetas_genericas = (
        "NOMBRE", "PRIMER APELLIDO", "SEGUNDO APELLIDO", "SEXO",
        "FECHA DE NACIMIENTO", "LUGAR DE NACIMIENTO", "NACIONALIDAD", "CURP"
    )
    for c in lineas:
        if c is etiqueta or c.get("x") is None:
            continue
        texto = normalizar_texto(c["texto"])
        if any(e in texto for e in etiquetas_genericas):
            continue
        cx = c["x"] + c["w"] / 2
        gap = ey_top - (c["y"] + c["h"])
        if gap < -18 or gap > max_gap:
            continue
        if abs(cx - ex) > tolerancia_x:
            continue
        if len(texto) < 2:
            continue
        # Favorece cercanía vertical y alineación horizontal.
        score = max(0, gap) + abs(cx - ex) * 0.35
        opciones.append((score, c))
    if not opciones:
        return None
    opciones.sort(key=lambda z: z[0])
    elegido = opciones[0][1]
    return {
        "valor": elegido["texto"],
        "confianza": elegido["confianza"],
        "pagina": elegido["pagina"],
        "metodo": "deteccion_linea_encima_de_etiqueta",
        "etiqueta_detectada": etiqueta["texto"],
        "estado": "requiere_confirmacion",
        "validacion_humana": "pendiente",
        "geometria_valor": elegido["coordenadas_xyxy"],
        "geometria_etiqueta": etiqueta["coordenadas_xyxy"],
    }


def extraer_campo_por_etiqueta(lineas, aliases, y_min=0, y_max=None, max_gap=115):
    etiqueta = buscar_linea(lineas, aliases, y_min, y_max)
    return valor_encima_de_etiqueta(lineas, etiqueta, aliases[0], max_gap=max_gap)



def valor_debajo_de_etiqueta(lineas, etiqueta, max_gap=110, tolerancia_x=280, patron=None):
    if etiqueta is None:
        return None
    ex = etiqueta["x"] + etiqueta["w"] / 2
    y_bottom = etiqueta["y"] + etiqueta["h"]
    opciones = []
    for c in lineas:
        if c is etiqueta or c.get("x") is None:
            continue
        gap = c["y"] - y_bottom
        cx = c["x"] + c["w"] / 2
        if gap < -8 or gap > max_gap or abs(cx-ex) > tolerancia_x:
            continue
        if patron and not re.search(patron, c["texto"]):
            continue
        opciones.append((gap + abs(cx-ex)*0.25, c))
    if not opciones:
        return None
    c = sorted(opciones, key=lambda z:z[0])[0][1]
    return {
        "valor": c["texto"], "confianza": c["confianza"], "pagina": c["pagina"],
        "metodo": "deteccion_linea_debajo_de_etiqueta",
        "etiqueta_detectada": etiqueta["texto"],
        "estado": "requiere_confirmacion", "validacion_humana": "pendiente",
        "geometria_valor": c["coordenadas_xyxy"],
        "geometria_etiqueta": etiqueta["coordenadas_xyxy"],
    }


def extraer_datos_registrales(lineas):
    """Asocia los valores de la fila inferior de la tabla con sus encabezados."""
    campos = {}
    etiquetas = {
        "oficialia": ["OFICIALIA"],
        "fecha_registro": ["FECHA DE REGISTRO"],
        "libro": ["LIBRO"],
        "numero_acta": ["NUMERO DE ACTA"],
    }
    halladas = {}
    for campo, aliases in etiquetas.items():
        halladas[campo] = buscar_linea(lineas, aliases)

    # Para cada encabezado, buscar el valor debajo, en la misma columna.
    for campo, etiqueta in halladas.items():
        if etiqueta is None:
            continue
        ex = etiqueta["x"] + etiqueta["w"] / 2
        y_bottom = etiqueta["y"] + etiqueta["h"]
        opciones = []
        for c in lineas:
            if c is etiqueta or c.get("x") is None:
                continue
            cy = c["y"] + c["h"] / 2
            gap = c["y"] - y_bottom
            if gap < -8 or gap > 100:
                continue
            cx = c["x"] + c["w"] / 2
            if abs(cx - ex) > max(70, etiqueta["w"] * 0.8):
                continue
            texto = c["texto"].strip()
            if campo == "fecha_registro" and not re.search(r"\d{1,2}[/-]\d{1,2}[/-]\d{4}", texto):
                continue
            if campo in ("oficialia", "libro", "numero_acta") and not re.search(r"\d", texto):
                continue
            opciones.append((gap + abs(cx-ex)*0.2, c))
        if opciones:
            elegido = sorted(opciones, key=lambda z: z[0])[0][1]
            campos[campo] = {
                "valor": elegido["texto"], "confianza": elegido["confianza"],
                "pagina": elegido["pagina"], "metodo": "tabla_registral_por_columna",
                "etiqueta_detectada": etiqueta["texto"],
                "estado": "requiere_confirmacion", "validacion_humana": "pendiente",
                "geometria_valor": elegido["coordenadas_xyxy"],
                "geometria_etiqueta": etiqueta["coordenadas_xyxy"],
            }

    # Folio: únicamente si aparece etiqueta explícita.
    etiqueta_folio = buscar_linea(lineas, ["FOLIO"])
    if etiqueta_folio:
        valor = valor_debajo_de_etiqueta(lineas, etiqueta_folio, max_gap=115, tolerancia_x=180, patron=r"\d{7,12}")
        if valor and re.fullmatch(r"\d{7,12}", re.sub(r"\D", "", valor["valor"])):
            valor["valor"] = re.sub(r"\D", "", valor["valor"])
            campos["folio"] = valor
    return campos


def extraer_persona_registrada(lineas):
    h_persona = buscar_linea(lineas, ["DATOS DE LA PERSONA REGISTRADA"])
    h_filiacion = buscar_linea(lineas, ["DATOS DE FILIACION DE LA PERSONA REGISTRADA"])
    if not h_persona:
        return {}
    y0 = h_persona["y"] + h_persona["h"]
    y1 = h_filiacion["y"] if h_filiacion else None
    campos = {}
    aliases = {
        "nombre": ["NOMBRE(S)", "NOMBRES"],
        "primer_apellido": ["PRIMER APELLIDO"],
        "segundo_apellido": ["SEGUNDO APELLIDO"],
        "sexo": ["SEXO"],
        "fecha_nacimiento": ["FECHA DE NACIMIENTO"],
        "lugar_nacimiento": ["LUGAR DE NACIMIENTO"],
    }
    for campo, al in aliases.items():
        etiqueta = buscar_linea(lineas, al, y0, y1)
        dato = valor_encima_de_etiqueta(lineas, etiqueta, campo, max_gap=150, tolerancia_x=210)
        if dato:
            campos[campo] = dato
    return campos


def extraer_filiacion(lineas):
    """Extrae candidatos de progenitores por renglón y columna; no asigna parentesco."""
    h = buscar_linea(lineas, ["DATOS DE FILIACION DE LA PERSONA REGISTRADA"])
    if not h:
        return {"estado": "no_detectada", "registros": []}

    y0 = h["y"] + h["h"]
    # La filiación termina al comenzar anotaciones/certificación.
    h_fin = buscar_linea(lineas, ["ANOTACIONES MARGINALES", "CERTIFICACION"], y0)
    y1 = h_fin["y"] if h_fin else None
    bloque = [x for x in lineas if x["y"] >= y0 and (y1 is None or x["y"] < y1)]
    etiquetas = ["NOMBRE(S)", "PRIMER APELLIDO", "SEGUNDO APELLIDO", "NACIONALIDAD", "CURP"]
    filas = []
    for c in bloque:
        if normalizar_texto(c["texto"]) in etiquetas:
            cy = c["y"] + c["h"] / 2
            fila = next((f for f in filas if abs(f["cy"] - cy) < 70), None)
            if fila is None:
                fila = {"cy": cy, "etiquetas": []}
                filas.append(fila)
            fila["etiquetas"].append(c)
    filas.sort(key=lambda f: f["cy"])
    registros = []
    for idx, fila in enumerate(filas[:2], start=1):
        campos = {}
        for etiqueta in fila["etiquetas"]:
            key = normalizar_texto(etiqueta["texto"]).replace("(S)", "").strip()
            mapa = {
                "NOMBRE": "nombre", "PRIMER APELLIDO": "primer_apellido",
                "SEGUNDO APELLIDO": "segundo_apellido",
                "NACIONALIDAD": "nacionalidad", "CURP": "curp",
            }
            campo = mapa.get(key)
            if not campo:
                continue
            dato = valor_encima_de_etiqueta(bloque, etiqueta, campo, max_gap=145, tolerancia_x=190)
            if dato:
                campos[campo] = dato
        if campos:
            registros.append({
                "registro": idx,
                "parentesco": "no_determinado",
                "campos": campos,
                "estado": "requiere_confirmacion",
            })
    return {
        "estado": "candidatos_extraidos" if registros else "sin_datos_suficientes",
        "nota": "No se infiere si cada registro corresponde a madre o padre.",
        "registros": registros,
    }


def extraer_identificadores(lineas):
    salida = {}
    # CURP encabezado: valor cercano a etiqueta Clave Única.
    etiqueta = buscar_linea(lineas, ["CLAVE UNICA DE REGISTRO DE POBLACION"])
    if etiqueta:
        d = valor_debajo_de_etiqueta(lineas, etiqueta, max_gap=100, tolerancia_x=280, patron=r"[A-ZÑ]{4}\d{6}[HM][A-Z]{5}[A-Z0-9]\d")
        if d:
            salida["curp"] = d
    # Identificador electrónico: etiqueta y valor numérico próximo debajo.
    etiqueta = buscar_linea(lineas, ["IDENTIFICADOR ELECTRONICO"])
    if etiqueta:
        ex = etiqueta["x"] + etiqueta["w"]/2
        opciones = []
        for c in lineas:
            gap = c["y"] - (etiqueta["y"] + etiqueta["h"])
            cx = c["x"] + c["w"]/2
            limpio = re.sub(r"\D", "", c["texto"])
            if 0 <= gap <= 100 and abs(cx-ex) <= 250 and 18 <= len(limpio) <= 24:
                opciones.append((gap, c, limpio))
        if opciones:
            _, c, limpio = sorted(opciones, key=lambda z:z[0])[0]
            salida["identificador_electronico"] = {
                "valor": limpio, "confianza": c["confianza"], "pagina": c["pagina"],
                "metodo": "etiqueta_identificador_y_numero_inferior",
                "estado": "requiere_confirmacion", "validacion_humana": "pendiente",
                "geometria_valor": c["coordenadas_xyxy"],
                "geometria_etiqueta": etiqueta["coordenadas_xyxy"],
            }
    # Código de verificación: etiqueta inferior explícita.
    etiqueta = buscar_linea(lineas, ["CODIGO DE VERIFICACION"])
    if etiqueta:
        d = valor_debajo_de_etiqueta(lineas, etiqueta, max_gap=100, tolerancia_x=250, patron=r"\d{12,24}")
        if d:
            salida["codigo_verificacion"] = d
    return salida


def extraer_semantica_pagina(lineas):
    resultado = {}
    resultado.update(extraer_datos_registrales(lineas))
    resultado.update(extraer_persona_registrada(lineas))
    resultado["filiacion"] = extraer_filiacion(lineas)
    resultado.update(extraer_identificadores(lineas))
    return resultado


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
        campos_semanticos = extraer_semantica_pagina(lineas)

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
            "campos_extraidos": campos_semanticos,
        })
        print(f"  Detecciones: {len(lineas)} | renglones: {len(renglones)}")
        print(f"  Formato estimado: {formato['tipo_estimado']}")

    documento.close()

    salida = {
        "lector": "lector_paddleocr_v3_1",
        "estado": "experimental_no_produccion",
        "motor": "PaddleOCR",
        "modelo": "PP-OCRv5",
        "idioma": "es",
        "dpi": dpi,
        "limite_deteccion": limite,
        "estrategia": "una pasada general + extracción semántica geométrica; sin Tesseract",
        "archivo_original": pdf_path.name,
        "paginas": paginas,
        "nota": (
            "Las detecciones conservan geometría por línea. "
            "La asignación semántica de todos los campos y la integración "
            "completa de extractores V19 siguen pendientes de validación."
        ),
    }

    json_path = raiz_salida / "resultado_paddleocr_v3_1.json"
    txt_path = raiz_salida / "resultado_paddleocr_v3_1.txt"
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
            f.write("\n--- CAMPOS EXTRAÍDOS ---\n")
            f.write(json.dumps(pagina["campos_extraidos"], ensure_ascii=False, indent=2))
            f.write("\n\n--- CANDIDATOS DE PATRÓN ---\n")
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
        description="Lector experimental PaddleOCR V3.1 para actas de nacimiento."
    )
    parser.add_argument("pdf", nargs="?", default=str(PDF_DEFAULT))
    parser.add_argument("--dpi", type=int, default=DPI_DEFAULT)
    parser.add_argument("--limite", type=int, default=OCR_LIMIT_DEFAULT)
    parser.add_argument("--salida", default=None)
    args = parser.parse_args()
    procesar(args.pdf, args.dpi, args.limite, args.salida)
