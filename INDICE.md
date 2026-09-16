### Índice de Escapada: Fórmula, Pesos y Fundamentación del Programa



El programa integrador (decision\_final\_escapadas.py) determina cuál es la escapada óptima de fin de semana largo en Uruguay cruzando tres fuentes de datos (atractivos turísticos, registros meteorológicos y afluencia histórica). La selección no utiliza una fórmula matemática, sino un *modelo que filtra datos secuencialmente acompañado de una jerarquización multicriterio*.



##### 1\. El Proceso de Decisión y los Pesos



El modelo formaliza cada escapada candidata como un par (Destino, Finde) y opera en tres fases:



1. **Filtro de Gratuidad**:
Se consideran únicamente aquellos destinos cuyo top de lugares turísticos evaluados sea 100% libre de costo.
2. **Filtro de Viabilidad Climática**:
Para cada fin de semana largo del año, se exige que se cumplan en simultáneo: que la temperatura media sea entre los 20.0°C y los 25.0°C, que la lluvia total sea menor a 2.0mm, y que los vientos no superen los 19.0km/h. Se descarta cualquier combinación o destino que no garantice estas condiciones.
3. **Función de Ordenamiento y Ranking Multivariable**:
Las combinaciones que superan los filtros se evalúan mediante una tupla
*ranking = sorted(escapadas, key=lambda x: (x\["promedio\_aglo"], -x\["total\_gratis"], x\["lluvia"], x\["viento"]))*
en donde *x\["promedio\_aglo"]* compara el índice de afluencia (de 0 a 100 de Google Trends), generando que la opción con menor aglomeración queda en primer lugar, -*x\["total\_gratis"]* produce que si dos opciones tienen la misma aglomeración, desempata por cantidad de lugares turísticos gratuitos (El signo negativo (-) hace que un número mayor pase a ser más chico en la comparación, ordenando de mayor a menor), *x\["lluvia"]* aparece porque si dos destinos y fechas aún empatan en los dos casos anteriores, gana la escapada con menos milímetros de lluvia acumulada, y, finalmente, con *x\["viento"]* si empatan en todo lo anterior, gana la de menor velocidad de viento promedio en km/h.



##### 2\. Justificación de los Pesos



Las actividades gratuitas para todas las edades son la base porque consideramos que si un destino no ofrece alternativas sin costo, el visitante queda condicionado a invertir dinero para su disfrute, limitarse a caminar y trasladarse por la zona (lo cual se arruina ante cualquier imprevisto climático) o permanecer encerrado en el alojamiento. En segundo lugar se halla el clima dado que, por más amplia que sea la oferta de un lugar, temperaturas extremas o temporales impiden el disfrute al aire libre y arruinan la experiencia. Finalmente, la aglomeración es el factor decisivo de calidad, porque una vez aseguradas actividades sin costo y un buen clima, la saturación de visitantes es lo que define el éxito del viaje. Una afluencia baja evita esperas, agobios y colapsos en servicios y espacios públicos, garantizando un verdadero descanso.

