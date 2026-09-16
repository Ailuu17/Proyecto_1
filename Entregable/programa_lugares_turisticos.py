#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Programa: Lugares Turísticos por Sitio (SerpApi - Google Maps)
Descripción: Utiliza SerpApi (Google Maps Engine) para buscar, catalogar y analizar
             los lugares y atracciones turísticas en los destinos de 'Lugares turísticos.txt'.
"""

import sys
import os
import re
import json
import time
import shutil
import unicodedata
import argparse
import datetime
from pathlib import Path
import requests

# Asegurar compatibilidad UTF-8 en terminal de Windows
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

SERPAPI_URL = "https://serpapi.com/search.json"

# Directorios de datos (relativos a Entregable)
BASE_DIR = Path(__file__).resolve().parent
DIR_CRUDO_LUGARES = BASE_DIR / "datos" / "crudo" / "serpapi_lugares"
DIR_DERIVADO = BASE_DIR / "datos" / "derivado"
DIR_FALLBACK_CRUDO = BASE_DIR.parent / "datos" / "crudo" / "serpapi_lugares"

ARCHIVO_TXT_DESTINOS = BASE_DIR / "Lugares turísticos.txt"
ARCHIVO_DERIVADO = DIR_DERIVADO / "lugares_turisticos_por_sitio.json"

# Base de conocimiento curada de lugares icónicos en Uruguay
DICCIONARIO_ICONICOS = {
    "jardín botánico": {"tipo_tarifa": "Gratuito", "detalle": "Entrada libre y gratuita (Intendencia)", "categoria": "Parques y Jardines Botánicos"},
    "jardin botanico": {"tipo_tarifa": "Gratuito", "detalle": "Entrada libre y gratuita (Intendencia)", "categoria": "Parques y Jardines Botánicos"},
    "parque rodó": {"tipo_tarifa": "De Pago", "detalle": "Parque público libre, pero juegos mecánicos con fichas", "categoria": "Parques de Diversiones y Juegos Familiares"},
    "parque rodo": {"tipo_tarifa": "De Pago", "detalle": "Parque público libre, pero juegos mecánicos con fichas", "categoria": "Parques de Diversiones y Juegos Familiares"},
    "parque lecocq": {"tipo_tarifa": "De Pago", "detalle": "Bono de ingreso por vehículo o entrada general", "categoria": "Bioparques, Termas y Naturaleza"},
    "bioparque durazno": {"tipo_tarifa": "Gratuito", "detalle": "Acceso libre y gratuito (Bioparque Washington Rodríguez)", "categoria": "Bioparques, Termas y Naturaleza"},
    "planetario de montevideo": {"tipo_tarifa": "Gratuito", "detalle": "Funciones gratuitas con reserva previa online", "categoria": "Museos, Ciencia y Planetarios"},
    "espacio ciencia": {"tipo_tarifa": "De Pago", "detalle": "Museo interactivo de ciencia con costo de entrada (LATU)", "categoria": "Museos, Ciencia y Planetarios"},
    "parque pan de azúcar": {"tipo_tarifa": "Gratuito", "detalle": "Estación de cría de fauna autóctona ECFA (acceso gratuito)", "categoria": "Bioparques, Termas y Naturaleza"},
    "parque el jagüel": {"tipo_tarifa": "Gratuito", "detalle": "Punta del Este: juegos infantiles de madera de acceso gratuito", "categoria": "Parques de Diversiones y Juegos Familiares"},
    "casapueblo": {"tipo_tarifa": "De Pago", "detalle": "Museo Taller Casapueblo con costo de entrada general", "categoria": "Museos, Ciencia y Planetarios"},
    "termas de guaviyú": {"tipo_tarifa": "De Pago", "detalle": "Complejo termal con cobro de entrada / acceso diario", "categoria": "Bioparques, Termas y Naturaleza"},
    "termas del daymán": {"tipo_tarifa": "De Pago", "detalle": "Complejo termal municipal con entrada general", "categoria": "Bioparques, Termas y Naturaleza"},
    "faro de cabo polonio": {"tipo_tarifa": "De Pago", "detalle": "Ascenso al faro con entrada/bono colaboración", "categoria": "Miradores, Faros y Paseos Históricos"},
    "faro de colonia": {"tipo_tarifa": "De Pago", "detalle": "Ascenso al faro con ticket de entrada", "categoria": "Miradores, Faros y Paseos Históricos"},
    "faro de la paloma": {"tipo_tarifa": "De Pago", "detalle": "Ascenso al faro con ticket de entrada", "categoria": "Miradores, Faros y Paseos Históricos"},
    "fortaleza de santa teresa": {"tipo_tarifa": "De Pago", "detalle": "Parque nacional libre, museo de la fortaleza con entrada", "categoria": "Miradores, Faros y Paseos Históricos"},
    "parque santa teresa": {"tipo_tarifa": "Gratuito", "detalle": "Parque Nacional y playas de libre acceso público", "categoria": "Parques y Jardines Botánicos"},
    "cerro del toro": {"tipo_tarifa": "Gratuito", "detalle": "Paseo natural y mirador de acceso libre (Piriápolis)", "categoria": "Miradores, Faros y Paseos Históricos"},
    "cerro san antonio": {"tipo_tarifa": "Gratuito", "detalle": "Mirador libre (telesilla mecánica opcional de pago)", "categoria": "Miradores, Faros y Paseos Históricos"},
    "puerto de punta del este": {"tipo_tarifa": "Gratuito", "detalle": "Paseo público costero y avistamiento de lobos marinos", "categoria": "Miradores, Faros y Paseos Históricos"},
    "museo blanes": {"tipo_tarifa": "Gratuito", "detalle": "Museo y Jardín Japonés de acceso libre y gratuito", "categoria": "Museos, Ciencia y Planetarios"},
    "barrio histórico de colonia": {"tipo_tarifa": "Gratuito", "detalle": "Paseo a cielo abierto por el casco antiguo de libre acceso", "categoria": "Miradores, Faros y Paseos Históricos"},
    "rambla de montevideo": {"tipo_tarifa": "Gratuito", "detalle": "Paseo costero peatonal público sin costo", "categoria": "Parques y Jardines Botánicos"}
}


def normalizar_slug(texto: str) -> str:
    """Convierte un texto a formato slug."""
    nfkd = unicodedata.normalize("NFKD", texto)
    solo_ascii = "".join([c for c in nfkd if not unicodedata.combining(c)])
    limpio = re.sub(r"[^\w\s-]", "", solo_ascii.lower()).strip()
    return re.sub(r"[-\s]+", "_", limpio)


def cargar_destinos_desde_txt() -> list:
    """
    Lee los destinos dinámicamente desde 'Lugares turísticos.txt'.
    Si no se encuentra o no se puede recuperar, ofrece ingresarlos por terminal
    en un bucle continuo hasta que el usuario ingrese 'False'.
    Retorna una lista de diccionarios [{'nombre': ..., 'departamento': ...}].
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
                    destinos.append({"nombre": nombre, "departamento": depto})
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
            destinos.append({"nombre": nombre, "departamento": depto})
            print(f"  -> Destino agregado: {nombre} ({depto})")

    return destinos


