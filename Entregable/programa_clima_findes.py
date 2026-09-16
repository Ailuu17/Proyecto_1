#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Programa Principal: Recolector y Comparador del Clima en Fines de Semana Largos (10 Años)
Descripción: Cruza la información de Nominatim OSM (coordenadas), Nager.Date (feriados y findes largos)
             y Open-Meteo Archive (clima histórico) para 18 destinos turísticos en Uruguay.
             Integra toda la arquitectura de datos, peticiones asíncronas y caché por capas en un único archivo.
"""

import sys
import os
import time
import json
import re
import math
import shutil
import unicodedata
import asyncio
import argparse
import datetime
from pathlib import Path
import aiohttp
import requests

# Forzar codificación UTF-8 en salida de terminal para Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

# ==============================================================================
# CONFIGURACIÓN Y CONSTANTES DEL SISTEMA
# ==============================================================================
BASE_DIR = Path(__file__).resolve().parent
DIR_CRUDO_NOMINATIM = BASE_DIR / "datos" / "crudo" / "nominatim"
DIR_CRUDO_NAGER = BASE_DIR / "datos" / "crudo" / "nager_date"
DIR_CRUDO_METEO = BASE_DIR / "datos" / "crudo" / "open_meteo"
DIR_DERIVADO = BASE_DIR / "datos" / "derivado"

ARCHIVO_TXT_DESTINOS = BASE_DIR / "Lugares turísticos.txt"
ARCHIVO_DERIVADO_COORDS = DIR_DERIVADO / "coordenadas_lugares_turisticos.json"
ARCHIVO_DERIVADO_FINDES_10A = DIR_DERIVADO / "fines_de_semana_largos_10anios.json"
ARCHIVO_DERIVADO_CLIMA_10A = DIR_DERIVADO / "clima_findes_largos_10anios.json"

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NAGER_BASE_URL = "https://date.nager.at/api/v3"
METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

USER_AGENT = "IndiceEscapadaUruguay/1.0 (proyecto-academico-programacion)"
HEADERS_NOMINATIM = {"User-Agent": USER_AGENT}

DIAS_SEMANA = {
    0: "Lunes", 1: "Martes", 2: "Miércoles", 3: "Jueves",
    4: "Viernes", 5: "Sábado", 6: "Domingo"
}



QUERIES_ESPECIALES_NOMINATIM = {
    "Las Termas de Guaviyú": ["Termas de Guaviyú, Paysandú, Uruguay", "Guaviyu, Paysandu, Uruguay"],
    "Las Termas del Daymán": ["Termas del Daymán, Salto, Uruguay", "Dayman, Salto, Uruguay"],
    "Santa Teresa": ["Fortaleza de Santa Teresa, Rocha, Uruguay", "Santa Teresa, Rocha, Uruguay"],
    "Piriápolis": ["Piriápolis, Maldonado, Uruguay", "Piriapolis, Maldonado, Uruguay"],
    "Punta Ballena": ["Punta Ballena, Maldonado, Uruguay", "Punta Ballena, Uruguay"]
}


# ==============================================================================
# FUNCIONES DE UTILIDAD GENERAL
# ==============================================================================
def normalizar_clave(texto: str) -> str:
    """Convierte un texto con tildes/espacios a formato slug."""
    nfkd = unicodedata.normalize("NFKD", texto)
    solo_ascii = "".join([c for c in nfkd if not unicodedata.combining(c)])
    limpio = re.sub(r"[^\w\s-]", "", solo_ascii.lower()).strip()
    return re.sub(r"[-\s]+", "_", limpio)


def formatear_fecha(fecha_str: str) -> str:
    """Convierte 'YYYY-MM-DD' en 'Día DD/MM/YYYY'."""
    f = datetime.datetime.strptime(fecha_str, "%Y-%m-%d").date()
    dia_nombre = DIAS_SEMANA[f.weekday()]
    return f"{dia_nombre} {f.day:02d}/{f.month:02d}/{f.year}"


def generar_rango_fechas(fecha_inicio_str: str, fecha_fin_str: str) -> set:
    """Genera conjunto de fechas ISO 'YYYY-MM-DD' entre inicio y fin inclusive."""
    d_inicio = datetime.datetime.strptime(fecha_inicio_str, "%Y-%m-%d").date()
    d_fin = datetime.datetime.strptime(fecha_fin_str, "%Y-%m-%d").date()
    fechas = set()
    actual = d_inicio
    while actual <= d_fin:
        fechas.add(actual.strftime("%Y-%m-%d"))
        actual += datetime.timedelta(days=1)
    return fechas


# ==============================================================================
# CAPA 1: LECTURA DE DESTINOS Y COORDENADAS (NOMINATIM OSM)
# ==============================================================================
def cargar_destinos_desde_txt() -> list:
    """
    Lee el archivo 'Lugares turísticos.txt' y extrae la lista de (nombre, departamento).
    Si no se encuentra o no se puede recuperar, ofrece ingresarlos por terminal
    en un bucle continuo hasta que el usuario ingrese 'False'.
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
                    destinos.append((nombre, depto))
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
            destinos.append((nombre, depto))
            print(f"  -> Destino agregado: {nombre} ({depto})")

    return destinos


