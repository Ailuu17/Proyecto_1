"""
decision_final_escapadas.py
===========================
Programa final que responde: CUÁL ES EL MEJOR FIN DE SEMANA LARGO DEL ANO
para escaparse en Uruguay, y a donde?

Cruza datos de los tres programas anteriores:
  - programa_lugares_turisticos.py   - datos/derivado/lugares_turisticos_por_sitio.json
  - programa_clima_findes.py        - datos/derivado/clima_findes_largos_10anios.json
  - programa_aglomeraciones.py  - datos/derivado/aglomeracion_fechas_por_sitio.json

Logica:
  1. Filtra destinos con 100 % de lugares gratuitos.
  2. Para cada fin de semana largo del ano actual, evalua el clima de ese
     destino (usando datos del ano actual; si aun no hay, usa el ano anterior).
  3. Clasifica el clima como BUENO si:
        - Temperatura media entre 20 C y 25 C
        - Lluvia total <= 2 mm
        - Viento maximo promedio < 19 km/h
  4. Descarta destinos que no tienen NINGUN fin de semana con clima bueno.
  5. Rankea los restantes por:
        a. Menor aglomeracion promedio en los fines buenos (ano actual si hay).
        b. Si empatan: mas lugares turisticos gratuitos.
        c. Si empatan: menor lluvia promedio en los fines buenos.
        d. Si empatan: menor viento promedio en los fines buenos.
  6. Imprime el ranking con razonamiento y seccion informativa del proceso.
"""

import json
import os
import sys
from datetime import datetime

# Forzar salida UTF-8 para que los acentos se muestren bien en Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Rutas de los archivos de cache derivado
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DERIVADO  = os.path.join(BASE_DIR, "datos", "derivado")

ARCHIVO_LUGARES    = os.path.join(DERIVADO, "lugares_turisticos_por_sitio.json")
ARCHIVO_CLIMA      = os.path.join(DERIVADO, "clima_findes_largos_10anios.json")
ARCHIVO_AGLO       = os.path.join(DERIVADO, "aglomeracion_fechas_por_sitio.json")

# Umbrales de "clima bueno"
TEMP_MIN   = 20.0   # C
TEMP_MAX   = 25.0   # C
LLUVIA_MAX = 2.0    # mm totales en el fin de semana
VIENTO_MAX = 19.0   # km/h (viento maximo promedio)

# Porcentaje minimo de gratuidad para ser considerado "100% gratis"
GRATUIDAD_MIN = 100.0


def cargar_json(ruta):
    with open(ruta, encoding="utf-8") as f:
        return json.load(f)


def clima_es_bueno(finde):
    """Devuelve True si el finde cumple todos los criterios de buen clima."""
    temp   = finde.get("temp_media_promedio")
    lluvia = finde.get("precipitacion_total_mm")
    viento = finde.get("viento_max_promedio_kmh")
    if temp is None or lluvia is None or viento is None:
        return False
    return (TEMP_MIN <= temp <= TEMP_MAX) and (lluvia <= LLUVIA_MAX) and (viento < VIENTO_MAX)


def nivel_afluencia_texto(promedio_interes):
    if promedio_interes is None:
        return "Sin datos (-)"
    if promedio_interes < 15:
        return "Baja"
    elif promedio_interes < 40:
        return "Moderada"
    elif promedio_interes < 70:
        return "Alta"
    else:
        return "Muy Alta / Saturado"


def nivel_afluencia_icono(promedio_interes):
    if promedio_interes is None:
        return "[-]"
    if promedio_interes < 15:
        return "[BAJA]"
    elif promedio_interes < 40:
        return "[MODERADA]"
    elif promedio_interes < 70:
        return "[ALTA]"
    else:
        return "[MUY ALTA]"


def verificar_archivos():
    for ruta, nombre in [
        (ARCHIVO_LUGARES, "lugares_turisticos_por_sitio.json"),
        (ARCHIVO_CLIMA,   "clima_findes_largos_10anios.json"),
        (ARCHIVO_AGLO,    "aglomeracion_fechas_por_sitio.json"),
    ]:
        if not os.path.exists(ruta):
            raise FileNotFoundError(
                f"No se encontro el archivo '{nombre}'.\n"
                f"Asegurate de haber corrido primero los tres programas anteriores.\n"
                f"Ruta esperada: {ruta}"
            )