def consultar_serpapi_maps_sitio(sitio: dict, api_key: str, forzar_recarga: bool = False) -> list:
    """Consulta SerpApi Google Maps para un destino y gestiona la capa de caché."""
    DIR_CRUDO_LUGARES.mkdir(parents=True, exist_ok=True)
    slug = normalizar_slug(sitio["nombre"])
    nombre_archivo = f"lugares_{slug}.json"
    ruta_archivo = DIR_CRUDO_LUGARES / nombre_archivo
    ruta_fallback = DIR_FALLBACK_CRUDO / nombre_archivo

    datos = None

    if not forzar_recarga:
        if ruta_archivo.exists():
            try:
                datos = json.loads(ruta_archivo.read_text(encoding="utf-8"))
                print(f"  [CACHÉ DISCO] '{sitio['nombre']}' recuperado de '{nombre_archivo}'.")
            except Exception:
                pass
        elif ruta_fallback.exists():
            try:
                shutil.copy(ruta_fallback, ruta_archivo)
                datos = json.loads(ruta_archivo.read_text(encoding="utf-8"))
                print(f"  [CACHÉ DISCO] '{sitio['nombre']}' recuperado de archivo existente.")
            except Exception:
                pass

    if datos is None:
        if not api_key:
            raise RuntimeError(
                f"No hay caché para recuperar ni API Key para ingresar a SerpApi al consultar '{sitio['nombre']}'."
            )

        query = f"lugares turisticos atracciones para todas las edades {sitio['nombre']} Uruguay"
        print(f"  [RED WEB] Consultando SerpApi Maps para {sitio['nombre']}...")
        params = {
            "engine": "google_maps",
            "q": query,
            "hl": "es",
            "gl": "uy",
            "api_key": api_key
        }

        try:
            resp = requests.get(SERPAPI_URL, params=params, timeout=25)
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

            ruta_archivo.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  [GUARDADO] Crudo guardado en '{ruta_archivo.name}'.")

        except requests.exceptions.RequestException as e:
            raise RuntimeError(
                f"No hay caché para recuperar ni se pudo ingresar a SerpApi (o API Key errónea): {e}"
            )

    resultados_locales = datos.get("local_results", [])
    if isinstance(resultados_locales, list):
        return resultados_locales
    return []


