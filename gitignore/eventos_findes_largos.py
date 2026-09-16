#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Programa: Eventos Culturales en Fines de Semana Largos (Sistema UruguayAPI + Setlist.fm)
Descripción: Recolecta la cartelera de espectáculos y eventos de Uruguay combinando:
             1. UruguayAPI (uruguayapi.onrender.com): Antel Arena, Teatro Solís, 
                Tickantel, RedTickets y Cartelera de Cine (Eventos vigentes y futuros).
             2. Setlist.fm API (api.setlist.fm): Archivo histórico de recitales,
                festivales y conciertos pasados en Uruguay.
             Los cruza automáticamente con los fines de semana largos del año (fines_de_semana_largos.py).

Arquitectura de Caché por Capas:
  1. Crudo: 
     - 'datos/crudo/uruguay_api/' (5 archivos JSON: antel_arena, teatro_solis, tickantel, redtickets, billboard)
     - 'datos/crudo/setlist_fm/' (setlists_UY_{anio}.json)
  2. Parseo y deduplicación: Extrae fechas, normaliza títulos y cruza con los findes largos.
  3. Derivado: 'datos/derivado/eventos_findes_largos_{anio}.json' consolidado.
"""

import sys
import os
import re
import json
import time
import argparse
import datetime
import importlib
import socket
from pathlib import Path
import requests

# Forzar resolución IPv4 en Windows para evitar ConnectionResetError con CloudFront / Setlist.fm
try:
    _orig_getaddrinfo = socket.getaddrinfo
    def _getaddrinfo_ipv4(host, port, family=0, type=0, proto=0, flags=0):
        return _orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
    socket.getaddrinfo = _getaddrinfo_ipv4
except Exception:
    pass

# Asegurar compatibilidad con Windows en UTF-8
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

# ==============================================================================
# CONFIGURACIÓN PRINCIPAL DE APIS
# ==============================================================================
# 1. UruguayAPI: No requiere clave (siempre activa).
URUGUAY_API_URL = "https://uruguayapi.onrender.com/api/v1/events"

# 2. Setlist.fm API: Para recitales y conciertos pasados en Uruguay.
#    Obtener gratis en: https://www.setlist.fm/settings/api
SETLIST_FM_API_KEY = "IZzlLOXJM1ljglddsFMmbjPRgoTotLBV26US"

AÑO_ACTUAL = datetime.date.today().year

# Importar módulo local fines_de_semana_largos
try:
    from otros import fines_de_semana_largos as mod_findes
except ImportError:
    try:
        mod_findes = importlib.import_module("fines_de_semana_largos")
    except ImportError:
        mod_findes = None

# Definición de directorios de capas
if Path("datos").exists() or Path("otros").exists():
    DIR_BASE_DATOS = Path("datos")
else:
    DIR_BASE_DATOS = Path(__file__).resolve().parent.parent / "datos"

DIR_CRUDO_URUGUAY = DIR_BASE_DATOS / "crudo" / "uruguay_api"
DIR_CRUDO_SETLIST = DIR_BASE_DATOS / "crudo" / "setlist_fm"
DIR_DERIVADO = DIR_BASE_DATOS / "derivado"

# Configuración de endpoints de UruguayAPI
URUGUAY_API_FUENTES = [
    {
        "id": "antel_arena",
        "nombre": "Antel Arena",
        "url": f"{URUGUAY_API_URL}/antel_arena",
        "archivo_crudo": "antel_arena.json"
    },
    {
        "id": "teatro_solis",
        "nombre": "Teatro Solís",
        "url": f"{URUGUAY_API_URL}/teatro_solis",
        "archivo_crudo": "teatro_solis.json"
    },
    {
        "id": "tickantel",
        "nombre": "Tickantel",
        "url": f"{URUGUAY_API_URL}/tickantel",
        "archivo_crudo": "tickantel.json"
    },
    {
        "id": "redtickets",
        "nombre": "RedTickets",
        "url": f"{URUGUAY_API_URL}/redtickets?period=monthly",
        "archivo_crudo": "redtickets.json"
    },
    {
        "id": "billboard",
        "nombre": "Cartelera (Billboard)",
        "url": f"{URUGUAY_API_URL}/billboard",
        "archivo_crudo": "billboard.json"
    }
]

MESES_ES = {
    "ene": 1, "enero": 1,
    "feb": 2, "febrero": 2,
    "mar": 3, "marzo": 3,
    "abr": 4, "abril": 4,
    "may": 5, "mayo": 5,
    "jun": 6, "junio": 6,
    "jul": 7, "julio": 7,
    "ago": 8, "agosto": 8,
    "set": 9, "sept": 9, "setiembre": 9, "septiembre": 9,
    "oct": 10, "octubre": 10,
    "nov": 11, "noviembre": 11,
    "dic": 12, "diciembre": 12
}


# ==============================================================================
# 1. PARSER ROBUSTO DE FECHAS
# ==============================================================================
def extraer_fechas_de_evento(evento: dict, año_por_defecto: int) -> list[datetime.date]:
    """
    Analiza todos los campos de un evento y extrae una lista de fechas (datetime.date).
    """
    fechas_encontradas = set()

    # 1. Fechas ISO directas (YYYY-MM-DD)
    campos_iso = [evento.get("start_date"), evento.get("end_date"), evento.get("next_function"), evento.get("start")]
    for val in campos_iso:
        if isinstance(val, str) and len(val) >= 10:
            match_iso = re.search(r"(\d{4})-(\d{2})-(\d{2})", val)
            if match_iso:
                try:
                    fechas_encontradas.add(datetime.date(int(match_iso.group(1)), int(match_iso.group(2)), int(match_iso.group(3))))
                except ValueError:
                    pass

    if evento.get("start_date") and evento.get("end_date"):
        try:
            d_ini = datetime.date.fromisoformat(str(evento["start_date"])[:10])
            d_fin = datetime.date.fromisoformat(str(evento["end_date"])[:10])
            if d_ini <= d_fin and (d_fin - d_ini).days <= 10:
                cur = d_ini
                while cur <= d_fin:
                    fechas_encontradas.add(cur)
                    cur += datetime.timedelta(days=1)
        except Exception:
            pass

    # 2. Formato Setlist.fm (DD-MM-YYYY)
    if "eventDate" in evento and isinstance(evento["eventDate"], str):
        match_ddmmyyyy = re.search(r"(\d{2})-(\d{2})-(\d{4})", evento["eventDate"])
        if match_ddmmyyyy:
            try:
                fechas_encontradas.add(datetime.date(int(match_ddmmyyyy.group(3)), int(match_ddmmyyyy.group(2)), int(match_ddmmyyyy.group(1))))
            except ValueError:
                pass

    # 3. Formato texto en español
    texto_fecha = str(evento.get("date", "")).lower().strip()
    if texto_fecha and texto_fecha != "none":
        # Formato rango entre meses: "del 08 sept 2026 al 12 sept 2026"
        match_rango = re.search(r"del\s+(\d{1,2})\s+([a-z]+)(?:\s+(\d{4}))?\s+al\s+(\d{1,2})\s+([a-z]+)\s+(\d{4})?", texto_fecha)
        if match_rango:
            dia1, mes1_str, a1, dia2, mes2_str, a2 = match_rango.groups()
            m1 = MESES_ES.get(mes1_str[:4], MESES_ES.get(mes1_str[:3]))
            m2 = MESES_ES.get(mes2_str[:4], MESES_ES.get(mes2_str[:3]))
            anio = int(a2 or a1 or año_por_defecto)
            if m1 and m2:
                try:
                    f1 = datetime.date(anio, m1, int(dia1))
                    f2 = datetime.date(anio, m2, int(dia2))
                    if f1 <= f2 and (f2 - f1).days <= 15:
                        cur = f1
                        while cur <= f2:
                            fechas_encontradas.add(cur)
                            cur += datetime.timedelta(days=1)
                except ValueError:
                    pass

        # Extraer año explícito de 4 dígitos (ej. 2026) y removerlo del texto para no confundir días
        match_anio = re.search(r"\b(20\d{2})\b", texto_fecha)
        if match_anio:
            anio_evento = int(match_anio.group(1))
            texto_fecha = texto_fecha[:match_anio.start()] + " " + texto_fecha[match_anio.end():]
        else:
            anio_evento = año_por_defecto

        # Remover horarios (ej. "18:30h", "18:30", "20h")
        texto_fecha = re.sub(r"\b\d{1,2}:\d{2}(?:h)?\b", " ", texto_fecha)
        texto_fecha = re.sub(r"\b\d{1,2}h\b", " ", texto_fecha)

        # Buscar el nombre del mes
        mes_encontrado = None
        for palabra in re.split(r"[\s,]+", texto_fecha):
            p_limpia = re.sub(r"[^a-z]", "", palabra)
            if p_limpia in MESES_ES:
                mes_encontrado = MESES_ES[p_limpia]
                break
            elif p_limpia[:4] in MESES_ES:
                mes_encontrado = MESES_ES[p_limpia[:4]]
                break
            elif p_limpia[:3] in MESES_ES:
                mes_encontrado = MESES_ES[p_limpia[:3]]
                break

        if mes_encontrado:
            # Rango en el mismo mes: "18 – 20 de set", "18 al 20 de set"
            match_rango_mes = re.search(r"(\d{1,2})\s*(?:al|–|-|a)\s*(\d{1,2})", texto_fecha)
            if match_rango_mes:
                d1, d2 = int(match_rango_mes.group(1)), int(match_rango_mes.group(2))
                if 1 <= d1 <= 31 and 1 <= d2 <= 31 and d1 <= d2 and (d2 - d1) <= 15:
                    for d in range(d1, d2 + 1):
                        fechas_encontradas.add(datetime.date(anio_evento, mes_encontrado, d))

            # Días individuales o lista: "8, 10 y 12 de setiembre"
            match_multi = re.findall(r"\b(\d{1,2})\b", texto_fecha)
            for d_str in match_multi:
                dia_num = int(d_str)
                if 1 <= dia_num <= 31:
                    try:
                        fechas_encontradas.add(datetime.date(anio_evento, mes_encontrado, dia_num))
                    except ValueError:
                        pass

    return sorted(list(fechas_encontradas))


# ==============================================================================
# 2. CAPA CRUDO: URUGUAYAPI (ONRENDER)
# ==============================================================================
def recolectar_uruguay_api(forzar_recarga: bool = False) -> list[dict]:
    """Recolecta y almacena los 5 JSONs crudos de UruguayAPI."""
    DIR_CRUDO_URUGUAY.mkdir(parents=True, exist_ok=True)
    eventos_consolidados = []

    print("\n[Fuente 1/2: UruguayAPI (Carteleras en Vivo y Próximas)]")
    for f_cfg in URUGUAY_API_FUENTES:
        ruta_archivo = DIR_CRUDO_URUGUAY / f_cfg["archivo_crudo"]
        datos = None

        if not forzar_recarga and ruta_archivo.exists():
            try:
                with open(ruta_archivo, "r", encoding="utf-8") as f:
                    datos = json.load(f)
                    print(f"  [CACHÉ DISCO] '{f_cfg['nombre']}' recuperado de '{ruta_archivo.name}'.")
            except Exception:
                pass

        if datos is None:
            print(f"  [RED WEB] Consultando '{f_cfg['nombre']}'...")
            try:
                resp = requests.get(f_cfg["url"], timeout=30)
                resp.raise_for_status()
                datos = resp.json()
                with open(ruta_archivo, "w", encoding="utf-8") as f:
                    json.dump(datos, f, ensure_ascii=False, indent=2)
                print(f"  [GUARDADO] Crudo guardado en '{ruta_archivo}'.")
            except Exception as e:
                print(f"  [ALERTA] Falló '{f_cfg['nombre']}': {e}", file=sys.stderr)
                datos = []

        # Normalizar elementos
        items = []
        if isinstance(datos, list):
            items = datos
        elif isinstance(datos, dict):
            for k, sub in datos.items():
                if isinstance(sub, list):
                    items.extend(sub)

        for it in items:
            if isinstance(it, dict) and (it.get("title") or it.get("name")):
                fechas = extraer_fechas_de_evento(it, AÑO_ACTUAL)
                if fechas:
                    eventos_consolidados.append({
                        "fuente": f_cfg["nombre"],
                        "tipo_fuente": "cartelera_programada",
                        "titulo": it.get("title") or it.get("name"),
                        "lugar": it.get("venue") or f_cfg["nombre"],
                        "fechas": [f.strftime("%Y-%m-%d") for f in fechas],
                        "hora": it.get("time") or it.get("doors_open"),
                        "precio": it.get("price") or (f"${it.get('price_low')} - ${it.get('price_high')}" if it.get("price_low") else None),
                        "enlace": it.get("event_link") or it.get("buy_tickets") or it.get("source_url"),
                        "descripcion": (it.get("description") or "")[:200]
                    })
        time.sleep(0.2)

    return eventos_consolidados


# ==============================================================================
# 3. CAPA CRUDO: SETLIST.FM API (HISTÓRICO DE RECITALES)
# ==============================================================================
def recolectar_setlist_fm(api_key: str, anio: int, forzar_recarga: bool = False) -> list[dict]:
    """Consulta Setlist.fm para obtener recitales pasados en Uruguay en el año."""
    if not api_key:
        print("\n[Fuente 2/2: Setlist.fm API (Histórico de Recitales)]")
        print("  ℹ️ No se especificó API Key de Setlist.fm. Omitiendo recitales históricos.")
        print("     (Puedes obtener una gratis en https://www.setlist.fm/settings/api e ingresarla al inicio del script)")
        return []

    DIR_CRUDO_SETLIST.mkdir(parents=True, exist_ok=True)
    ruta_archivo = DIR_CRUDO_SETLIST / f"setlists_UY_{anio}.json"
    datos = None

    print(f"\n[Fuente 2/2: Setlist.fm API (Histórico de Recitales en Uruguay - Año {anio})]")
    if not forzar_recarga and ruta_archivo.exists():
        try:
            with open(ruta_archivo, "r", encoding="utf-8") as f:
                datos = json.load(f)
                print(f"  [CACHÉ DISCO] Setlist.fm recuperado de '{ruta_archivo.name}'.")
        except Exception:
            pass

    if datos is None:
        print(f"  [RED WEB] Consultando Setlist.fm API para Uruguay (año {anio})...")
        url = "https://api.setlist.fm/rest/1.0/search/setlists"
        headers = {
            "x-api-key": api_key,
            "Accept": "application/json"
        }
        
        # Paginación para recolectar los recitales del año (hasta 10 páginas = 200 conciertos)
        todos_setlists = []
        try:
            for p in range(1, 11):
                params = {
                    "countryCode": "UY",
                    "year": str(anio),
                    "p": str(p)
                }
                resp = requests.get(url, headers=headers, params=params, timeout=20)
                if resp.status_code == 200:
                    data_page = resp.json()
                    items_page = data_page.get("setlist", [])
                    if not items_page:
                        break
                    todos_setlists.extend(items_page)
                    total_disponibles = data_page.get("total", len(todos_setlists))
                    if len(todos_setlists) >= total_disponibles:
                        break
                    time.sleep(1.1)  # Respetar rate limit de Setlist.fm (máx 1 req/seg)
                else:
                    break
            
            datos = {"setlist": todos_setlists, "total": len(todos_setlists)}
            with open(ruta_archivo, "w", encoding="utf-8") as f:
                json.dump(datos, f, ensure_ascii=False, indent=2)
            print(f"  [GUARDADO] {len(todos_setlists)} recitales históricos guardados en '{ruta_archivo}'.")
        except Exception as e:
            print(f"  [ALERTA] Falló Setlist.fm API: {e}", file=sys.stderr)
            return []

    eventos = []
    lista_setlists = datos.get("setlist", []) if isinstance(datos, dict) else []
    for s in lista_setlists:
        fechas = extraer_fechas_de_evento(s, anio)
        if fechas:
            artista = s.get("artist", {}).get("name", "Artista")
            venue_info = s.get("venue", {})
            sala = venue_info.get("name", "Sala")
            ciudad = venue_info.get("city", {}).get("name", "Uruguay")
            eventos.append({
                "fuente": "Setlist.fm",
                "tipo_fuente": "historico_pasado",
                "titulo": f"Concierto: {artista}",
                "lugar": f"{sala}, {ciudad}",
                "fechas": [f.strftime("%Y-%m-%d") for f in fechas],
                "hora": None,
                "precio": "Histórico / Concierto pasado",
                "enlace": s.get("url"),
                "descripcion": f"Gira/Tour: {s.get('tour', {}).get('name', 'N/D')}"
            })

    print(f"  Total de recitales históricos obtenidos de Setlist.fm: {len(eventos)}")
    return eventos


# ==============================================================================
# 4. CRUCE Y CONSOLIDACIÓN DERIVADA
# ==============================================================================
def obtener_fines_de_semana_del_año(anio: int, forzar_recarga: bool = False) -> list[dict]:
    """Obtiene los fines de semana largos oficiales desde fines_de_semana_largos.py."""
    if mod_findes:
        try:
            findes_todos, _, _ = mod_findes.procesar_fines_de_semana(
                anio=anio,
                pais="UY",
                incluir_puentes=True,
                forzar_recarga=forzar_recarga
            )
            return findes_todos
        except Exception as e:
            print(f"[ALERTA] Error al invocar fines_de_semana_largos: {e}", file=sys.stderr)
    return []


def procesar_sistema_hibrido(anio: int, setlist_key: str, forzar_recarga: bool = False) -> dict:
    """Coordina UruguayAPI y Setlist.fm, deduplica eventos y genera la capa derivada."""
    hoy = datetime.date.today()
    print("\n" + "=" * 85)
    print(f"  SISTEMA DE EVENTOS EN FINES DE SEMANA LARGOS - URUGUAY {anio}")
    print(f"  Fecha de referencia hoy: {hoy}")
    print("=" * 85)

    # 1. Obtener fines de semana largos
    findes_crudos = obtener_fines_de_semana_del_año(anio, forzar_recarga=forzar_recarga)

    # 2. Recolectar de las APIs (UruguayAPI + Setlist.fm)
    evs_uruguay = recolectar_uruguay_api(forzar_recarga=forzar_recarga)
    evs_setlist = recolectar_setlist_fm(setlist_key, anio, forzar_recarga=forzar_recarga)

    todos_los_eventos = evs_uruguay + evs_setlist

    # 3. Deduplicación por (clave fecha + título normalizado)
    eventos_unicos = []
    vistos = set()
    for ev in todos_los_eventos:
        t_clean = re.sub(r"[^\w]", "", ev["titulo"].lower())
        clave = (tuple(ev["fechas"]), t_clean[:20])
        if clave not in vistos:
            vistos.add(clave)
            eventos_unicos.append(ev)

    print(f"\n[Procesando Cruce] Total de eventos únicos procesados: {len(eventos_unicos)}")

    # 4. Clasificación por Fin de Semana Largo
    findes_estructurados = []
    for idx, fl in enumerate(findes_crudos):
        inicio = datetime.date.fromisoformat(fl["inicio"])
        fin = datetime.date.fromisoformat(fl["fin"])

        if fin < hoy:
            estado = "pasado"
        elif inicio <= hoy <= fin:
            estado = "en_curso"
        else:
            estado = "programado"

        coincidentes = []
        for ev in eventos_unicos:
            for f_str in ev["fechas"]:
                f_ev = datetime.date.fromisoformat(f_str)
                if inicio <= f_ev <= fin:
                    coincidentes.append(ev)
                    break

        findes_estructurados.append({
            "id": idx + 1,
            "nombre": ", ".join(fl.get("nombres_feriados", [])) or f"Fin de semana largo #{idx + 1}",
            "inicio": fl["inicio"],
            "fin": fl["fin"],
            "inicio_formateado": fl.get("inicio_formateado", str(inicio)),
            "fin_formateado": fl.get("fin_formateado", str(fin)),
            "duracion_dias": fl.get("duracion_dias", (fin - inicio).days + 1),
            "es_puente": fl.get("es_puente", False),
            "estado": estado,
            "feriados": fl.get("nombres_feriados", []),
            "total_eventos": len(coincidentes),
            "eventos": coincidentes
        })

    # 5. Guardar capa derivada
    DIR_DERIVADO.mkdir(parents=True, exist_ok=True)
    archivo_derivado = DIR_DERIVADO / f"eventos_findes_largos_{anio}.json"

    documento_derivado = {
        "metadata": {
            "anio": anio,
            "fecha_recoleccion": datetime.datetime.now().isoformat(),
            "total_findes_largos": len(findes_estructurados),
            "total_eventos_encontrados": sum(f["total_eventos"] for f in findes_estructurados),
            "fuentes": {
                "uruguay_api": [f["nombre"] for f in URUGUAY_API_FUENTES],
                "setlist_fm": bool(setlist_key)
            }
        },
        "fines_de_semana_largos": findes_estructurados
    }

    with open(archivo_derivado, "w", encoding="utf-8") as f:
        json.dump(documento_derivado, f, ensure_ascii=False, indent=2)

    print(f"\n✅ [CONSOLIDADO DERIVADO] Guardado exitosamente en '{archivo_derivado}'.")
    return documento_derivado


# ==============================================================================
# 5. VISUALIZACIÓN EN TERMINAL
# ==============================================================================
def mostrar_reporte_eventos(datos_derivados: dict):
    """Muestra el reporte cronológico completo con eventos pasados y programados."""
    findes = datos_derivados.get("fines_de_semana_largos", [])
    anio = datos_derivados.get("metadata", {}).get("anio")

    print("\n" + "=" * 90)
    print(f"🎭 EVENTOS CULTURALES EN FINES DE SEMANA LARGOS - URUGUAY {anio}")
    print("=" * 90)

    iconos_estado = {
        "pasado": "⏪ [PASADO]",
        "en_curso": "🔴 [EN CURSO HOY]",
        "programado": "📅 [PROGRAMADO / PRÓXIMO]"
    }

    for f in findes:
        tag = iconos_estado.get(f["estado"], f"[{f['estado'].upper()}]")
        print(f"\n{tag} {f['nombre']} ({f['inicio']} al {f['fin']} - {f['duracion_dias']} días)")
        print("-" * 90)

        if f["total_eventos"] == 0:
            print("   (No hay eventos registrados para este fin de semana largo)")
        else:
            for ev in f["eventos"]:
                fechas_txt = ", ".join(ev["fechas"])
                precio_txt = f" | {ev['precio']}" if ev.get("precio") else ""
                print(f"   • [{ev['fuente']}] {ev['titulo']}")
                print(f"     Lugar: {ev['lugar']} | Fechas: {fechas_txt}{precio_txt}")
                if ev.get("enlace"):
                    print(f"     Info/Entradas: {ev['enlace']}")

    print("\n" + "=" * 90 + "\n")


# ==============================================================================
# 6. PUNTO DE ENTRADA CLI
# ==============================================================================
def main():
    parser = argparse.ArgumentParser(
        description="Sistema híbrido: cruza eventos de UruguayAPI y Setlist.fm con findes largos."
    )
    parser.add_argument("--anio", type=int, default=AÑO_ACTUAL, help=f"Año a analizar (por defecto {AÑO_ACTUAL}).")
    parser.add_argument("--setlist-key", type=str, default=SETLIST_FM_API_KEY, help="API Key de Setlist.fm.")
    parser.add_argument("--forzar-recarga", action="store_true", help="Ignora la caché en disco y vuelve a consultar las APIs.")

    args = parser.parse_args()

    setlist_key = args.setlist_key or os.environ.get("SETLIST_FM_API_KEY", "").strip()

    datos = procesar_sistema_hibrido(
        anio=args.anio,
        setlist_key=setlist_key,
        forzar_recarga=args.forzar_recarga
    )
    mostrar_reporte_eventos(datos)


if __name__ == "__main__":
    main()