def pedir_nominatim(queries: list) -> list:
    """Petición a Nominatim OSM respetando 1s de rate-limit."""
    for q in queries:
        params = {"q": q, "format": "json", "limit": 1, "countrycodes": "uy", "addressdetails": 1}
        try:
            time.sleep(1.1)
            response = requests.get(NOMINATIM_URL, params=params, headers=HEADERS_NOMINATIM, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data and len(data) > 0:
                    return data
        except requests.exceptions.RequestException:
            pass
    return None


def obtener_coordenadas_destinos(forzar_recarga: bool = False) -> list:
    """Obtiene coordenadas de los destinos utilizando caché por capas."""
    destinos_txt = cargar_destinos_desde_txt()
    resultados = []

    # Verificar derivado existente para acelerar lectura
    coords_guardadas = {}
    if not forzar_recarga and ARCHIVO_DERIVADO_COORDS.exists():
        try:
            derivado = json.loads(ARCHIVO_DERIVADO_COORDS.read_text(encoding="utf-8"))
            for item in derivado:
                coords_guardadas[item["nombre"].lower()] = item
        except Exception:
            pass
    
    for nombre, depto in destinos_txt:
        nom_low = nombre.lower()
        if not forzar_recarga and nom_low in coords_guardadas:
            cached_item = dict(coords_guardadas[nom_low])
            cached_item["origen"] = "Caché Derivado"
            resultados.append(cached_item)
            continue

        clave = normalizar_clave(f"{nombre}_{depto}")
        ruta_crudo = DIR_CRUDO_NOMINATIM / f"{clave}.json"
        
        crudo = None
        origen = "API Nominatim (Red)"
        
        if not forzar_recarga:
            if ruta_crudo.exists():
                try:
                    crudo = json.loads(ruta_crudo.read_text(encoding="utf-8"))
                    origen = "Caché Disco"
                except Exception:
                    pass

        if crudo is None:
            queries = QUERIES_ESPECIALES_NOMINATIM.get(nombre, [f"{nombre}, {depto}, Uruguay", f"{nombre}, Uruguay"])
            crudo = pedir_nominatim(queries)
            if crudo:
                DIR_CRUDO_NOMINATIM.mkdir(parents=True, exist_ok=True)
                ruta_crudo.write_text(json.dumps(crudo, ensure_ascii=False, indent=2), encoding="utf-8")
                
        # Parsear crudo
        if crudo and len(crudo) > 0:
            res = crudo[0]
            lat = float(res["lat"])
            lon = float(res["lon"])
            osm_display = res.get("display_name", "")
        else:
            lat, lon, osm_display = None, None, "No encontrado"
            
        resultados.append({
            "nombre": nombre,
            "departamento": depto,
            "latitud": lat,
            "longitud": lon,
            "osm_display_name": osm_display,
            "origen": origen
        })

    # Guardar o actualizar derivado
    try:
        DIR_DERIVADO.mkdir(parents=True, exist_ok=True)
        # Combinar existentes con nuevos
        mapa_final = dict(coords_guardadas)
        for item in resultados:
            mapa_final[item["nombre"].lower()] = {k: v for k, v in item.items() if k != "origen"}
        datos_limpios = list(mapa_final.values())
        ARCHIVO_DERIVADO_COORDS.write_text(json.dumps(datos_limpios, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[WARN] No se pudo guardar el derivado de coordenadas: {e}", file=sys.stderr)
        
    return resultados


# ==============================================================================
# CAPA 2: OBTENCIÓN ASÍNCRONA DE FINES DE SEMANA LARGOS (NAGER.DATE 10 AÑOS)
# ==============================================================================
async def descargar_nager_año(session: aiohttp.ClientSession, anio: int, pais: str = "UY",
                              forzar_recarga: bool = False) -> tuple:
    """Descarga/recupera feriados y findes largos para un año."""
    clave_f = f"public_holidays_{pais}_{anio}"
    clave_w = f"long_weekends_{pais}_{anio}"
    
    ruta_f = DIR_CRUDO_NAGER / f"{clave_f}.json"
    ruta_w = DIR_CRUDO_NAGER / f"{clave_w}.json"

    crudo_f, crudo_w = None, None
    origen = "Caché Disco"
    
    if not forzar_recarga:
        if ruta_f.exists() and ruta_w.exists():
            try:
                crudo_f = json.loads(ruta_f.read_text(encoding="utf-8"))
                crudo_w = json.loads(ruta_w.read_text(encoding="utf-8"))
            except Exception:
                pass
              
    if crudo_f is None:
        url_f = f"{NAGER_BASE_URL}/PublicHolidays/{anio}/{pais}"
        try:
            async with session.get(url_f, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    crudo_f = await resp.json()
                    DIR_CRUDO_NAGER.mkdir(parents=True, exist_ok=True)
                    ruta_f.write_text(json.dumps(crudo_f, ensure_ascii=False, indent=2), encoding="utf-8")
                    origen = "API Nager.Date"
        except Exception:
            crudo_f = []

    if crudo_w is None:
        url_w = f"{NAGER_BASE_URL}/LongWeekend/{anio}/{pais}"
        try:
            async with session.get(url_w, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    crudo_w = await resp.json()
                    DIR_CRUDO_NAGER.mkdir(parents=True, exist_ok=True)
                    ruta_w.write_text(json.dumps(crudo_w, ensure_ascii=False, indent=2), encoding="utf-8")
                    origen = "API Nager.Date"
        except Exception:
            crudo_w = []

    return anio, crudo_f or [], crudo_w or [], origen


def parsear_findes_largos_año(crudo_feriados: list, crudo_findes: list, anio: int) -> list:
    """Parsea los feriados y los empareja con las fechas de findes largos."""
    feriados_map = {f["date"]: f for f in crudo_feriados if "date" in f}
    resultado = []
    
    for item in crudo_findes:
        es_puente = item.get("needBridgeDay", False)
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
                    "nombre_local": fer.get("localName", ""),
                    "nombre_ingles": fer.get("name", "")
                })
            curr += datetime.timedelta(days=1)
            
        resultado.append({
            "anio": anio,
            "inicio": item["startDate"],
            "fin": item["endDate"],
            "inicio_formateado": formatear_fecha(item["startDate"]),
            "fin_formateado": formatear_fecha(item["endDate"]),
            "duracion_dias": duracion,
            "es_puente": es_puente,
            "dias_puente": item.get("bridgeDays", []),
            "feriados": feriados_involucrados,
            "nombres_feriados": [f["nombre_local"] for f in feriados_involucrados]
        })
        
    resultado.sort(key=lambda x: x["inicio"])
    return resultado


async def obtener_findes_largos_10anios_async(anio_actual: int, forzar_recarga: bool = False) -> dict:
    """Obtiene los fines de semana largos para los 10 años en paralelo."""
    anios = list(range(anio_actual - 9, anio_actual + 1))

    if not forzar_recarga and ARCHIVO_DERIVADO_FINDES_10A.exists():
        try:
            datos = json.loads(ARCHIVO_DERIVADO_FINDES_10A.read_text(encoding="utf-8"))
            anios_guardados = set(datos.get("findes_largos_por_anio", {}).keys())
            anios_pedidos = {str(a) for a in anios}
            if anios_pedidos.issubset(anios_guardados):
                return datos
        except Exception:
            pass

    async with aiohttp.ClientSession() as session:
        tareas = [descargar_nager_año(session, a, "UY", forzar_recarga) for a in anios]
        descargas = await asyncio.gather(*tareas)
        
    findes_por_año = {}
    for anio, crudo_f, crudo_w, origen in descargas:
        parsed = parsear_findes_largos_año(crudo_f, crudo_w, anio)
        findes_por_año[str(anio)] = parsed
        
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
        print(f"[WARN] No se pudo guardar derivado de findes: {e}", file=sys.stderr)
        
    return paquete


# ==============================================================================
# CAPA 3: RECOLECCIÓN ASÍNCRONA DE CLIMA (OPEN-METEO ARCHIVE 10 AÑOS)
# ==============================================================================



async def descargar_clima_destino_año(session: aiohttp.ClientSession, destino: dict, anio: int,
                                      forzar_recarga: bool = False,
                                      semaforo: asyncio.Semaphore = None) -> tuple:
    """Descarga o recupera de caché el clima diario de un destino para un año."""
    nom = destino["nombre"]
    dep = destino["departamento"]
    lat = destino["latitud"]
    lon = destino["longitud"]
    clave = normalizar_clave(nom)
    
    nombre_archivo = f"clima_{clave}_{anio}.json"
    ruta = DIR_CRUDO_METEO / nombre_archivo
  
    if not forzar_recarga:
        for r in [ruta]:
            if r.exists():
                try:
                    datos = json.loads(r.read_text(encoding="utf-8"))
                    if isinstance(datos, dict) and "daily" in datos and "time" in datos["daily"]:
                        if r != ruta:
                            DIR_CRUDO_METEO.mkdir(parents=True, exist_ok=True)
                            shutil.copy(r, ruta)
                        return nom, dep, anio, datos, "Caché Disco"
                except Exception:
                    pass
                    
    hoy = datetime.date.today()
    end_date = f"{anio}-12-31"
    if anio == hoy.year:
        end_date = (hoy - datetime.timedelta(days=4)).strftime("%Y-%m-%d")
        
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": f"{anio}-01-01",
        "end_date": end_date,
        "daily": [
            "temperature_2m_max", "temperature_2m_min", "temperature_2m_mean",
            "precipitation_sum", "wind_speed_10m_max"
        ],
        "timezone": "America/Montevideo"
    }
    
    MAX_REINTENTOS = 4
    ESPERA_BASE_SEG = 10  # segundos de espera ante error 429, se duplica en cada reintento

    async with semaforo if semaforo else asyncio.Semaphore(2):
        await asyncio.sleep(0.3)
        for intento in range(1, MAX_REINTENTOS + 1):
            try:
                async with session.get(METEO_ARCHIVE_URL, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status == 200:
                        datos = await resp.json()
                        DIR_CRUDO_METEO.mkdir(parents=True, exist_ok=True)
                        ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
                        return nom, dep, anio, datos, "Open-Meteo API"
                    elif resp.status == 429:
                        espera = ESPERA_BASE_SEG * (2 ** (intento - 1))
                        print(f"[RATE LIMIT] {nom} {anio} — demasiadas peticiones. Reintento {intento}/{MAX_REINTENTOS} en {espera}s...", file=sys.stderr)
                        await asyncio.sleep(espera)
                    else:
                        print(f"[WARN] {nom} {anio} — HTTP {resp.status}. Reintento {intento}/{MAX_REINTENTOS}...", file=sys.stderr)
                        await asyncio.sleep(ESPERA_BASE_SEG)
            except Exception as e:
                print(f"[ERROR] {nom} {anio} — {e}. Reintento {intento}/{MAX_REINTENTOS}...", file=sys.stderr)
                await asyncio.sleep(ESPERA_BASE_SEG)

        print(f"[SKIP] {nom} {anio} — sin datos tras {MAX_REINTENTOS} reintentos. Se omite este año/destino.", file=sys.stderr)
        return nom, dep, anio, None, "Sin datos"


async def recolectar_clima_10anios_async(destinos: list, anios: list, forzar_recarga: bool = False) -> list:
    """Descarga en paralelo la información meteorológica de todos los destinos y años."""
    semaforo = asyncio.Semaphore(3)
    connector = aiohttp.TCPConnector(limit=5)
    
    async with aiohttp.ClientSession(connector=connector) as session:
        tareas = [
            descargar_clima_destino_año(session, d, a, forzar_recarga, semaforo)
            for d in destinos for a in anios
        ]
        return await asyncio.gather(*tareas)


def procesar_estadisticas_clima_10anios(destinos: list, paquete_findes: dict, descargas_clima: list) -> dict:
    """Calcula y estructura las estadísticas climáticas por destino y por año."""
    anio_actual = paquete_findes["anio_actual"]
    anios_consultados = paquete_findes["anios_consultados"]
    findes_por_año = paquete_findes["findes_largos_por_anio"]
    
    mapa_clima = {}
    origenes_cont = {"Caché Disco": 0, "Open-Meteo API": 0, "Estimación Climatológica": 0}
    
    for nom, dep, a, datos, origen in descargas_clima:
        if nom not in mapa_clima:
            mapa_clima[nom] = {}
        if datos and "daily" in datos:
            mapa_clima[nom][a] = datos["daily"]
            origenes_cont[origen] = origenes_cont.get(origen, 0) + 1

    resumen_destinos = []
    
    for d in destinos:
        nom = d["nombre"]
        dep = d["departamento"]
        lat = d["latitud"]
        lon = d["longitud"]
        
        datos_por_año = {}
        
        for a in anios_consultados:
            daily = mapa_clima.get(nom, {}).get(a)
            findes_a = findes_por_año.get(str(a), [])
            
            if not daily or "time" not in daily:
                datos_por_año[str(a)] = {"total_findes": len(findes_a), "findes": []}
                continue
                
            fechas_serie = daily.get("time", [])
            t_max_serie = daily.get("temperature_2m_max", [])
            t_min_serie = daily.get("temperature_2m_min", [])
            t_mean_serie = daily.get("temperature_2m_mean", [])
            precip_serie = daily.get("precipitation_sum", [])
            viento_serie = daily.get("wind_speed_10m_max", [])
            
            mapa_dias = {}
            for i, fecha in enumerate(fechas_serie):
                t_max_v = t_max_serie[i] if i < len(t_max_serie) else None
                t_min_v = t_min_serie[i] if i < len(t_min_serie) else None
                t_mean_v = (
                    t_mean_serie[i]
                    if (t_mean_serie and i < len(t_mean_serie) and t_mean_serie[i] is not None)
                    else ((t_max_v + t_min_v) / 2.0 if (t_max_v is not None and t_min_v is not None) else None)
                )
                precip_v = precip_serie[i] if i < len(precip_serie) else None
                viento_v = viento_serie[i] if (viento_serie and i < len(viento_serie)) else None
                
                mapa_dias[fecha] = {
                    "t_max": t_max_v, "t_min": t_min_v, "t_mean": t_mean_v,
                    "precip": precip_v, "viento": viento_v
                }
                
            detalles_findes = []
            for f in findes_a:
                rango_fechas = sorted(list(generar_rango_fechas(f["inicio"], f["fin"])))
                f_tmax, f_tmin, f_tmean, f_precip, f_viento = [], [], [], [], []
                dias_con_lluvia = 0
                
                for fecha in rango_fechas:
                    if fecha in mapa_dias:
                        v = mapa_dias[fecha]
                        if v["t_max"] is not None: f_tmax.append(v["t_max"])
                        if v["t_min"] is not None: f_tmin.append(v["t_min"])
                        if v["t_mean"] is not None: f_tmean.append(v["t_mean"])
                        if v["precip"] is not None:
                            f_precip.append(v["precip"])
                            if v["precip"] >= 0.5: dias_con_lluvia += 1
                        if v["viento"] is not None: f_viento.append(v["viento"])
                        
                nombres_feriados = ", ".join(f.get("nombres_feriados", [])) if f.get("nombres_feriados") else "Fin de semana largo"
                
                detalles_findes.append({
                    "inicio": f["inicio"],
                    "fin": f["fin"],
                    "duracion_dias": len(rango_fechas),
                    "es_puente": f.get("es_puente", False),
                    "feriados": nombres_feriados,
                    "temp_max_promedio": round(sum(f_tmax) / len(f_tmax), 2) if f_tmax else None,
                    "temp_min_promedio": round(sum(f_tmin) / len(f_tmin), 2) if f_tmin else None,
                    "temp_media_promedio": round(sum(f_tmean) / len(f_tmean), 2) if f_tmean else None,
                    "precipitacion_total_mm": round(sum(f_precip), 2) if f_precip else 0.0,
                    "precipitacion_diaria_promedio_mm": round(sum(f_precip) / len(f_precip), 2) if f_precip else 0.0,
                    "dias_con_lluvia": dias_con_lluvia,
                    "viento_max_promedio_kmh": round(sum(f_viento) / len(f_viento), 2) if f_viento else None
                })
                
            datos_por_año[str(a)] = {
                "total_findes": len(detalles_findes),
                "findes": detalles_findes
            }

        resumen_destinos.append({
            "nombre": nom,
            "departamento": dep,
            "latitud": lat,
            "longitud": lon,
            "clima_por_año": datos_por_año
        })

    paquete_resultado = {
        "anio_actual": anio_actual,
        "anios_consultados": anios_consultados,
        "total_destinos": len(resumen_destinos),
        "fecha_generacion": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "origenes_datos": origenes_cont,
        "destinos": resumen_destinos
    }

    try:
        DIR_DERIVADO.mkdir(parents=True, exist_ok=True)
        ARCHIVO_DERIVADO_CLIMA_10A.write_text(json.dumps(paquete_resultado, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[WARN] No se pudo guardar derivado de clima: {e}", file=sys.stderr)
        
    return paquete_resultado


# ==============================================================================
# CAPA 4: VISUALIZACIÓN Y REPORTES EN TERMINAL
# ==============================================================================
def imprimir_encabezado(anio_actual: int, total_destinos: int, anios_consultados: list):
    """Imprime el banner inicial del programa."""
    sep = "=" * 138
    print("\n" + sep)
    print("  ANÁLISIS CLIMÁTICO EN FINES DE SEMANA LARGOS - URUGUAY")
    print(f"  Año en curso: {anio_actual} | Período histórico: {anios_consultados[0]} - {anios_consultados[-1]} ({len(anios_consultados)} años)")
    print(f"  Destinos turísticos analizados: {total_destinos} (desde 'Lugares turísticos.txt')")
    print("  APIs integradas: Nominatim OSM (coordenadas) + Nager.Date (feriados) + Open-Meteo Archive (clima)")
    print(sep)


def imprimir_tabla_resumen_año_actual(resultado: dict, destino_filtro: str = None):
    """Muestra los datos meteorológicos de los fines de semana largos del año actual."""
    sep = "=" * 128
    subsep = "-" * 128
    
    anio_actual = str(resultado["anio_actual"])
    destinos = resultado["destinos"]
    
    if destino_filtro:
        destinos = [d for d in destinos if destino_filtro.lower() in d["nombre"].lower()]
        
    print("\n" + sep)
    print(f"  1. RESUMEN CLIMÁTICO DEL AÑO EN CURSO ({anio_actual}) - FINES DE SEMANA LARGOS")
    print(sep)
    
    header = (
        f"{'#':<3} | {'Destino':<25} | {'Depto':<12} | "
        f"{'T. Máx (2026)':<13} | {'T. Mín (2026)':<13} | {'T. Media':<11} | "
        f"{'Lluvia Tot':<12} | {'Viento Máx':<12}"
    )
    print(header)
    print(subsep)
    
    for i, d in enumerate(destinos, 1):
        num = f"{i:02d}"
        nom = d["nombre"]
        dep = d["departamento"]
        
        datos_actual = d["clima_por_año"].get(anio_actual, {}).get("findes", [])
        
        t_max_list = [f["temp_max_promedio"] for f in datos_actual if f["temp_max_promedio"] is not None]
        t_min_list = [f["temp_min_promedio"] for f in datos_actual if f["temp_min_promedio"] is not None]
        t_med_list = [f["temp_media_promedio"] for f in datos_actual if f["temp_media_promedio"] is not None]
        precip_list = [f["precipitacion_total_mm"] for f in datos_actual if f["precipitacion_total_mm"] is not None]
        viento_list = [f["viento_max_promedio_kmh"] for f in datos_actual if f.get("viento_max_promedio_kmh") is not None]
        
        t_max_str = f"{sum(t_max_list)/len(t_max_list):.1f} °C" if t_max_list else "N/D"
        t_min_str = f"{sum(t_min_list)/len(t_min_list):.1f} °C" if t_min_list else "N/D"
        t_med_str = f"{sum(t_med_list)/len(t_med_list):.1f} °C" if t_med_list else "N/D"
        precip_str = f"{sum(precip_list):.1f} mm" if precip_list else "0.0 mm"
        viento_str = f"{sum(viento_list)/len(viento_list):.1f} km/h" if viento_list else "N/D"
        
        print(f"{num:<3} | {nom:<25} | {dep:<12} | {t_max_str:<13} | {t_min_str:<13} | {t_med_str:<11} | {precip_str:<12} | {viento_str:<12}")

    print(sep)


def imprimir_comparativa_historica(resultado: dict, destino_filtro: str = None):
    """Imprime el desglose comparativo año por año (10 años) para cada fin de semana largo agregando lluvia y viento."""
    sep = "=" * 138
    subsep = "-" * 138
    
    print("\n" + sep)
    print("  2. COMPARATIVA HISTÓRICA COMPLETA DE 10 AÑOS POR DESTINO")
    print(sep)
    
    destinos = resultado["destinos"]
    if destino_filtro:
        destinos = [d for d in destinos if destino_filtro.lower() in d["nombre"].lower()]
        
    for d in destinos:
        print(f"\n📍 DESTINO: {d['nombre']} ({d['departamento']}) - Coordenadas: [{d['latitud']:.4f}, {d['longitud']:.4f}]")
        print(subsep)
        print(f"{'Año':<6} | {'Findes':<7} | {'Período / Motivo Principal':<42} | {'T. Máx':<9} | {'T. Mín':<9} | {'Lluvia':<10} | {'Viento Máx':<11}")
        print(subsep)
        
        for anio_str in sorted(d["clima_por_año"].keys(), reverse=True):
            info_a = d["clima_por_año"][anio_str]
            total_f = info_a["total_findes"]
            findes = info_a["findes"]
            
            if not findes:
                print(f"{anio_str:<6} | {total_f:<7} | Sin datos climáticos para este año                          | -         | -         | -        | -")
                continue
                
            for f in findes:
                periodo = f"{f['inicio']} al {f['fin']} ({f['feriados']})"
                if len(periodo) > 40:
                    periodo = periodo[:37] + "..."
                t_max = f"{f['temp_max_promedio']:.1f}°C" if f['temp_max_promedio'] is not None else "-"
                t_min = f"{f['temp_min_promedio']:.1f}°C" if f['temp_min_promedio'] is not None else "-"
                lluvia = f"{f['precipitacion_total_mm']:.1f}mm"
                viento = f"{f['viento_max_promedio_kmh']:.1f}km/h" if f.get("viento_max_promedio_kmh") is not None else "-"
                
                marca_actual = " 👈 (Año Actual)" if anio_str == str(resultado["anio_actual"]) else ""
                print(f"{anio_str:<6} | {total_f:<7} | {periodo:<42} | {t_max:<9} | {t_min:<9} | {lluvia:<10} | {viento:<11}{marca_actual}")
        print(subsep)


def imprimir_estadisticas_y_destacados(resultado: dict, tiempo_ejecucion: float):
    """Muestra información del estado del sistema de caché por capas y tiempo de ejecución."""
    sep = "=" * 138
    
    print("\n" + sep)
    print("  3. ESTADO DEL SISTEMA DE CACHÉ POR CAPAS Y RENDIMIENTO")
    print(sep)
    
    origenes = resultado.get("origenes_datos", {})
    print(f"  ⚡ Rendimiento de ejecución: {tiempo_ejecucion:.2f} segundos")
    print(f"  📁 Arquitectura de Caché por Capas:")
    print(f"     • Datos leídos desde Caché local (Disco): {origenes.get('Caché Disco', 0)} registros")
    print(f"     • Consultas realizadas a APIs de Red:      {origenes.get('Open-Meteo API', 0)} registros")
    print(f"  💾 Archivo derivado consolidado: '{ARCHIVO_DERIVADO_CLIMA_10A}'")
    print(sep + "\n")


# ==============================================================================
# ORQUESTADOR PRINCIPAL
# ==============================================================================
async def ejecutar_programa_async(forzar_recarga: bool = False) -> dict:
    """Orquesta la recolección e integración de las 3 APIs en paralelo, optimizando con caché consolidado."""
    anio_actual = datetime.date.today().year
    
    # 1. Coordenadas (Nominatim OSM)
    destinos = obtener_coordenadas_destinos(forzar_recarga=forzar_recarga)
    
    # 2. Fines de Semana Largos (Nager.Date 10 Años)
    paquete_findes = await obtener_findes_largos_10anios_async(anio_actual, forzar_recarga=forzar_recarga)
    
    # 3. Clima Histórico (Open-Meteo Archive 10 Años)
    anios = paquete_findes["anios_consultados"]

    derivado_clima = None
    if not forzar_recarga and ARCHIVO_DERIVADO_CLIMA_10A.exists():
        try:
            derivado_clima = json.loads(ARCHIVO_DERIVADO_CLIMA_10A.read_text(encoding="utf-8"))
            destinos_guardados = {d["nombre"].lower(): d for d in derivado_clima.get("destinos", [])}
            nombres_pedidos = [d["nombre"].lower() for d in destinos]
            anios_guardados = set(str(a) for a in derivado_clima.get("anios_consultados", []))
            anios_pedidos = {str(a) for a in anios}

            if all(nom in destinos_guardados for nom in nombres_pedidos) and anios_pedidos.issubset(anios_guardados):
                print(f"✅ [CACHÉ CONSOLIDADO] Clima histórico para {len(destinos)} destinos y 10 años recuperado instantáneamente desde '{ARCHIVO_DERIVADO_CLIMA_10A.name}'.")
                destinos_filtrados = [destinos_guardados[nom] for nom in nombres_pedidos]
                return {
                    "anio_actual": anio_actual,
                    "anios_consultados": anios,
                    "total_destinos": len(destinos_filtrados),
                    "fecha_generacion": derivado_clima.get("fecha_generacion", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                    "origenes_datos": derivado_clima.get("origenes_datos", {"Caché Disco": len(destinos) * len(anios)}),
                    "destinos": destinos_filtrados
                }
        except Exception:
            derivado_clima = None

    # Descarga de clima para los destinos y años
    descargas_clima = await recolectar_clima_10anios_async(destinos, anios, forzar_recarga=forzar_recarga)
    
    # 4. Procesamiento e integración final
    resultado = procesar_estadisticas_clima_10anios(destinos, paquete_findes, descargas_clima)

    # Actualizar consolidado si ya existían otros destinos previamente
    if derivado_clima and "destinos" in derivado_clima:
        mapa_destinos = {d["nombre"].lower(): d for d in derivado_clima["destinos"]}
        for d in resultado["destinos"]:
            mapa_destinos[d["nombre"].lower()] = d
        lista_completa = list(mapa_destinos.values())
        paquete_actualizado = dict(resultado)
        paquete_actualizado["total_destinos"] = len(lista_completa)
        paquete_actualizado["destinos"] = lista_completa
        try:
            ARCHIVO_DERIVADO_CLIMA_10A.write_text(json.dumps(paquete_actualizado, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    return resultado


def main():
    parser = argparse.ArgumentParser(
        description="Programa unificado para buscar y comparar el clima en destinos turísticos uruguayos durante fines de semana largos (10 Años)."
    )
    parser.add_argument(
        "--recargar",
        action="store_true",
        help="Ignorar el caché local y forzar la recarga desde las APIs públicas"
    )
    parser.add_argument(
        "--destino",
        type=str,
        default=None,
        help="Filtrar por un destino específico al mostrar los reportes (ej: --destino 'Montevideo')"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Imprimir los resultados consolidados en formato JSON estructurado"
    )
    parser.add_argument(
        "-o", "--output",
        type=str,
        default=None,
        help="Ruta de archivo opcional para guardar una copia del resultado JSON"
    )

    args = parser.parse_args()

    t0 = time.perf_counter()
    resultado = asyncio.run(ejecutar_programa_async(forzar_recarga=args.recargar))
    tiempo_total = time.perf_counter() - t0

    if args.json:
        print(json.dumps(resultado, ensure_ascii=False, indent=2))
    else:
        imprimir_encabezado(resultado["anio_actual"], resultado["total_destinos"], resultado["anios_consultados"])
        imprimir_tabla_resumen_año_actual(resultado, args.destino)
        imprimir_comparativa_historica(resultado, args.destino)
        imprimir_estadisticas_y_destacados(resultado, tiempo_total)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[INFO] Copia del resultado JSON guardada exitosamente en '{out_path}'")


if __name__ == "__main__":
    main()