def inferir_categoria_tematica(titulo: str, tipo_lugar: str, descripcion: str) -> str:
    """Clasifica el lugar en una categoría temática."""
    texto = f"{titulo.lower()} {tipo_lugar.lower()} {descripcion.lower()}"

    if any(k in texto for k in ["diversion", "diversiones", "juegos", "mecanicos", "médicos", "arcade", "karting", "calesita", "rueda gigante"]):
        return "Parques de Diversiones y Juegos Familiares"

    if any(k in texto for k in ["museo", "museum", "ciencia", "planetario", "galería", "taller", "casapueblo", "arte"]):
        return "Museos, Ciencia y Planetarios"

    if any(k in texto for k in ["bioparque", "reserva", "animal", "zoologico", "zoológico", "termas", "fauna", "ecoparque", "flora"]):
        return "Bioparques, Termas y Naturaleza"

    if any(k in texto for k in ["faro", "mirador", "cerro", "fortaleza", "historico", "histórico", "monumento", "puerto", "plaza de toros"]):
        return "Miradores, Faros y Paseos Históricos"

    if any(k in texto for k in ["jardin", "jardín", "botanico", "botánico", "parque", "park", "rambla", "plaza", "playa", "bosque"]):
        return "Parques y Jardines Botánicos"

    return "Paseos y Atracciones Generales"


def clasificar_lugar(lugar: dict, sitio_info: dict) -> dict:
    """Determina la categoría temática y si el lugar es Gratuito o De Pago."""
    titulo = (lugar.get("title") or "").strip()
    titulo_low = titulo.lower()
    descripcion = (lugar.get("description") or "").lower()
    tipo_lugar = (lugar.get("type") or "").lower()
    precio_raw = str(lugar.get("price", "")).strip()

    for clave_iconica, info_iconica in DICCIONARIO_ICONICOS.items():
        if clave_iconica in titulo_low:
            return {
                "categoria": info_iconica["categoria"],
                "tipo_tarifa": info_iconica["tipo_tarifa"],
                "detalle_tarifa": info_iconica["detalle"]
            }

    categoria = inferir_categoria_tematica(titulo, tipo_lugar, descripcion)

    if precio_raw in ["$", "$$", "$$$", "$$$$"]:
        return {"categoria": categoria, "tipo_tarifa": "De Pago", "detalle_tarifa": f"Indicador de precio en Google Maps: {precio_raw}"}
    if precio_raw.lower() in ["gratis", "$0", "free"]:
        return {"categoria": categoria, "tipo_tarifa": "Gratuito", "detalle_tarifa": "Registrado como gratuito en Google Maps"}

    texto_completo = f"{titulo_low} {descripcion} {tipo_lugar}"
    palabras_gratis = ["gratis", "gratuito", "gratuita", "entrada libre", "acceso libre", "sin costo", "sin cargo", "parque publico", "parque público"]
    for p in palabras_gratis:
        if p in texto_completo:
            return {"categoria": categoria, "tipo_tarifa": "Gratuito", "detalle_tarifa": f"Indicación de acceso libre ('{p}')"}

    palabras_pago = ["ticket", "entrada", "boletos", "boleto", "tarifa", "fichas", "costo", "adquiere tus", "pagar", "comprar entrada", "termas", "faro"]
    for p in palabras_pago:
        if p in texto_completo:
            return {"categoria": categoria, "tipo_tarifa": "De Pago", "detalle_tarifa": f"Mención de acceso comercial ('{p}')"}

    if categoria in ["Parques de Diversiones y Juegos Familiares"]:
        return {"categoria": categoria, "tipo_tarifa": "De Pago", "detalle_tarifa": "Atracciones sujetas a fichas/tarifa"}

    return {"categoria": categoria, "tipo_tarifa": "Gratuito", "detalle_tarifa": "Paseo público sin costo de entrada registrado"}


