#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Programa: Aglomeración e Interés Turístico en Fines de Semana Largos (SerpApi - Google Trends)
Descripción: Evalúa el nivel de aglomeración, interés y afluencia de los 18 destinos turísticos
             de Uruguay (leídos dinámicamente desde 'Lugares turísticos.txt') durante los fines de semana
             largos del año en curso y de los 2 años anteriores (3 años en total).

Integración y Caché Compartido:
  - Utiliza el MISMO archivo de caché de feriados y findes largos ('fines_de_semana_largos_10anios.json')
    generado por Nager.Date. Si ya existe en disco, se reutiliza (0 llamadas a la API de feriados).
  - Consulta SerpApi (Google Trends) para medir la afluencia en cada rango de fechas.
  - Guarda los crudos en 'datos/crudo/serpapi_trends/' y el consolidado en
    'datos/derivado/aglomeracion_fechas_por_sitio.json'.
"""

import sys
import os
import re
import json
import time
import math
import shutil
import hashlib
import unicodedata
import asyncio
import argparse
import datetime
from pathlib import Path
import aiohttp
import requests

# Forzar codificación UTF-8 en terminal de Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

# ==============================================================================
# CONFIGURACIÓN PRINCIPAL
# ==============================================================================
# Ingrese su API Key de SerpApi aquí:
SERPAPI_API_KEY = "1f36ea1cf782e33e0a74e01846e72035b69bb14a1eb6994faec876e950d1c163"

SERPAPI_SEARCH_URL = "https://serpapi.com/search.json"
NAGER_BASE_URL = "https://date.nager.at/api/v3"
GEO_DEFAULT = "UY"

# Directorios de datos (relativos a Entregable)
BASE_DIR = Path(__file__).resolve().parent
DIR_CRUDO_NAGER = BASE_DIR / "datos" / "crudo" / "nager_date"
DIR_CRUDO_TRENDS = BASE_DIR / "datos" / "crudo" / "serpapi_trends"
DIR_DERIVADO = BASE_DIR / "datos" / "derivado"

ARCHIVO_TXT_DESTINOS = BASE_DIR / "Lugares turísticos.txt"
ARCHIVO_DERIVADO_FINDES_10A = DIR_DERIVADO / "fines_de_semana_largos_10anios.json"
ARCHIVO_DERIVADO_AGLOMERACION = DIR_DERIVADO / "aglomeracion_fechas_por_sitio.json"

DIAS_SEMANA = {
    0: "Lunes", 1: "Martes", 2: "Miércoles", 3: "Jueves",
    4: "Viernes", 5: "Sábado", 6: "Domingo"
}

# Modificadores de búsqueda para mejorar la sensibilidad en SerpApi Google Trends
TERMINOS_ESPECIALES = {
    "La Paloma": "La Paloma Rocha",
    "La Pedrera": "La Pedrera Rocha",
    "Minas": "Minas Lavalleja",
    "Atlántida": "Atlántida Canelones",
    "La Floresta": "La Floresta Canelones",
    "Salinas": "Salinas Canelones",
    "Santa Teresa": "Santa Teresa Rocha",
    "Las Termas de Guaviyú": "Termas de Guaviyú",
    "Las Termas del Daymán": "Termas del Daymán"
}


# ==============================================================================
# FUNCIONES DE UTILIDAD GENERAL
# ==============================================================================
def normalizar_slug(texto: str) -> str:
    """Convierte un texto a formato slug."""
    nfkd = unicodedata.normalize("NFKD", texto)
    solo_ascii = "".join([c for c in nfkd if not unicodedata.combining(c)])
    limpio = re.sub(r"[^\w\s-]", "", solo_ascii.lower()).strip()
    return re.sub(r"[-\s]+", "_", limpio)


def formatear_fecha(fecha_str: str) -> str:
    """Convierte 'YYYY-MM-DD' en 'Día DD/MM/YYYY'."""
    f = datetime.datetime.strptime(fecha_str, "%Y-%m-%d").date()
    dia_nombre = DIAS_SEMANA[f.weekday()]
    return f"{dia_nombre} {f.day:02d}/{f.month:02d}/{f.year}"


def calificar_afluencia(puntaje: float) -> str:
    """Clasifica el nivel de aglomeración según el puntaje de interés (0 a 100)."""
    if puntaje >= 75:
        return "Muy Alta / Saturado 🔴"
    elif puntaje >= 50:
        return "Alta 🟠"
    elif puntaje >= 25:
        return "Moderada 🟡"
    else:
        return "Baja 🟢"


# ==============================================================================
# LECTURA DE DESTINOS DESDE EL ARCHIVO .TXT
# ==============================================================================
def cargar_destinos_desde_txt() -> list:
    """
    Lee los destinos dinámicamente desde 'Lugares turísticos.txt'.
    Si no se encuentra o no se puede recuperar, ofrece ingresarlos por terminal
    en un bucle continuo hasta que el usuario ingrese 'False'.
    Retorna una lista de diccionarios [{'nombre': ..., 'departamento': ..., 'termino': ...}].
    """
    destinos = []
    if ARCHIVO_TXT_DESTINOS.exists():
        try:
            lineas = ARCHIVO_TXT_DESTINOS.read_text(encoding="utf-8").splitlines()
            for linea in lineas:
                linea = linea.strip()
                if not linea or "Lugares turísticos" in linea:
                    continue
                if linea.startswith("-"):
                    linea = linea[1:].strip()
                    
                match = re.match(r"^(.+?)\s*\((.+?)\)$", linea)
                if match:
                    nombre = match.group(1).strip()
                    depto = match.group(2).strip()
                    termino = TERMINOS_ESPECIALES.get(nombre, nombre)
                    destinos.append({
                        "nombre": nombre,
                        "departamento": depto,
                        "termino": termino
                    })
        except Exception as e:
            print(f"[WARN] Error al leer '{ARCHIVO_TXT_DESTINOS}': {e}", file=sys.stderr)

    if not destinos:
        print(f"\n[AVISO] No se pudo encontrar o recuperar '{ARCHIVO_TXT_DESTINOS.name}'.")
        print("Ingrese los destinos manualmente por terminal. Para finalizar, ingrese 'False'.\n")
        while True:
            entrada = input("Destino (o 'False' para terminar): ").strip()
            if not entrada:
                continue
            if entrada.lower() == "false":
                break
            match = re.match(r"^(.+?)\s*\((.+?)\)$", entrada)
            if match:
                nombre = match.group(1).strip()
                depto = match.group(2).strip()
            else:
                nombre = entrada
                depto = input(f"  Departamento para '{nombre}': ").strip()
                if not depto:
                    depto = "Uruguay"
            termino = TERMINOS_ESPECIALES.get(nombre, nombre)
            destinos.append({
                "nombre": nombre,
                "departamento": depto,
                "termino": termino
            })
            print(f"  -> Destino agregado: {nombre} ({depto})")

    return destinos


# ==============================================================================
# INTEGRACIÓN DEL CACHÉ COMPARTIDO DE FINES DE SEMANA LARGOS (NAGER.DATE)
# ==============================================================================
def traer_crudo_nager_local(nombre_archivo: str):
    """Revisa si existe el crudo de Nager.Date en Entregable o carpeta otros."""
    ruta = DIR_CRUDO_NAGER / f"{nombre_archivo}.json"
    
    if ruta.exists():
        try:
            return json.loads(ruta.read_text(encoding="utf-8"))
        except Exception:
            pass
    return None


async def descargar_nager_año_async(session: aiohttp.ClientSession, anio: int) -> tuple:
    """Descarga feriados y findes largos de un año si no están en caché."""
    clave_f = f"public_holidays_UY_{anio}"
    clave_w = f"long_weekends_UY_{anio}"
    
    crudo_f = traer_crudo_nager_local(clave_f)
    crudo_w = traer_crudo_nager_local(clave_w)
    
    if crudo_f is None:
        url_f = f"{NAGER_BASE_URL}/PublicHolidays/{anio}/UY"
        try:
            async with session.get(url_f, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    crudo_f = await resp.json()
                    DIR_CRUDO_NAGER.mkdir(parents=True, exist_ok=True)
                    (DIR_CRUDO_NAGER / f"{clave_f}.json").write_text(json.dumps(crudo_f, ensure_ascii=False, indent=2), encoding="utf-8")
                else: crudo_f = []
        except Exception: crudo_f = []

    if crudo_w is None:
        url_w = f"{NAGER_BASE_URL}/LongWeekend/{anio}/UY"
        try:
            async with session.get(url_w, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    crudo_w = await resp.json()
                    DIR_CRUDO_NAGER.mkdir(parents=True, exist_ok=True)
                    (DIR_CRUDO_NAGER / f"{clave_w}.json").write_text(json.dumps(crudo_w, ensure_ascii=False, indent=2), encoding="utf-8")
                else: crudo_w = []
        except Exception: crudo_w = []

    return anio, crudo_f or [], crudo_w or []


def parsear_findes_largos_año(crudo_feriados: list, crudo_findes: list, anio: int) -> list:
    """Empareja feriados con las fechas de findes largos."""
    feriados_map = {f["date"]: f for f in crudo_feriados if "date" in f}
    resultado = []
    
    for item in crudo_findes:
        inicio = datetime.datetime.strptime(item["startDate"], "%Y-%m-%d").date()
        fin = datetime.datetime.strptime(item["endDate"], "%Y-%m-%d").date()
        duracion = item.get("dayCount", (fin - inicio).days + 1)
        
        feriados_involucrados = []
        curr = inicio
        while curr <= fin:
            curr_str = curr.strftime("%Y-%m-%d")
            if curr_str in feriados_map:
                fer = feriados_map[curr_str]
                feriados_involucrados.append({
                    "fecha": curr_str,
                    "dia_semana": DIAS_SEMANA[curr.weekday()],
                    "nombre_local": fer.get("localName", "")
                })
            curr += datetime.timedelta(days=1)
            
        resultado.append({
            "anio": anio,
            "inicio": item["startDate"],
            "fin": item["endDate"],
            "inicio_formateado": formatear_fecha(item["startDate"]),
            "fin_formateado": formatear_fecha(item["endDate"]),
            "duracion_dias": duracion,
            "es_puente": item.get("needBridgeDay", False),
            "feriados": feriados_involucrados,
            "nombres_feriados": [f["nombre_local"] for f in feriados_involucrados]
        })
        
    resultado.sort(key=lambda x: x["inicio"])
    return resultado


async def obtener_findes_largos_compartidos(anio_actual: int, forzar_recarga: bool = False) -> dict:
    """
    Lee el archivo derivado compartido 'fines_de_semana_largos_10anios.json' si ya existe en disco.
    Si no existe, consulta Nager.Date y lo genera en el MISMO documento de caché.
    """
    if not forzar_recarga and ARCHIVO_DERIVADO_FINDES_10A.exists():
        try:
            datos = json.loads(ARCHIVO_DERIVADO_FINDES_10A.read_text(encoding="utf-8"))
            if isinstance(datos, dict) and "findes_largos_por_anio" in datos:
                print(f"[CACHÉ COMPARTIDO] Fines de semana largos leídos desde '{ARCHIVO_DERIVADO_FINDES_10A.name}' (0 llamadas API).")
                return datos
        except Exception:
            pass

    print("[RED WEB] El caché compartido no existe aún. Consultando Nager.Date para 10 años...")
    anios = list(range(anio_actual - 9, anio_actual + 1))
    
    async with aiohttp.ClientSession() as session:
        tareas = [descargar_nager_año_async(session, a) for a in anios]
        descargas = await asyncio.gather(*tareas)
        
    findes_por_año = {}
    for anio, crudo_f, crudo_w in descargas:
        findes_por_año[str(anio)] = parsear_findes_largos_año(crudo_f, crudo_w, anio)
        
    paquete = {
        "anio_actual": anio_actual,
        "pais": "UY",
        "anios_consultados": anios,
        "total_anios": len(anios),
        "ultima_actualizacion": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "findes_largos_por_anio": findes_por_año
    }
    
    try:
        DIR_DERIVADO.mkdir(parents=True, exist_ok=True)
        ARCHIVO_DERIVADO_FINDES_10A.write_text(json.dumps(paquete, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[WARN] No se pudo guardar el caché compartido: {e}", file=sys.stderr)
        
    return paquete


# ==============================================================================
# MEDIDOR DE AGLOMERACIÓN E INTERÉS HISTÓRICO (SERPAPI - GOOGLE TRENDS)
# ==============================================================================
def generar_nombre_crudo_trends(terminos: list, inicio: str, fin: str) -> str:
    """Genera un nombre determinístico para el archivo de caché en disco."""
    terminos_slug = "_".join([normalizar_slug(t)[:10] for t in terminos])
    hash_p = hashlib.md5(f"{','.join(terminos)}_{inicio}_{fin}".encode("utf-8")).hexdigest()[:8]
    return f"trends_{inicio}_al_{fin}_{terminos_slug}_{hash_p}.json"


def consultar_lote_serpapi_trends(terminos_map: dict, inicio: str, fin: str, api_key: str, forzar_recarga: bool = False) -> tuple:
    """Consulta SerpApi Google Trends para un rango de fechas y un lote de destinos. Retorna (dict_resultado, hubo_peticion_red)."""
    DIR_CRUDO_TRENDS.mkdir(parents=True, exist_ok=True)
    terminos_lista = list(terminos_map.keys())
    nombre_archivo = generar_nombre_crudo_trends(terminos_lista, inicio, fin)
    ruta = DIR_CRUDO_TRENDS / nombre_archivo

    datos = None
    hubo_red = False

    if not forzar_recarga:
        if ruta.exists():
            try:
                datos = json.loads(ruta.read_text(encoding="utf-8"))
            except Exception:
                datos = None

    if datos is None:
        if not api_key:
            raise RuntimeError(
                f"No hay caché para recuperar ni API Key para ingresar a SerpApi al consultar aglomeración ({inicio} al {fin})."
            )

        param_q = ", ".join(terminos_lista)
        param_date = f"{inicio} {fin}"
        params = {
            "engine": "google_trends",
            "q": param_q,
            "date": param_date,
            "geo": GEO_DEFAULT,
            "api_key": api_key
        }

        try:
            hubo_red = True
            resp = requests.get(SERPAPI_SEARCH_URL, params=params, timeout=25)
            if resp.status_code in [401, 403]:
                raise RuntimeError(
                    f"No hay caché para recuperar y la API Key es errónea para ingresar a SerpApi (HTTP {resp.status_code})."
                )
            datos = resp.json()
            if "error" in datos:
                raise RuntimeError(
                    f"No hay caché para recuperar y la API Key es errónea para ingresar a SerpApi: {datos['error']}"
                )
            resp.raise_for_status()
            ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
        except requests.exceptions.RequestException as e:
            raise RuntimeError(
                f"No hay caché para recuperar ni se pudo ingresar a SerpApi (o API Key errónea): {e}"
            )

    # Parsear respuesta de Google Trends (si es fecha futura o no hay interés, dejar nulo / '-')
    timeline = []
    if datos and isinstance(datos, dict) and "interest_over_time" in datos:
        timeline = datos.get("interest_over_time", {}).get("timeline_data", [])

    series_por_termino = {term: [] for term in terminos_map}

    for punto in timeline:
        valores = punto.get("values", [])
        if valores and isinstance(valores, list):
            for v in valores:
                query_name = v.get("query", "").strip()
                val_num = v.get("extracted_value", 0)
                for term in terminos_map:
                    if term.lower() == query_name.lower():
                        series_por_termino[term].append(int(val_num) if str(val_num).isdigit() else 0)
                        break
        elif "value" in punto:
            term_unico = list(terminos_map.keys())[0]
            val_num = punto.get("extracted_value", punto.get("value", 0))
            series_por_termino[term_unico].append(int(val_num) if str(val_num).isdigit() else 0)

    res = {}
    for term, meta in terminos_map.items():
        vals = series_por_termino[term]
        if vals and any(v > 0 for v in vals):
            prom = sum(vals) / len(vals)
            max_v = max(vals)
            res[meta["nombre"]] = {
                "departamento": meta["departamento"],
                "termino_busqueda": term,
                "promedio_interes": round(prom, 1),
                "max_interes": max_v,
                "nivel_afluencia": calificar_afluencia(prom),
                "datos_disponibles": True
            }
        else:
            # Fechas futuras o sin métricas registradas en Google Trends: sin datos / '-'
            res[meta["nombre"]] = {
                "departamento": meta["departamento"],
                "termino_busqueda": term,
                "promedio_interes": None,
                "max_interes": None,
                "nivel_afluencia": "-",
                "datos_disponibles": False
            }
        
    return res, hubo_red


# ==============================================================================
# PROCESAMIENTO CONSOLIDADOS DE AGLOMERACIÓN (3 AÑOS: ACTUAL Y 2 ANTERIORES)
# ==============================================================================
def procesar_aglomeraciones_3anios(destinos: list, paquete_findes: dict, api_key: str, forzar_recarga: bool = False) -> dict:
    """
    Evalúa la aglomeración de todos los destinos para los findes largos del año actual
    y de los 2 años anteriores (3 años en total). Reutiliza y actualiza la caché derivada.
    """
    anio_actual = paquete_findes["anio_actual"]
    anios_evaluacion = [anio_actual - 2, anio_actual - 1, anio_actual]
    findes_por_año = paquete_findes["findes_largos_por_anio"]

    print("\n" + "=" * 110)
    print("  ANÁLISIS DE AGLOMERACIÓN E INTERÉS TURÍSTICO EN FINES DE SEMANA LARGOS (3 AÑOS)")
    print(f"  Años analizados: {anios_evaluacion} | Destinos evaluados: {len(destinos)}")
    print("=" * 110 + "\n")

    # Verificar si el consolidado derivado ya tiene todos los destinos y años requeridos
    derivado_existente = None
    if not forzar_recarga and ARCHIVO_DERIVADO_AGLOMERACION.exists():
        try:
            derivado_existente = json.loads(ARCHIVO_DERIVADO_AGLOMERACION.read_text(encoding="utf-8"))
        except Exception:
            derivado_existente = None

    if derivado_existente and isinstance(derivado_existente, dict):
        destinos_guardados = {d["nombre"].lower() for d in derivado_existente.get("destinos", [])}
        anios_guardados = set(derivado_existente.get("aglomeraciones_por_año", {}).keys())
        destinos_pedidos = {d["nombre"].lower() for d in destinos}
        anios_pedidos = {str(a) for a in anios_evaluacion}

        if destinos_pedidos.issubset(destinos_guardados) and anios_pedidos.issubset(anios_guardados) and not forzar_recarga:
            print(f"✅ [CACHÉ CONSOLIDADO] Aglomeración para {len(destinos)} destinos y 3 años recuperada instantáneamente desde '{ARCHIVO_DERIVADO_AGLOMERACION.name}'.")
            return derivado_existente

    TAMAÑO_LOTE = 5
    lotes_destinos = [destinos[i:i + TAMAÑO_LOTE] for i in range(0, len(destinos), TAMAÑO_LOTE)]

    resultados_por_año = derivado_existente.get("aglomeraciones_por_año", {}) if (derivado_existente and not forzar_recarga) else {}

    for anio in anios_evaluacion:
        findes_a = findes_por_año.get(str(anio), [])
        print(f"📅 Procesando año {anio} ({len(findes_a)} fines de semana largos)...")
        
        findes_resultados = []
        
        for f in findes_a:
            inicio = f["inicio"]
            fin = f["fin"]
            nombres_feriados = ", ".join(f.get("nombres_feriados", [])) if f.get("nombres_feriados") else "Finde Largo"
            
            aglomeracion_destinos_finde = {}
            
            for lote in lotes_destinos:
                terminos_map = {d["termino"]: d for d in lote}
                res_lote, hubo_red = consultar_lote_serpapi_trends(terminos_map, inicio, fin, api_key, forzar_recarga=forzar_recarga)
                aglomeracion_destinos_finde.update(res_lote)
                if hubo_red:
                    time.sleep(0.5)

            findes_resultados.append({
                "inicio": inicio,
                "fin": fin,
                "duracion_dias": f["duracion_dias"],
                "feriados": nombres_feriados,
                "aglomeracion_por_destino": aglomeracion_destinos_finde
            })
            
        resultados_por_año[str(anio)] = findes_resultados

    # Consolidar estructura derivada actualizada
    paquete_resultado = {
        "metadata": {
            "fecha_analisis": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "anio_actual": anio_actual,
            "anios_analizados": anios_evaluacion,
            "total_destinos": len(destinos),
            "fuente": "SerpApi (Google Trends Engine) + Nager.Date"
        },
        "destinos": destinos,
        "aglomeraciones_por_año": resultados_por_año
    }

    try:
        DIR_DERIVADO.mkdir(parents=True, exist_ok=True)
        ARCHIVO_DERIVADO_AGLOMERACION.write_text(json.dumps(paquete_resultado, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n✅ [DERIVADO GUARDADO] Consolidado guardado y actualizado en '{ARCHIVO_DERIVADO_AGLOMERACION}'.")
    except Exception as e:
        print(f"[WARN] No se pudo guardar derivado de aglomeración: {e}", file=sys.stderr)

    return paquete_resultado


# ==============================================================================
# VISUALIZACIÓN EN TERMINAL
# ==============================================================================
def imprimir_reporte_aglomeraciones(resultado: dict, destino_filtro: str = None):
    """Imprime una tabla completa comparativa de aglomeración por destino y año."""
    sep = "=" * 128
    subsep = "-" * 128

    meta = resultado["metadata"]
    anios = [str(a) for a in meta["anios_analizados"]]
    destinos = resultado["destinos"]
    
    if destino_filtro:
        destinos = [d for d in destinos if destino_filtro.lower() in d["nombre"].lower()]

    print("\n" + sep)
    print("📊 REPORTE COMPARATIVO DE AGLOMERACIÓN E INTERÉS TURÍSTICO EN FINES DE SEMANA LARGOS")
    print(f"   Período histórico: Años {anios[0]}, {anios[1]} y {anios[2]} (Año Actual)")
    print(sep)

    for d in destinos:
        nom = d["nombre"]
        dep = d["departamento"]
        print(f"\n📍 DESTINO: {nom} ({dep})")
        print(f"{'Año':<6} | {'Inicio':<11} | {'Fin':<11} | {'Días':<5} | {'Feriado / Motivo':<35} | {'Índice (0-100)':<15} | {'Nivel de Aglomeración'}")
        print(subsep)

        for a_str in sorted(resultado["aglomeraciones_por_año"].keys(), reverse=True):
            findes_a = resultado["aglomeraciones_por_año"][a_str]
            for f in findes_a:
                fer = f["feriados"][:33] + ".." if len(f["feriados"]) > 35 else f["feriados"]
                info_aglo = f["aglomeracion_por_destino"].get(nom, {})
                puntaje = info_aglo.get("promedio_interes")
                puntaje_str = f"{puntaje:.1f}" if puntaje is not None else "-"
                nivel = info_aglo.get("nivel_afluencia") or "-"
                
                marca_actual = " 👈" if a_str == str(meta["anio_actual"]) else ""
                print(f"{a_str:<6} | {f['inicio']:<11} | {f['fin']:<11} | {f['duracion_dias']:<5} | {fer:<35} | {puntaje_str:<15} | {nivel}{marca_actual}")
        print(subsep)

    print("\n" + sep + "\n")


# ==============================================================================
# PUNTO DE ENTRADA (CLI)
# ==============================================================================
def main():
    parser = argparse.ArgumentParser(
        description="Evalúa la aglomeración de destinos turísticos en fines de semana largos de este año y 2 anteriores con SerpApi."
    )
    parser.add_argument("--destino", type=str, default=None, help="Filtrar por un destino específico al mostrar el reporte (ej: --destino 'Punta del Este')")
    parser.add_argument("--recargar", action="store_true", help="Ignora el caché local y forzar la recarga desde las APIs")
    parser.add_argument("--json", action="store_true", help="Imprimir los resultados consolidados en JSON")
    parser.add_argument("-o", "--output", type=str, default=None, help="Guardar copia del resultado JSON en la ruta especificada")

    args = parser.parse_args()

    t0 = time.perf_counter()
    anio_actual = datetime.date.today().year

    # 1. Cargar destinos desde 'Lugares turísticos.txt' (con fallback a terminal si falta)
    destinos = cargar_destinos_desde_txt()
    if not destinos:
        print("[ERROR] No se proporcionaron destinos para procesar.", file=sys.stderr)
        sys.exit(1)

    # 2. Cargar/reutilizar el MISMO caché compartido de findes largos de Nager.Date
    paquete_findes = asyncio.run(obtener_findes_largos_compartidos(anio_actual, forzar_recarga=args.recargar))

    # 3. API Key configurada directamente en el código, por entorno o solicitada por terminal
    api_key = SERPAPI_API_KEY.strip() or os.environ.get("SERPAPI_API_KEY", "").strip()
    if not api_key:
        api_key = input("Ingrese su API Key de SerpApi (presione Enter si usará datos en caché): ").strip()

    # 4. Procesar aglomeraciones para 3 años
    resultado = procesar_aglomeraciones_3anios(destinos, paquete_findes, api_key, forzar_recarga=args.recargar)
    tiempo_total = time.perf_counter() - t0

    if args.json:
        print(json.dumps(resultado, ensure_ascii=False, indent=2))
    else:
        imprimir_reporte_aglomeraciones(resultado, args.destino)
        print(f"⚡ Rendimiento de ejecución: {tiempo_total:.2f} segundos")
        print(f"💾 Archivo derivado guardado en: '{ARCHIVO_DERIVADO_AGLOMERACION}'\n")

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[INFO] Copia guardada en '{out_path}'")


if __name__ == "__main__":
    main()