def wrap_texto(texto, ancho=65, prefijo="         "):
    palabras = texto.split()
    linea_actual = prefijo
    resultado = []
    for p in palabras:
        if len(linea_actual) + len(p) + 1 > ancho + len(prefijo):
            resultado.append(linea_actual)
            linea_actual = prefijo + p
        else:
            if linea_actual.strip():
                linea_actual += " " + p
            else:
                linea_actual += p
    resultado.append(linea_actual)
    return "\n".join(resultado)


def imprimir_info_proceso(anio_actual, finde_largos_2026, destinos_gratis,
                           evaluaciones, datos_lugares, datos_clima, datos_aglo):
    sep_mayor = "=" * 72
    total_destinos_txt  = len(datos_lugares["destinos"])
    total_gratis        = len(destinos_gratis)
    total_descartados   = total_destinos_txt - total_gratis
    destinos_con_buenos = len(evaluaciones)
    destinos_sin_buenos = total_gratis - destinos_con_buenos

    print()
    print(sep_mayor)
    print("  [i] INFORMACION DEL PROCESO")
    print(sep_mayor)
    print()
    print("  Fuentes de datos:")
    print("    * Atractivos turisticos  -> SerpApi (Google Maps Engine)")
    print("    * Clima                  -> Open-Meteo Archive API")
    print("    * Aglomeracion           -> SerpApi (Google Trends Engine)")
    print("    * Feriados y fins largos -> Nager.Date API")
    print()
    print("  Destinos evaluados:")
    print(f"    * Total en Lugares turisticos.txt : {total_destinos_txt}")
    print(f"    * Con 100% gratuidad              : {total_gratis}")
    print(f"    * Descartados por tener costo     : {total_descartados}")
    if total_descartados:
        descartados = [
            d["sitio"] for d in datos_lugares["destinos"]
            if d["resumen_tarifas"]["porcentaje_gratuitos"] < GRATUIDAD_MIN
        ]
        print(f"      -> {', '.join(descartados)}")
    print()
    print(f"  Fins de semana largos en {anio_actual} (Nager.Date):")
    for fw in finde_largos_2026:
        print(f"    * {fw['feriados'][:45]:45s}  {fw['inicio']} -> {fw['fin']}  ({fw['duracion_dias']} dias)")
    print()
    print("  Criterio de 'buen clima':")
    print(f"    * Temperatura media   entre {TEMP_MIN} y {TEMP_MAX} C")
    print(f"    * Lluvia total        <= {LLUVIA_MAX} mm en el fin de semana")
    print(f"    * Viento max promedio < {VIENTO_MAX} km/h")
    print()
    print("  Resultados del filtro climatico:")
    print(f"    * Destinos gratuitos con al menos 1 fin de semana bueno : {destinos_con_buenos}")
    print(f"    * Descartados por no tener ningún fin de semana bueno   : {destinos_sin_buenos}")
    if destinos_sin_buenos:
        sin_finde_bueno = [n for n in destinos_gratis if n not in evaluaciones]
        print(f"      -> {', '.join(sin_finde_bueno)}")
    print()
    print("  Criterio de ranking individual (Top 10 - destino y fin de semana):")
    print("    1  Menor aglomeración en el fin de semana largo específico")
    print("    2  Mayor cantidad de atractivos 100% gratuitos en el destino")
    print("    3  Menor lluvia prevista en el fin de semana largo")
    print("    4  Menor viento máximo promedio en el fin de semana largo")
    print()
    anios_clima = datos_clima.get("anios_consultados", [])
    anios_aglo  = datos_aglo["metadata"]["anios_analizados"]
    if anios_clima:
        print(f"  Datos de clima: Open-Meteo Archive (años {anios_clima[0]}-{anios_clima[-1]})")
    print(f"  Datos de aglomeracion: Google Trends ({', '.join(str(a) for a in anios_aglo)})")
    print()
    print(sep_mayor)
    print(f"  Generado el {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    print(sep_mayor)
    print()


def main():
    anio_actual = datetime.now().year
    anio_ant    = anio_actual - 1

    verificar_archivos()
    datos_lugares = cargar_json(ARCHIVO_LUGARES)
    datos_clima   = cargar_json(ARCHIVO_CLIMA)
    datos_aglo    = cargar_json(ARCHIVO_AGLO)

    # 1. Destinos 100% gratuitos
    destinos_gratis = {}
    for dest in datos_lugares["destinos"]:
        pct = dest["resumen_tarifas"]["porcentaje_gratuitos"]
        if pct >= GRATUIDAD_MIN:
            nombre = dest["sitio"]
            destinos_gratis[nombre] = {
                "departamento":    dest["departamento"],
                "total_gratuitos": dest["resumen_tarifas"]["gratuitos"],
                "total_lugares":   dest["resumen_tarifas"]["total_lugares"],
                "porcentaje":      pct,
            }

    # 2. Indice de clima por destino
    clima_index = {}
    for dest in datos_clima["destinos"]:
        nombre = dest["nombre"]
        if nombre not in destinos_gratis:
            continue
        clima_index[nombre] = {}
        for anio_str, info_anio in dest.get("clima_por_año", {}).items():
            for finde in info_anio.get("findes", []):
                clima_index[nombre][finde["inicio"]] = {**finde, "anio": int(anio_str)}

    # 3. Indice de aglomeracion por finde y destino
    aglo_index = {}
    for anio_str, finde_list in datos_aglo.get("aglomeraciones_por_año", {}).items():
        for finde in finde_list:
            inicio = finde["inicio"]
            if inicio not in aglo_index:
                aglo_index[inicio] = {}
            for dest, info in finde.get("aglomeracion_por_destino", {}).items():
                aglo_index[inicio][dest] = info

    # 4. Fins de semana largos del año actual
    finde_largos_2026 = datos_aglo["aglomeraciones_por_año"].get(str(anio_actual), [])

    if not finde_largos_2026:
        print(f"No hay fins de semana largos registrados para {anio_actual}.")
        return

    # 5. Evaluar cada destino gratis en cada fin de semana
    evaluaciones = {}

    for nombre in destinos_gratis:
        finde_buenos = []
        for finde_aglo in finde_largos_2026:
            inicio   = finde_aglo["inicio"]
            fin      = finde_aglo["fin"]
            feriados = finde_aglo["feriados"]

            # Buscar clima: preferir año actual, si no usar año anterior
            finde_clima = None
            if nombre in clima_index:
                if inicio in clima_index[nombre]:
                    finde_clima = clima_index[nombre][inicio]
                else:
                    # Buscar mismo finde en año anterior
                    inicio_ant = inicio.replace(str(anio_actual), str(anio_ant))
                    if inicio_ant in clima_index[nombre]:
                        finde_clima = clima_index[nombre][inicio_ant]

            if finde_clima is None:
                continue

            if not clima_es_bueno(finde_clima):
                continue

            # Aglomeracion del año actual para este destino y finde
            info_aglo_dest = aglo_index.get(inicio, {}).get(nombre)
            promedio_aglo = None
            if info_aglo_dest is not None:
                promedio_aglo = info_aglo_dest.get("promedio_interes")

            if promedio_aglo is None:
                # Calcular promedio de los anos disponibles con métricas reales
                promedios = []
                for anio_str_loop, fl in datos_aglo.get("aglomeraciones_por_año", {}).items():
                    for fw in fl:
                        if fw.get("feriados") == feriados:
                            info = fw.get("aglomeracion_por_destino", {}).get(nombre)
                            if info and info.get("promedio_interes") is not None:
                                promedios.append(info["promedio_interes"])
                promedio_aglo = (sum(promedios) / len(promedios)) if promedios else 50.0

            finde_buenos.append({
                "inicio":        inicio,
                "fin":           fin,
                "feriados":      feriados,
                "duracion_dias": finde_aglo["duracion_dias"],
                "temp_media":    finde_clima["temp_media_promedio"],
                "lluvia":        finde_clima["precipitacion_total_mm"],
                "viento":        finde_clima["viento_max_promedio_kmh"],
                "promedio_aglo": promedio_aglo,
                "anio_clima":    finde_clima["anio"],
            })

        if finde_buenos:
            evaluaciones[nombre] = finde_buenos

    # 6. Construir y rankear cada opción de escapada individual (Destino + Fin de semana)
    escapadas = []
    for nombre, finde_list in evaluaciones.items():
        info_d = destinos_gratis[nombre]
        for f in finde_list:
            escapadas.append({
                "destino":       nombre,
                "departamento":  info_d["departamento"],
                "total_gratis":  info_d["total_gratuitos"],
                "pct_gratis":    info_d["porcentaje"],
                "feriados":      f["feriados"],
                "inicio":        f["inicio"],
                "fin":           f["fin"],
                "duracion_dias": f["duracion_dias"],
                "temp_media":    f["temp_media"],
                "lluvia":        f["lluvia"],
                "viento":        f["viento"],
                "promedio_aglo": f["promedio_aglo"],
                "anio_clima":    f["anio_clima"],
            })

    # Criterio de ranking individual:
    # 1. Menor aglomeración en ese fin de semana específico
    # 2. Mayor cantidad de atractivos 100% gratuitos en el destino
    # 3. Menor lluvia
    # 4. Menor viento
    ranking = sorted(
        escapadas,
        key=lambda x: (x["promedio_aglo"], -x["total_gratis"], x["lluvia"], x["viento"])
    )

    # ────────────────────────────────────────────────────────────────────────
    # IMPRESION
    # ────────────────────────────────────────────────────────────────────────
    sep_mayor = "=" * 72
    sep_menor = "-" * 72

    print()
    print(sep_mayor)
    print("¿CUÁL ES EL MEJOR FIN DE SEMANA LARGO PARA ESCAPARSE EN URUGUAY, Y A DÓNDE?")
    print(sep_mayor)
    print(f"\n  Año analizado  : {anio_actual}")
    print(f"  Criterio clima : Temp. media {TEMP_MIN}-{TEMP_MAX} C  |  "
          f"Lluvia <= {LLUVIA_MAX} mm  |  Viento < {VIENTO_MAX} km/h")
    print(f"  Destinos 100% gratuitos : {len(destinos_gratis)} de {len(datos_lugares['destinos'])}")
    print()

    if not ranking:
        print("  No hay escapadas de destinos 100% gratuitos con clima bueno este año.")
        print()
        imprimir_info_proceso(anio_actual, finde_largos_2026, destinos_gratis,
                              evaluaciones, datos_lugares, datos_clima, datos_aglo)
        return

    top_n = min(10, len(ranking))
    print(sep_mayor)
    print(f"TOP {top_n} MEJORES ESCAPADAS EN {anio_actual} (DESTINO Y FIN DE SEMANA)")
    print(sep_mayor)
    print()

    posiciones = ["[1ro]", "[2do]", "[3ro]", "[4to]", "[5to]",
                  "[6to]", "[7mo]", "[8vo]", "[9no]", "[10mo]"]

    for pos in range(top_n):
        escapada = ranking[pos]
        pos_txt = posiciones[pos] if pos < len(posiciones) else f"[{pos+1}]"
        nota_anio = f" (datos clima {escapada['anio_clima']})" if escapada["anio_clima"] != anio_actual else ""

        print(f"  {pos_txt}  {escapada['destino']} en {escapada['feriados']}")
        print(f"         Destino y Departamento                 : {escapada['destino']} ({escapada['departamento']})")
        print(f"         Fin de semana largo                    : {escapada['feriados']}")
        print(f"         Período y Duración                     : {escapada['inicio']} al {escapada['fin']} ({escapada['duracion_dias']} días){nota_anio}")
        print(f"         Clima previsto                         : Temp: {escapada['temp_media']:.1f} C  |  "
              f"Lluvia: {escapada['lluvia']:.1f} mm  |  "
              f"Viento: {escapada['viento']:.1f} km/h")
        print(f"         Aglomeración estimada                  : {escapada['promedio_aglo']:.1f}/100  "
              f"{nivel_afluencia_icono(escapada['promedio_aglo'])} ({nivel_afluencia_texto(escapada['promedio_aglo'])})")
        print(f"         Lugares turísticos 100% gratuitos      : {escapada['total_gratis']} lugares")
        print()

    imprimir_info_proceso(anio_actual, finde_largos_2026, destinos_gratis,
                          evaluaciones, datos_lugares, datos_clima, datos_aglo)


if __name__ == "__main__":
    main()
