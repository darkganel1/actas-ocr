# -*- coding: utf-8 -*-
"""
Lector experimental PaddleOCR V4 - PaddleOCR + reglas semánticas/validación de V19.
No modifica lector_inteligente_v19.py ni versiones anteriores.

V4:
- Una pasada OCR general por página.
- Conserva las cajas originales de PaddleOCR (nivel línea).
- Convierte coordenadas a x/y/w/h sin inventar cajas por palabra.
- Clasifica de forma orientativa los dos formatos de acta de nacimiento.
- Genera JSON, TXT e imagen de evidencia.
- No ejecuta Tesseract.
"""
import argparse
import csv
import json
import re
from datetime import datetime
from pathlib import Path
from statistics import median

import pypdfium2 as pdfium
from PIL import Image, ImageDraw, ImageOps, ImageEnhance
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


def limpiar_etiqueta(texto):
    """Normaliza etiquetas OCR para comparar aunque incluyan dos puntos o signos."""
    texto = normalizar_texto(texto)
    return re.sub(r"[^A-Z0-9Ñ() ]", "", texto).strip()


def valor_encima_de_etiqueta(
    lineas, etiqueta, campo, max_gap=115, tolerancia_x=170,
    excluir_cajas_altas=True
):
    """
    Busca una detección de texto encima de la etiqueta.
    Evita cajas anormalmente altas que suelen abarcar marca de agua o zonas vecinas.
    Conserva la caja OCR original; no inventa coordenadas por palabra.
    """
    if etiqueta is None or etiqueta.get("x") is None:
        return None

    ex = etiqueta["x"] + etiqueta["w"] / 2
    ey_top = etiqueta["y"]
    alto_etiqueta = max(1, etiqueta["h"])
    opciones = []
    etiquetas_genericas = (
        "NOMBRE", "PRIMER APELLIDO", "SEGUNDO APELLIDO", "SEXO",
        "FECHA DE NACIMIENTO", "LUGAR DE NACIMIENTO", "NACIONALIDAD", "CURP",
        "DATOS DE FILIACION", "DATOS DE LA PERSONA"
    )

    for c in lineas:
        if c is etiqueta or c.get("x") is None or c.get("w") is None:
            continue

        texto = normalizar_texto(c["texto"])
        texto_limpio = limpiar_etiqueta(texto)
        if any(e in texto_limpio for e in etiquetas_genericas):
            continue

        cx = c["x"] + c["w"] / 2
        gap = ey_top - (c["y"] + c["h"])
        if gap < -12 or gap > max_gap:
            continue

        # La alineación del centro ayuda, pero también aceptamos cajas anchas
        # cuando contienen el valor completo de una columna.
        distancia_x = abs(cx - ex)
        solapamiento = max(
            0,
            min(c["x"] + c["w"], etiqueta["x"] + etiqueta["w"])
            - max(c["x"], etiqueta["x"])
        )
        if distancia_x > tolerancia_x and solapamiento < min(c["w"], etiqueta["w"]) * 0.25:
            continue

        if excluir_cajas_altas and c.get("h") and c["h"] > max(65, alto_etiqueta * 3.0):
            continue
        if len(texto) < 2:
            continue

        # Penaliza cajas muy anchas que invaden columnas contiguas.
        penalizacion_ancho = max(0, c["w"] - max(260, etiqueta["w"] * 2.2)) * 0.12
        score = max(0, gap) + distancia_x * 0.30 + penalizacion_ancho
        opciones.append((score, c))

    if not opciones:
        return None

    opciones.sort(key=lambda z: z[0])
    elegido = opciones[0][1]
    return {
        "valor": elegido["texto"],
        "confianza": elegido["confianza"],
        "pagina": elegido["pagina"],
        "metodo": "deteccion_linea_encima_de_etiqueta_geometria_v32",
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
    """
    Extrae hasta dos filas de filiación.
    Agrupa etiquetas por renglón y limpia puntuación OCR (p. ej. 'Nombre(s):').
    No infiere parentesco ni transforma candidatos en datos confirmados.
    """
    h = buscar_linea(lineas, ["DATOS DE FILIACION DE LA PERSONA REGISTRADA"])
    if not h:
        return {"estado": "no_detectada", "registros": []}

    y0 = h["y"] + h["h"]
    h_fin = buscar_linea(lineas, ["ANOTACIONES MARGINALES", "CERTIFICACION"], y0)
    y1 = h_fin["y"] if h_fin else None
    bloque = [
        x for x in lineas
        if x.get("y") is not None and x.get("h") is not None
        and x["y"] >= y0 and (y1 is None or x["y"] < y1)
    ]

    mapa = {
        "NOMBRE(S)": "nombre",
        "NOMBRES": "nombre",
        "NOMBRE": "nombre",
        "PRIMER APELLIDO": "primer_apellido",
        "SEGUNDO APELLIDO": "segundo_apellido",
        "NACIONALIDAD": "nacionalidad",
        "CURP": "curp",
    }
    etiquetas = []
    for c in bloque:
        clave = limpiar_etiqueta(c["texto"])
        # Variantes frecuentes del OCR en las etiquetas.
        if clave in mapa and c.get("x") is not None:
            etiquetas.append((c, mapa[clave], c["y"] + c["h"] / 2))

    # Cada fila se forma con etiquetas que comparten aproximadamente la misma altura.
    filas = []
    for etiqueta, campo, cy in sorted(etiquetas, key=lambda z: z[2]):
        mejor = None
        mejor_dist = None
        for fila in filas:
            distancia = abs(fila["cy"] - cy)
            if distancia <= 42 and (mejor_dist is None or distancia < mejor_dist):
                mejor, mejor_dist = fila, distancia
        if mejor is None:
            filas.append({"cy": cy, "etiquetas": []})
            mejor = filas[-1]
        mejor["etiquetas"].append((etiqueta, campo))
        mejor["cy"] = median([e[0]["y"] + e[0]["h"] / 2 for e in mejor["etiquetas"]])

    filas.sort(key=lambda f: f["cy"])
    registros = []

    for idx, fila in enumerate(filas[:2], start=1):
        campos = {
            nombre: {
                "valor": None,
                "estado": "no_detectado",
                "validacion_humana": "pendiente",
            }
            for nombre in ("nombre", "primer_apellido", "segundo_apellido", "nacionalidad", "curp")
        }
        # Ordena por columna y limita la búsqueda a la fila correspondiente.
        for etiqueta, campo in sorted(fila["etiquetas"], key=lambda z: z[0]["x"]):
            dato = valor_encima_de_etiqueta(
                bloque,
                etiqueta,
                campo,
                max_gap=155,
                tolerancia_x=155,
                excluir_cajas_altas=True,
            )
            if dato and normalizar_texto(dato.get("valor")) not in {"-", "--", "---"}:
                campos[campo] = dato
            elif dato:
                campos[campo] = {
                    "valor": None,
                    "estado": "campo_vacio_o_guion",
                    "validacion_humana": "pendiente",
                    "geometria_valor": dato.get("geometria_valor"),
                    "geometria_etiqueta": dato.get("geometria_etiqueta"),
                }

        if any(v.get("valor") is not None for v in campos.values()):
            registros.append({
                "registro": idx,
                "parentesco": "no_determinado",
                "campos": campos,
                "estado": "requiere_confirmacion",
            })

    return {
        "estado": "candidatos_extraidos" if registros else "sin_datos_suficientes",
        "nota": (
            "Filas identificadas por la altura de sus etiquetas; "
            "parentesco no inferido. Todos los valores requieren confirmación humana."
        ),
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



def caja_sospechosa(caja):
    """Detecta cajas OCR demasiado altas para un campo de texto de una línea."""
    if not caja or len(caja) != 4 or any(v is None for v in caja):
        return True
    x1, y1, x2, y2 = caja
    ancho = max(1, x2 - x1)
    alto = max(1, y2 - y1)
    return alto > 75 or alto / ancho > 0.32


def segunda_lectura_campo(ocr, imagen_path, dato, campo, etiqueta, limite, carpeta_salida):
    """
    Relee una región estrecha situada encima de la etiqueta.
    La segunda lectura se guarda como evidencia y nunca elimina el OCR original.
    """
    if not dato or not etiqueta or etiqueta.get("x") is None:
        return None

    # La región se calcula desde la etiqueta, no desde la caja sospechosa.
    # Así se evita incluir gran parte de la marca de agua o columnas vecinas.
    x1 = max(0, int(etiqueta["x"] - 28))
    x2 = int(etiqueta["x"] + etiqueta["w"] + 28)
    y2 = max(1, int(etiqueta["y"] - 2))
    y1 = max(0, y2 - 145)

    with Image.open(imagen_path) as original:
        original = original.convert("RGB")
        x2 = min(original.width, x2)
        y2 = min(original.height, y2)
        if x2 <= x1 or y2 <= y1:
            return None

        recorte = original.crop((x1, y1, x2, y2))
        # Aumenta legibilidad sin alterar la imagen original almacenada.
        gris = ImageOps.grayscale(recorte)
        gris = ImageOps.autocontrast(gris, cutoff=1)
        gris = ImageEnhance.Contrast(gris).enhance(1.25)
        ampliada = gris.resize((gris.width * 2, gris.height * 2), Image.Resampling.LANCZOS)
        ruta_recorte = Path(carpeta_salida) / f"segunda_lectura_{campo}.png"
        ampliada.save(ruta_recorte)

    resultados = ocr.predict(
        input=str(ruta_recorte),
        text_det_limit_side_len=limite,
        text_det_limit_type="max",
    )
    if not resultados:
        return {
            "estado": "sin_resultado",
            "archivo_evidencia": ruta_recorte.name,
            "candidatos": [],
        }

    detecciones = normalizar_resultado_paddle(resultados[0], pagina_num=1)
    candidatos = []
    for item in detecciones:
        texto = item["texto"].strip()
        caja = item.get("coordenadas_xyxy")
        if not texto or not caja or any(v is None for v in caja):
            continue

        # Coordenadas del recorte (ampliado 2x) a coordenadas de la página.
        cx1, cy1, cx2, cy2 = caja
        caja_pagina = [
            int(round(cx1 / 2 + x1)),
            int(round(cy1 / 2 + y1)),
            int(round(cx2 / 2 + x1)),
            int(round(cy2 / 2 + y1)),
        ]
        alto = caja_pagina[3] - caja_pagina[1]
        if alto > 75:
            continue
        if limpiar_etiqueta(texto) in {
            "NOMBRE(S)", "NOMBRES", "PRIMER APELLIDO", "SEGUNDO APELLIDO",
            "SEXO", "FECHA DE NACIMIENTO", "LUGAR DE NACIMIENTO"
        }:
            continue

        candidatos.append({
            "valor": texto,
            "confianza": item["confianza"],
            "coordenadas_xyxy": caja_pagina,
        })

    candidatos.sort(
        key=lambda z: (z["confianza"] if z["confianza"] is not None else 0),
        reverse=True
    )

    original = {
        "valor": dato.get("valor"),
        "confianza": dato.get("confianza"),
        "geometria": dato.get("geometria_valor"),
    }
    elegido = candidatos[0] if candidatos else None

    resultado = {
        "estado": "candidato_segunda_lectura" if elegido else "sin_candidato_valido",
        "campo": campo,
        "original": original,
        "candidatos": candidatos,
        "archivo_evidencia": ruta_recorte.name,
        "requiere_confirmacion": True,
    }

    # Solo propone sustitución cuando la lectura nueva tiene confianza
    # claramente superior; nunca la confirma automáticamente.
    conf_original = dato.get("confianza") or 0
    if elegido and (elegido["confianza"] or 0) >= conf_original + 0.015:
        resultado["valor_propuesto"] = elegido["valor"]
        resultado["confianza_propuesta"] = elegido["confianza"]
    return resultado


def refinar_campos_persona(ocr, imagen_path, lineas, campos, limite, carpeta_salida):
    """Aplica segunda lectura únicamente a nombres/apellidos con cajas sospechosas."""
    if not campos:
        return {}

    h_persona = buscar_linea(lineas, ["DATOS DE LA PERSONA REGISTRADA"])
    h_filiacion = buscar_linea(lineas, ["DATOS DE FILIACION DE LA PERSONA REGISTRADA"])
    if not h_persona:
        return {}

    y0 = h_persona["y"] + h_persona["h"]
    y1 = h_filiacion["y"] if h_filiacion else None
    aliases = {
        "nombre": ["NOMBRE(S)", "NOMBRES"],
        "primer_apellido": ["PRIMER APELLIDO"],
        "segundo_apellido": ["SEGUNDO APELLIDO"],
    }
    resultados = {}

    for campo, alias in aliases.items():
        dato = campos.get(campo)
        if not dato or not caja_sospechosa(dato.get("geometria_valor")):
            continue
        etiqueta = buscar_linea(lineas, alias, y0, y1)
        if not etiqueta:
            continue
        segunda = segunda_lectura_campo(
            ocr, imagen_path, dato, campo, etiqueta, limite, carpeta_salida
        )
        if segunda:
            resultados[campo] = segunda
            if segunda.get("valor_propuesto"):
                # Mantiene el valor original para auditoría y expone la propuesta aparte.
                dato["valor_original"] = dato["valor"]
                dato["valor"] = segunda["valor_propuesto"]
                dato["confianza_original"] = dato.get("confianza")
                dato["confianza"] = segunda["confianza_propuesta"]
                dato["metodo"] = "segunda_lectura_selectiva_v4"
                dato["validacion_humana"] = "pendiente"
                dato["segunda_lectura"] = segunda
    return resultados


def extraer_semantica_pagina(lineas):
    resultado = {}
    resultado.update(extraer_datos_registrales(lineas))
    resultado.update(extraer_persona_registrada(lineas))
    resultado["filiacion"] = extraer_filiacion(lineas)
    resultado.update(extraer_identificadores(lineas))
    return resultado



# ---------------- V4: REGLAS SEMÁNTICAS Y VALIDACIÓN PORTADAS DE V19 ----------------

PATRONES_V19 = {
    "folio": re.compile(r"(?<!\d)\d{7,12}(?!\d)"),
    "curp": re.compile(r"\b[A-ZÑ]{4}\d{6}[HM][A-Z]{5}[A-Z0-9]\d\b", re.I),
    "identificador_electronico": re.compile(r"\b\d{15,22}\b"),
}

ALIASES_V19 = {
    "oficialia": ["oficialia", "numero de oficialia", "no de oficialia"],
    "fecha_registro": ["fecha de registro", "fecha registro"],
    "libro": ["libro", "numero de libro"],
    "numero_acta": ["numero de acta", "num de acta", "no de acta"],
    "nombre": ["nombre(s)", "nombres", "nombre"],
    "primer_apellido": ["primer apellido"],
    "segundo_apellido": ["segundo apellido"],
    "fecha_nacimiento": ["fecha de nacimiento"],
    "sexo": ["sexo"],
    "lugar_nacimiento": ["lugar de nacimiento"],
    "nacionalidad": ["nacionalidad"],
}


def normalizar_v19(texto):
    import unicodedata
    s = unicodedata.normalize("NFD", str(texto or ""))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", s.lower())).strip()


def validar_formato_v19(campo, valor):
    """Reglas no destructivas adaptadas de V19; nunca corrige el texto OCR."""
    if valor is None or not str(valor).strip():
        return False, "Sin valor reconocido"
    limpio = re.sub(r"\s+", "", str(valor))
    if campo in ("oficialia", "libro", "numero_acta"):
        limites = {"oficialia": 6, "libro": 8, "numero_acta": 10}
        ok = bool(re.fullmatch(rf"\d{{1,{limites[campo]}}}", limpio))
        return ok, "Número válido" if ok else "Formato numérico no válido"
    if campo == "folio":
        ok = bool(re.fullmatch(r"\d{7,12}", limpio))
        return ok, "Folio numérico" if ok else "Folio no válido"
    if campo in ("fecha_registro", "fecha_nacimiento"):
        if not re.fullmatch(r"\d{1,2}[/-]\d{1,2}[/-]\d{4}", limpio):
            return False, "Formato de fecha no válido"
        for fmt in ("%d/%m/%Y", "%d-%m-%Y"):
            try:
                datetime.strptime(limpio, fmt)
                return True, "Fecha calendario válida"
            except ValueError:
                pass
        return False, "Fecha inexistente"
    if campo == "curp":
        ok = bool(PATRONES_V19["curp"].fullmatch(limpio))
        return ok, "Estructura CURP válida" if ok else "Estructura CURP no válida"
    if campo == "identificador_electronico":
        ok = bool(re.fullmatch(r"\d{15,22}", limpio))
        return ok, "Identificador numérico admisible" if ok else "Longitud numérica no válida"
    if campo == "codigo_verificacion":
        ok = bool(re.fullmatch(r"\d{12,24}", limpio))
        return ok, "Código numérico admisible" if ok else "Longitud numérica no válida"
    if campo == "sexo":
        ok = normalizar_v19(valor) in ("hombre", "mujer", "masculino", "femenino")
        return ok, "Categoría admisible" if ok else "Texto no reconocido como sexo"
    if campo in ("nombre", "primer_apellido", "segundo_apellido", "lugar_nacimiento", "nacionalidad"):
        letras = re.sub(r"[^A-Za-zÁÉÍÓÚÜÑáéíóúüñ]", "", str(valor))
        ok = len(letras) >= 2 and len(str(valor).strip()) <= 100
        return ok, "Texto admisible" if ok else "Texto insuficiente"
    return False, "Campo sin regla de validación"


def dato_ausente(campo, detalle):
    return {
        "valor": None, "confianza": None, "metodo": "no_identificado",
        "formato_valido": False, "detalle_validacion": detalle,
        "validacion_humana": "pendiente", "estado": "captura_manual",
        "alternativas": [],
    }


def preparar_dato_v4(campo, dato):
    if not dato or dato.get("valor") in (None, ""):
        return dato_ausente(campo, "No se encontró una asociación OCR confiable")
    valor = str(dato.get("valor", "")).strip()
    ok, detalle = validar_formato_v19(campo, valor)
    salida = dict(dato)
    salida.update({
        "valor": valor,
        "formato_valido": ok,
        "detalle_validacion": detalle,
        "validacion_humana": "pendiente",
        "estado": "requiere_confirmacion" if ok else "captura_manual",
        "alternativas": salida.get("alternativas", []),
    })
    return salida


def consolidar_campos_v4(paginas):
    requeridos = [
        "oficialia", "fecha_registro", "libro", "numero_acta", "folio",
        "nombre", "primer_apellido", "segundo_apellido", "fecha_nacimiento",
        "sexo", "lugar_nacimiento", "nacionalidad", "curp",
        "identificador_electronico", "codigo_verificacion",
    ]
    campos = {}
    for campo in requeridos:
        elegido = None
        for pagina in paginas:
            candidato = pagina.get("campos_extraidos", {}).get(campo)
            if candidato and candidato.get("valor") not in (None, ""):
                elegido = candidato
                break
        campos[campo] = preparar_dato_v4(campo, elegido)

    # CURP y folio solo se toman de etiquetas/asociaciones explícitas.
    if campos["folio"]["valor"] is None:
        campos["folio"]["detalle_validacion"] = (
            "No se encontró una etiqueta FOLIO asociada a un valor; "
            "el identificador o número de certificado no se interpreta como folio"
        )
    if campos["nacionalidad"]["valor"] is None:
        campos["nacionalidad"]["detalle_validacion"] = (
            "No se infiere la nacionalidad de la persona registrada a partir de los datos de filiación"
        )

    cruzadas = []
    curp = (campos["curp"].get("valor") or "").upper()
    fecha_txt = campos["fecha_nacimiento"].get("valor") or ""
    sexo = normalizar_v19(campos["sexo"].get("valor") or "")
    if PATRONES_V19["curp"].fullmatch(curp):
        fecha_obj = None
        for fmt in ("%d/%m/%Y", "%d-%m-%Y"):
            try:
                fecha_obj = datetime.strptime(fecha_txt, fmt)
                break
            except ValueError:
                pass
        if fecha_obj:
            curp_fecha = curp[4:10]
            fecha_doc = fecha_obj.strftime("%y%m%d")
            cruzadas.append({
                "regla": "curp_fecha_nacimiento",
                "resultado": "coincide" if curp_fecha == fecha_doc else "discrepancia",
                "valor_documento": fecha_txt, "valor_curp": curp_fecha,
                "impacto": "informativo; requiere cotejo humano",
            })
        if sexo in ("hombre", "mujer", "masculino", "femenino"):
            sexo_curp = curp[10]
            sexo_doc = "H" if sexo in ("hombre", "masculino") else "M"
            cruzadas.append({
                "regla": "curp_sexo",
                "resultado": "coincide" if sexo_curp == sexo_doc else "discrepancia",
                "valor_documento": sexo, "valor_curp": sexo_curp,
                "impacto": "informativo; requiere cotejo humano",
            })

    recuperados = [k for k, v in campos.items() if v.get("valor") not in (None, "")]
    pendientes = [k for k, v in campos.items() if v.get("estado") == "captura_manual"]
    return campos, cruzadas, {
        "total_campos": len(campos), "campos_con_valor": len(recuperados),
        "campos_captura_manual": len(pendientes),
        "campos_recuperados": recuperados, "campos_pendientes": pendientes,
        "nota": "Validaciones informativas; no certifican legalmente el documento y no sustituyen revisión humana.",
    }


def validar_filiacion_v4(filiacion):
    """Valida campos de cada fila sin asignar parentesco ni completar ausencias."""
    for registro in filiacion.get("registros", []):
        for campo, dato in registro.get("campos", {}).items():
            if dato.get("valor") not in (None, ""):
                ok, detalle = validar_formato_v19(campo, dato["valor"])
                dato["formato_valido"] = ok
                dato["detalle_validacion"] = detalle
                dato["estado"] = "requiere_confirmacion" if ok else "captura_manual"
                dato["validacion_humana"] = "pendiente"
            else:
                dato.setdefault("formato_valido", False)
                dato.setdefault("detalle_validacion", "Campo ausente o no detectado; no se infiere")
                dato.setdefault("estado", "captura_manual")
    return filiacion

def procesar(pdf_path, dpi, limite, output_root=None):
    pdf_path = Path(pdf_path).resolve()
    if not pdf_path.is_file():
        raise FileNotFoundError(f"No existe el PDF: {pdf_path}")

    raiz_salida = Path(output_root).resolve() if output_root else (
        BASE / "storage" / "paddleocr" / f"{pdf_path.stem}_v4"
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
        campos_semanticos["filiacion"] = validar_filiacion_v4(campos_semanticos.get("filiacion", {}))
        segunda_lectura = refinar_campos_persona(
            ocr,
            imagen_path,
            lineas,
            campos_semanticos,
            limite,
            raiz_salida,
        )

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
            "segunda_lectura_selectiva": segunda_lectura,
        })
        print(f"  Detecciones: {len(lineas)} | renglones: {len(renglones)}")
        print(f"  Formato estimado: {formato['tipo_estimado']}")

    documento.close()

    campos_finales, validaciones_cruzadas, control_calidad = consolidar_campos_v4(paginas)
    filiacion_global = next((p.get("campos_extraidos", {}).get("filiacion") for p in paginas
                             if p.get("campos_extraidos", {}).get("filiacion", {}).get("registros")),
                            {"estado": "sin_datos_suficientes", "registros": []})
    salida = {
        "lector": "lector_paddleocr_v4",
        "version_motor": "4.0-experimental",
        "estado": "experimental_no_produccion",
        "motor": "PaddleOCR",
        "modelo": "PP-OCRv5",
        "idioma": "es",
        "dpi": dpi,
        "limite_deteccion": limite,
        "estrategia": [
            "PaddleOCR_PP-OCRv5_como_motor_principal",
            "extraccion_geometrica_y_semantica_derivada_de_V3_3",
            "reglas_de_validacion_y_control_de_calidad_portadas_de_V19",
            "segunda_lectura_selectiva_de_campos_con_cajas_sospechosas",
            "sin_Tesseract_ni_autocorreccion_automatica",
            "revision_humana_obligatoria",
        ],
        "archivo_original": pdf_path.name,
        "campos": campos_finales,
        "secciones": {
            "persona_registrada": ["nombre", "primer_apellido", "segundo_apellido", "fecha_nacimiento", "sexo", "lugar_nacimiento", "nacionalidad"],
            "datos_registrales": ["oficialia", "fecha_registro", "libro", "numero_acta", "folio"],
            "identificadores": ["curp", "identificador_electronico", "codigo_verificacion"],
            "filiacion": filiacion_global,
        },
        "validaciones_cruzadas": validaciones_cruzadas,
        "control_calidad": control_calidad,
        "paginas": paginas,
        "nota": (
            "V4 integra reglas de validación y control de calidad de V19 con OCR PaddleOCR. "
            "No incorpora las funciones de reconocimiento Tesseract de V19. "
            "Todos los datos requieren cotejo humano y esta versión no es de producción."
        ),
    }

    json_path = raiz_salida / "resultado_paddleocr_v4.json"
    txt_path = raiz_salida / "resultado_paddleocr_v4.txt"
    csv_path = raiz_salida / "reporte_revision_humana_v4.csv"
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

    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "seccion", "campo", "valor_ocr", "confianza_ocr", "formato_valido",
            "detalle_validacion", "estado_ocr", "valor_confirmado_por_revisor", "observaciones"
        ])
        writer.writeheader()
        grupos = {
            "persona_registrada": ["nombre", "primer_apellido", "segundo_apellido", "fecha_nacimiento", "sexo", "lugar_nacimiento", "nacionalidad"],
            "datos_registrales": ["oficialia", "fecha_registro", "libro", "numero_acta", "folio"],
            "identificadores": ["curp", "identificador_electronico", "codigo_verificacion"],
        }
        for seccion, nombres in grupos.items():
            for campo in nombres:
                d = campos_finales[campo]
                writer.writerow({
                    "seccion": seccion, "campo": campo, "valor_ocr": d.get("valor") or "",
                    "confianza_ocr": d.get("confianza", ""), "formato_valido": d.get("formato_valido", False),
                    "detalle_validacion": d.get("detalle_validacion", ""), "estado_ocr": d.get("estado", ""),
                    "valor_confirmado_por_revisor": "", "observaciones": "",
                })
        for registro in filiacion_global.get("registros", []):
            for campo, d in registro.get("campos", {}).items():
                writer.writerow({
                    "seccion": f"filiacion_fila_{registro.get('registro')}", "campo": campo,
                    "valor_ocr": d.get("valor") or "", "confianza_ocr": d.get("confianza", ""),
                    "formato_valido": d.get("formato_valido", False), "detalle_validacion": d.get("detalle_validacion", ""),
                    "estado_ocr": d.get("estado", ""), "valor_confirmado_por_revisor": "", "observaciones": "",
                })

    print("\nPADDLEOCR V4 FINALIZADO — EXPERIMENTAL")
    for campo, dato in campos_finales.items():
        print(f"{campo}: {dato.get('valor') or 'NO IDENTIFICADO'} | válido={dato.get('formato_valido')} | estado={dato.get('estado')}")
    print(f"JSON: {json_path}")
    print(f"TXT:  {txt_path}")
    print(f"CSV:  {csv_path}")
    print(f"Salida: {raiz_salida}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Lector experimental PaddleOCR V4 para actas de nacimiento."
    )
    parser.add_argument("pdf", nargs="?", default=str(PDF_DEFAULT))
    parser.add_argument("--dpi", type=int, default=DPI_DEFAULT)
    parser.add_argument("--limite", type=int, default=OCR_LIMIT_DEFAULT)
    parser.add_argument("--salida", default=None)
    args = parser.parse_args()
    procesar(args.pdf, args.dpi, args.limite, args.salida)