def procesar_lugares_por_sitio(destinos: list, api_key: str, forzar_recarga: bool = False) -> dict:
    """Procesa los destinos turísticos recolectando sus atracciones y métricas."""
    print("\n" + "=" * 95)
    print("  ANÁLISIS DE LUGARES TURÍSTICOS POR SITIO (SERPAPI - GOOGLE MAPS)")
    print(f"  Total de sitios a analizar: {len(destinos)} (extraídos dinámicamente de 'Lugares turísticos.txt')")
    print("=" * 95 + "\n")

    # Verificar si el archivo derivado ya contiene los destinos pedidos
    derivado_existente = None
    if not forzar_recarga and ARCHIVO_DERIVADO.exists():
        try:
            derivado_existente = json.loads(ARCHIVO_DERIVADO.read_text(encoding="utf-8"))
        except Exception:
            derivado_existente = None

    mapa_sitios_guardados = {}
    if derivado_existente and isinstance(derivado_existente, dict) and "destinos" in derivado_existente:
        for d in derivado_existente["destinos"]:
            mapa_sitios_guardados[d["sitio"].lower()] = d

    # Si todos los destinos solicitados ya están en el consolidado y no se fuerza recarga:
    nombres_pedidos = [d["nombre"].lower() for d in destinos]
    if derivado_existente and all(nom in mapa_sitios_guardados for nom in nombres_pedidos) and not forzar_recarga:
        print(f"✅ [CACHÉ CONSOLIDADO] Todos los destinos ({len(destinos)}) recuperados instantáneamente de '{ARCHIVO_DERIVADO.name}'.")
        destinos_filtrados = [mapa_sitios_guardados[nom] for nom in nombres_pedidos]
        return {
            "metadata": derivado_existente.get("metadata", {}),
            "destinos": destinos_filtrados
        }

    sitios_analizados = []
    total_lugares_pais = 0
    total_gratuitos_pais = 0
    total_de_pago_pais = 0

    for idx, sitio in enumerate(destinos, 1):
        nombre_sitio = sitio["nombre"]
        depto_sitio = sitio["departamento"]
        nombre_sitio_low = nombre_sitio.lower()

        # Si ya está en el derivado y no forzamos recarga, reusarlo
        if not forzar_recarga and nombre_sitio_low in mapa_sitios_guardados:
            print(f"[{idx}/{len(destinos)}] Destino '{nombre_sitio}' recuperado desde caché derivado.")
            d_cache = mapa_sitios_guardados[nombre_sitio_low]
            sitios_analizados.append(d_cache)
            r = d_cache["resumen_tarifas"]
            total_lugares_pais += r["total_lugares"]
            total_gratuitos_pais += r["gratuitos"]
            total_de_pago_pais += r["de_pago"]
            continue

        print(f"[{idx}/{len(destinos)}] Explorando destino: {nombre_sitio} ({depto_sitio})")
        items_crudos = consultar_serpapi_maps_sitio(sitio, api_key, forzar_recarga=forzar_recarga)

        lugares_sitio = []
        ids_vistos = set()

        for it in items_crudos:
            titulo = (it.get("title") or "").strip()
            if not titulo:
                continue

            tipo_lugar = (it.get("type") or "").lower()
            palabras_excluidas = ["hotel", "restaurante", "inmobiliaria", "bar", "hostel", "alquiler", "cerrajería", "farmacia"]
            if any(pe in tipo_lugar for pe in palabras_excluidas) and "parque" not in titulo.lower():
                continue

            place_id = it.get("place_id") or re.sub(r"[^\w]", "", titulo.lower())
            if place_id in ids_vistos:
                continue
            ids_vistos.add(place_id)

            clasif = clasificar_lugar(it, sitio)

            lugares_sitio.append({
                "nombre": titulo,
                "categoria": clasif["categoria"],
                "tipo_tarifa": clasif["tipo_tarifa"],
                "detalle_tarifa": clasif["detalle_tarifa"],
                "direccion": it.get("address") or f"{nombre_sitio}, {depto_sitio}",
                "calificacion": it.get("rating"),
                "total_resenas": it.get("reviews"),
                "tipo_google": it.get("type"),
                "enlace_maps": it.get("link") or f"https://www.google.com/maps/search/?api=1&query={requests.utils.quote(titulo)}"
            })

        cant_total_sitio = len(lugares_sitio)
        cant_gratis_sitio = sum(1 for x in lugares_sitio if x["tipo_tarifa"] == "Gratuito")
        cant_pago_sitio = sum(1 for x in lugares_sitio if x["tipo_tarifa"] == "De Pago")

        pct_gratis_sitio = round((cant_gratis_sitio / cant_total_sitio * 100), 1) if cant_total_sitio > 0 else 0.0
        pct_pago_sitio = round((cant_pago_sitio / cant_total_sitio * 100), 1) if cant_total_sitio > 0 else 0.0

        desglose_categorias_sitio = {}
        for x in lugares_sitio:
            cat = x["categoria"]
            if cat not in desglose_categorias_sitio:
                desglose_categorias_sitio[cat] = {"total": 0, "gratuitos": 0, "de_pago": 0, "lugares": []}
            desglose_categorias_sitio[cat]["total"] += 1
            desglose_categorias_sitio[cat]["lugares"].append(x["nombre"])
            if x["tipo_tarifa"] == "Gratuito":
                desglose_categorias_sitio[cat]["gratuitos"] += 1
            else:
                desglose_categorias_sitio[cat]["de_pago"] += 1

        sitios_analizados.append({
            "id": idx,
            "sitio": nombre_sitio,
            "departamento": depto_sitio,
            "resumen_tarifas": {
                "total_lugares": cant_total_sitio,
                "gratuitos": cant_gratis_sitio,
                "porcentaje_gratuitos": pct_gratis_sitio,
                "de_pago": cant_pago_sitio,
                "porcentaje_de_pago": pct_pago_sitio
            },
            "desglose_por_categoria": desglose_categorias_sitio,
            "lugares": lugares_sitio
        })

        total_lugares_pais += cant_total_sitio
        total_gratuitos_pais += cant_gratis_sitio
        total_de_pago_pais += cant_pago_sitio

    # Actualizar o consolidar en mapa general para guardar
    mapa_actualizado = dict(mapa_sitios_guardados)
    for s in sitios_analizados:
        mapa_actualizado[s["sitio"].lower()] = s

    lista_final = list(mapa_actualizado.values())
    tot_lugares = sum(s["resumen_tarifas"]["total_lugares"] for s in lista_final)
    tot_gratis = sum(s["resumen_tarifas"]["gratuitos"] for s in lista_final)
    tot_pago = sum(s["resumen_tarifas"]["de_pago"] for s in lista_final)
    pct_gratis = round((tot_gratis / tot_lugares * 100), 1) if tot_lugares > 0 else 0.0
    pct_pago = round((tot_pago / tot_lugares * 100), 1) if tot_lugares > 0 else 0.0

    DIR_DERIVADO.mkdir(parents=True, exist_ok=True)
    documento_derivado = {
        "metadata": {
            "fecha_analisis": datetime.datetime.now().isoformat(),
            "pais": "Uruguay",
            "fuente_sitios": "Lugares turísticos.txt",
            "total_sitios_analizados": len(lista_final),
            "totales_pais": {
                "total_lugares": tot_lugares,
                "gratuitos": tot_gratis,
                "porcentaje_gratuitos": pct_gratis,
                "de_pago": tot_pago,
                "porcentaje_de_pago": pct_pago
            }
        },
        "destinos": lista_final
    }

    ARCHIVO_DERIVADO.write_text(json.dumps(documento_derivado, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ [CONSOLIDADO DERIVADO] Guardado y actualizado exitosamente en '{ARCHIVO_DERIVADO}'.")

    # Retornar los solicitados específicamente
    destinos_retorno = [mapa_actualizado[d["nombre"].lower()] for d in destinos if d["nombre"].lower() in mapa_actualizado]
    return {
        "metadata": documento_derivado["metadata"],
        "destinos": destinos_retorno
    }


def mostrar_reporte_por_sitio(datos: dict):
    """Muestra el reporte con el desglose en consola."""
    meta = datos.get("metadata", {})
    totales_pais = meta.get("totales_pais", {})
    destinos = datos.get("destinos", [])

    print("\n" + "=" * 95)
    print("📊 REPORTE NACIONAL: LUGARES TURÍSTICOS POR SITIO Y TIPO DE ACCESO (GRATUITO VS. DE PAGO)")
    print("=" * 95)
    print(f" • Sitios evaluados:                 {meta.get('total_sitios_analizados', 0)} destinos de 'Lugares turísticos.txt'")
    print(f" • Total de lugares encontrados:     {totales_pais.get('total_lugares', 0)}")
    print(f" • 🟢 Total lugares GRATUITOS:       {totales_pais.get('gratuitos', 0)} ({totales_pais.get('porcentaje_gratuitos', 0)}%)")
    print(f" • 🟡 Total lugares DE PAGO:         {totales_pais.get('de_pago', 0)} ({totales_pais.get('porcentaje_de_pago', 0)}%)")
    print("=" * 95)

    for d in destinos:
        r = d["resumen_tarifas"]
        print(f"\n📍 SITIO: {d['sitio'].upper()} ({d['departamento']})")
        print(f"   Total lugares: {r['total_lugares']} | 🟢 Gratuitos: {r['gratuitos']} ({r['porcentaje_gratuitos']}%) | 🟡 De Pago: {r['de_pago']} ({r['porcentaje_de_pago']}%)")
        print("   " + "-" * 88)

        desglose = d.get("desglose_por_categoria", {})
        if not desglose:
            print("   (No se encontraron atracciones específicas registradas en caché para este destino)")
        else:
            print("   📁 Desglose por Categoría Temática:")
            for cat_nom, st in desglose.items():
                print(f"      ▶ {cat_nom}: {st['total']} lugares  (🟢 {st['gratuitos']} gratis, 🟡 {st['de_pago']} pagos)")

            print("\n   🏛️ Principales Lugares del Sitio:")
            for it in d.get("lugares", [])[:6]:
                icono = "🟢 [GRATIS]" if it["tipo_tarifa"] == "Gratuito" else "🟡 [PAGO]  "
                calif = f" | ⭐ {it['calificacion']}" if it.get("calificacion") else ""
                print(f"      • {icono} {it['nombre']}{calif}")
                print(f"        Tarifa: {it['detalle_tarifa']}")
                if it.get("enlace_maps"):
                    print(f"        Maps: {it['enlace_maps']}")

    print("\n" + "=" * 95)
    print("📈 TABLA RESUMEN COMPARATIVA POR DESTINO:")
    print("=" * 95)
    print(f"{'Destino':<28} | {'Depto':<12} | {'Total':<6} | {'Gratis':<8} | {'De Pago':<8} | {'% Gratis':<9}")
    print("-" * 95)
    for d in destinos:
        r = d["resumen_tarifas"]
        print(f"{d['sitio']:<28} | {d['departamento']:<12} | {r['total_lugares']:<6} | {r['gratuitos']:<8} | {r['de_pago']:<8} | {r['porcentaje_gratuitos']:<8}%")
    print("=" * 95 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="Lugares turísticos por sitio utilizando SerpApi y cargando los destinos desde 'Lugares turísticos.txt'."
    )
    parser.add_argument("--destinos", type=str, default="todos", help="Destinos específicos separados por coma o 'todos' (por defecto 'todos').")
    parser.add_argument("--forzar-recarga", action="store_true", help="Ignora la caché en disco y vuelve a consultar SerpApi.")

    args = parser.parse_args()

    # Prioridad de la API Key en código, entorno o terminal
    api_key = SERPAPI_API_KEY.strip() or os.environ.get("SERPAPI_API_KEY", "").strip()
    if not api_key:
        api_key = input("Ingrese su API Key de SerpApi (presione Enter si usará datos en caché): ").strip()

    destinos_todos = cargar_destinos_desde_txt()

    if args.destinos.lower() != "todos":
        nombres_filtro = [n.strip().lower() for n in args.destinos.split(",") if n.strip()]
        destinos_a_procesar = [
            d for d in destinos_todos
            if any(nf in d["nombre"].lower() for nf in nombres_filtro)
        ]
        if not destinos_a_procesar:
            print(f"[ALERTA] No se encontró ningún destino coincidente con '{args.destinos}'. Se procesarán todos.")
            destinos_a_procesar = destinos_todos
    else:
        destinos_a_procesar = destinos_todos

    datos = procesar_lugares_por_sitio(destinos=destinos_a_procesar, api_key=api_key, forzar_recarga=args.forzar_recarga)
    mostrar_reporte_por_sitio(datos)


if __name__ == "__main__":
    main()
