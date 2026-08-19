# Registro de cambios

El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y el
versionado es [semántico](https://semver.org/lang/es/).

## [No publicado]

### Agregado

- **Las métricas compuestas se agrupan por su tabla de medidas.** Una compuesta no
  sale de ningún hecho, así que caían todas en un montón llamado «compuesta» — con
  cincuenta y ocho, eso dice de qué NO son y no de qué son. Ahora las ordena la tabla
  de medidas donde se guardaron, que es como se agrupan en el modelo. Las de un hecho
  siguen diciendo de qué hecho salen: es la nota con la que se comprueba una cifra.

- **El PDF se genera en el servidor: «Descargar PDF», sin diálogo de impresión.** El
  camino del navegador no llegaba. `window.print()` obliga a pasar por el diálogo
  —ninguna página web puede elegir el destino de impresión, y eso no se rodea— y además
  **Safari ignora el tamaño de página que pide el documento**, así que la hoja de una
  sola página salía en tamaño Carta y cortada. Ahora el servidor abre esta misma
  pantalla con su propio Chromium y devuelve el archivo hecho: igual en Safari que en
  Chrome, y también en PNG. Las dos formas de imprimir siguen ahí, debajo de una raya.

  Es el mismo código el que mide en los dos caminos (`medirHoja.ts`, que el servidor
  dispara con `?informe=una-hoja`): dos formas de medir la misma hoja se desvían la
  primera semana que alguien toque una. El archivo se genera con el token de quien lo
  pide, así que **las políticas de seguridad por fila se aplican igual que en
  pantalla** — un informe que se las salta porque lo generó el servidor sería una
  puerta trasera con formato PDF.

  Chromium, y no una librería de PDF, porque lo que hay que dibujar es la hoja tal como
  está: rejilla CSS y gráficos que se pintan con JavaScript en un `canvas`. WeasyPrint
  no ejecuta JavaScript —los gráficos saldrían en blanco— y wkhtmltopdf usa un WebKit
  de hace una década que no entiende la rejilla. Licencias: Playwright Apache-2.0,
  Chromium BSD; uso comercial sin condiciones. El instalador de Windows lo descarga, y
  **avisa** si no pudo: mejor saberlo al instalar que el día 2 a las 7 de la mañana.

- **El widget de texto sirve de título de sección: tamaño, color, negrita y
  alineación.** Los tamaños van con nombre —Nota, Normal, Subtítulo, Título, Título
  grande, Portada— y no como número libre, para que los títulos de dos hojas salgan
  del mismo juego. Un texto sin título propio **no dibuja tarjeta** en la vista: se
  lee como parte de la hoja y no como un widget más; al editar recupera el marco, que
  es el asa con la que se arrastra. El color es opcional: sin poner ninguno sigue el
  tema y se lee igual en claro y en oscuro.

- **Los widgets de una hoja se pueden subir y bajar con ↑ / ↓.** Mueven la **banda**
  —los widgets que empiezan en la misma fila, como los tres filtros de arriba—, y las
  dos bandas se reparten el sitio que ocupaban, así que nada de lo que hay más arriba
  o más abajo se mueve. Por bandas y no por posición en una lista porque una hoja es
  una rejilla: dos widgets pueden estar uno al lado del otro, y en una lista eso no se
  puede decir. La lista, además, sale ahora en el orden en que se lee la hoja — el
  mismo en que sale el PDF— y no en el que se fueron agregando.

- **Una columna renombrada dice de qué métrica es.** Con noventa y seis métricas y la
  columna renombrada a «% CONV LEAD A TRAF M ANT», el inspector ya no decía cuál se
  había puesto. El nombre del modelo se queda a la vista, atenuado, y al abrirla se
  lee completo con su nombre técnico.

- **El PDF de una sola hoja se ensancha si algo no cabe.** Salía siempre de 1600 px, y
  una tabla de veinte columnas no entra ahí: en pantalla se desplaza dentro de su
  widget, pero en una sola hoja no hay dónde desplazar, así que las últimas columnas
  se quedaban cortadas por el borde de la página — un PDF que enseña doce de veinte y
  no dice que faltan ocho. Ahora se mide lo que se sale y la página crece hasta que
  entra. Lo que quede después de las pasadas se le da a la **página** y no a la hoja:
  la hoja ya no se recompone —cada vez que se ensancha, la tabla pide un poco más y el
  resto no baja de unos pocos píxeles— y una página con tres píxeles de aire a la
  derecha no le hace daño a nadie, mientras que negarse a hacer el PDF por tres
  píxeles sí. Solo se dice que no cuando de verdad se pasa del máximo del navegador. La medida va escalada por la fracción de rejilla del widget: un
  widget de tres columnas de doce crece un cuarto de lo que crece la hoja, así que
  ensancharla solo lo que sobresale se quedaba corto tres veces.

- **El menú del botón PDF no se veía, y el de exportar un widget tampoco del todo.**
  Los dos colgaban dentro de su contenedor, y los dos contenedores recortan lo que
  desborda: la barra del tablero para encogerse en una pantalla angosta en vez de
  empujar al panel de la derecha, y un widget porque es una celda de la rejilla. El
  del PDF quedaba en una tira de tres píxeles; el de un widget se cortaba en los
  widgets bajos. Ahora se dibujan fuera, en un portal con las coordenadas del botón —
  lo mismo que ya hacía la lista de un filtro colapsado, y por lo mismo—, y el
  comportamiento está en un solo sitio para los dos.

- **Una tabla vacía dice por qué está vacía.** «Sin datos para la selección actual»
  se ve igual venga de donde venga, y viene de cuatro sitios que se arreglan en cuatro
  sitios distintos: la tabla no se ha cargado, la unión no encuentra pareja, una
  política tapa todo, o los filtros no dejan nada. Ahora se dice cuál de los cuatro
  es — y en el de la unión, **por dónde** se une, que es el dato con el que se revisa:
  «`FACT_PO` tiene filas, pero ninguna llega al desglose por `FACT_PO.id_sucursal →
  CAT_SUCURSAL.Id_Sucursal`: la unión no encuentra pareja». El de la unión es el más
  caro de los cuatro porque no se parece a un error: se parece a «no hubo ventas».
  Cuesta tres conteos por hecho y solo se pagan cuando ya no hubo filas.

- **«No hay relación entre estas dos tablas» dice qué versión del modelo se está
  consultando.** Casi siempre significa «la hay, pero no en esta versión»: se dibuja
  en el borrador, y hasta que no se publica una versión —y el tablero la adopta— para
  la consulta no existe. Sin decir qué versión se está leyendo, el aviso parece
  contradecir al lienzo, donde la relación está a la vista.

- **Los valores de un filtro se pueden ordenar por otra columna.** «Enero, febrero,
  marzo» no es el orden alfabético: un filtro con el nombre del mes empezaba en abril
  y terminaba en septiembre, y en esa lista nadie encuentra nada. En la tabla de
  campos de la entidad, la columna **orden** dice por qué otra columna de la misma
  entidad se ordena — el nombre del mes por el número del mes. Es el «ordenar por
  columna» de Power BI. Se ofrecen solo columnas de la misma entidad: un orden que
  viniera de otra tabla necesitaría una unión, y entonces el orden de un filtro
  dependería de por dónde se une. El modelo no se guarda si apunta a una columna que
  no existe, ni a sí misma.

- **Una métrica de tiempo ya no exige la columna del mes en la tabla: el mes lo pone
  el contexto.** Antes, «Ventas Mes Anterior» al lado de una fila por sucursal fallaba
  pidiendo una columna de meses en el desglose — y agregarla convierte una fila por
  sucursal en una por sucursal y mes, que es otro informe. Ahora, si el desglose trae
  los meses cada fila compara contra el suyo, como siempre; y si no los trae, los
  meses bajan a una capa escondida —hacen falta, o no habría mes anterior que mirar,
  y para eso se levantan los filtros de fecha igual que `TODO()` levanta un filtro en
  DAX— y arriba se queda solo el mes que manda. Es como funciona Power BI, donde el
  periodo sale del filtro de la página.

  Cuál manda: el último mes que sobreviva a los filtros. Con un mes filtrado ese, con
  solo el año su último mes, y **sin filtro de fecha ninguno, el último mes que tenga
  la cifra que se compara** — no el último con datos de cualquier tabla: un objetivo
  cargado hasta diciembre haría mandar a diciembre, y la fila saldría con el objetivo
  puesto y todas las columnas de venta vacías. Para eso las cifras de las que sale la
  comparación bajan escondidas al detalle, y si ninguna tiene dato en ningún mes manda
  el último que haya, que es mejor que una tabla vacía sin explicación. Eso último trae que la cifra cambie al cargar el mes siguiente sin que
  nadie toque el informe, así que el widget dice encima de la tabla «Comparado contra
  202607» y la respuesta trae `mes_usado`: un número firmado tiene que poder fecharse.
  Solo sigue siendo un error que el modelo no marque ninguna columna como mes, porque
  entonces no hay contexto del que sacar el periodo.

  Los filtros del periodo se levantan **estén en la columna que estén**, siempre que
  sean del calendario: la primera versión solo levantaba la columna marcada como mes,
  así que filtrar por año y por nombre del mes —dos columnas, que es como está armado
  el informe que se está traduciendo— dejaba la capa de dentro con un solo mes y la
  comparación salía vacía, sin decir nada. Se levanta la tabla de fechas entera, como
  en DAX, y para elegir el mes los filtros se vuelven a aplicar contra el calendario.
  Las columnas de esos filtros ya no bajan como dimensiones escondidas: una que no sea
  del grano del mes partiría las cifras en pedazos más chicos y la ventana se
  calcularía por pedazo. Y un filtro de días se rechaza diciéndolo: el mes anterior de
  un día no existe, y estirarlo al mes entero daría las unidades del mes en una fila
  que pedía un día.

- **Las métricas del catálogo, agrupadas por la tabla de la que salen y plegables.**
  Con noventa y seis, una lista plana obliga a atravesar las de ventas para llegar a
  las de refacciones y no deja ver de un golpe qué trae cada tabla. La cabecera de un
  grupo cerrado sigue diciendo cuántas hay dentro y cuántas usa el widget —un grupo
  cerrado que esconde una métrica en uso sería una trampa—; nacen abiertos los que
  aportan algo al widget y cerrados los demás, hasta que alguien decida a mano, que
  entonces manda y se acuerda; y al buscar se abren todos, porque un grupo cerrado
  que esconde el único resultado se lee como «no hay nada». `compuesta` va al final
  y no entre las tablas: no es una tabla, y ponerla en medio haría pensar que existe
  un origen con ese nombre. Mismo mecanismo de plegado que los grupos del ETL y del
  panel del modelo, misma clave y mismo sitio.

- **La hoja entera en PDF, como informe, en una sola página o en A4.** Botón **PDF**
  en la barra del tablero: saca la hoja activa con los filtros puestos, encabezada por
  una portada que solo existe en el documento —tablero, hoja, filtros aplicados, modelo
  y versión, quién lo emitió y cuándo—. Es la misma procedencia que lleva el Excel, y
  por lo mismo: un PDF que circula por correo tiene que poder decir de qué mes es.

  **Una sola hoja** es la de presentar: una única página del alto que haga falta, con
  todo dentro y sin un solo corte, porque no hay dos páginas entre las que partir nada.
  El alto se mide de verdad —se enciende el diseño del informe, se deja que los
  gráficos se recoloquen y se pregunta al navegador cuánto ocupa— y se le escribe a
  `@page`. Va con ocho píxeles de holgura: la maquetación de impresión no redondea
  igual que la de pantalla, y con la medida exacta sobraba una fracción de píxel que
  se llevaba una segunda página en blanco. Si la hoja pasa de las 200 pulgadas que
  admite el navegador se dice y se ofrece A4, en vez de entregar un PDF cortado.

  Lo hace el navegador y no el servidor: el navegador ya tiene la hoja dibujada, con
  sus gráficos y sus colores, y sale texto de verdad en vez de una imagen. Un PDF
  hecho en el servidor pediría un navegador headless instalado allí.

  El papel no es la pantalla, y de ahí casi todo el trabajo: la rejilla conserva las
  columnas de la hoja pero suelta los altos; nada se queda dentro de una caja que se
  desplaza; una tabla larga repite sus encabezados en cada página y su fila de totales
  se imprime **una** vez y al final —un `tfoot` se repite por omisión, y eso pone el
  total de treinta y seis sucursales debajo de las diez que caben en la primera hoja—;
  y el informe sale en la paleta clara aunque la pantalla esté en oscuro, porque el
  tema es de la pantalla y un informe en negativo es un cartucho por hoja.

- **Un widget avisa cuando le faltan filas.** Banda ámbar encima del dato: «Faltan
  filas. Se alcanzó el máximo de N filas y hay más. Lo que se ve es una parte, y los
  totales son los de esa parte.» No se puede cerrar mientras la tabla esté cortada.

  El motor lo sabe con exactitud porque pide **una fila más** de las que enseña, y la
  descarta. Contando las que vuelven no se distingue «justo caben mil» de «hay diez mil
  y se cortaron en mil», y en pantalla esas dos cosas se parecen tanto que nadie mira el
  número dos veces. La respuesta de `/consultar` trae `truncado`, y queda en auditoría.

- **El escenario que lo destapó: en una tabla dinámica el límite contaba filas
  equivocadas.** El usuario escribe filas de la tabla que ve; el motor limitaba filas
  planas, una por cada cruce de fila y columna. Con 36 sucursales, 127 meses y un
  máximo de mil, salían **8 sucursales** y una tabla con toda la pinta de estar entera.
  Ahora la dinámica averigua primero cuántas columnas va a abrir —con los mismos
  filtros, porque los meses que quedan tras una selección son los que saldrán— y pide
  las filas planas que hacen falta. El mismo tablero pasó de 8 a las 36 sucursales que
  tienen venta, y los totales por mes de 774 a 3 522.

- **El estante: los tableros se guardan en carpetas.** Columna de carpetas a la
  izquierda con la cuenta de cada una, «Todos» y «Sin carpeta»; buscador por nombre,
  carpeta y modelo; y al ver todo el estante los resultados se agrupan por carpeta. La
  carpeta se teclea —si ya existe, se ofrece— al crear el tablero o en
  **Editar → Tablero → Carpeta**. Una carpeta existe mientras haya algo dentro: no hay
  que crearla antes ni borrarla después.

  **Una carpeta solo ordena: no da ni quita acceso a nada.** En Qlik un *stream* es a
  la vez la carpeta y el permiso; aquí no, y se dice en la propia pantalla y no solo en
  el manual. Una carpeta que parece un permiso y no lo es sería una trampa: alguien
  pondría los sueldos en una llamada «Dirección» creyendo que ahí quedan guardados.
  Quién ve qué lo siguen decidiendo el rol y el publicado. Hay una prueba que lo fija:
  un tablero sin publicar en una carpeta de nombre serio sigue siendo invisible para un
  lector, y uno publicado se ve esté donde esté.

  La carpeta va en su propia columna de la base y no dentro de la definición del
  tablero, para que reordenar el estante no cuente como cambiarlo.

- **Semáforos: la flecha verde o roja al lado de una cifra.** Se pone por columna, en
  tablas, tablas dinámicas y KPI. Se compara contra un objetivo fijo o contra otra
  columna del mismo widget, y **la dirección se declara**: «más es mejor» no vale para
  todo —los días que un auto lleva en inventario suben y eso está mal—, así que un
  semáforo que pintara verde hacia arriba pondría en verde justo la columna que hay que
  mirar. Si la columna es un porcentaje, el objetivo se escribe como se ve (`100`, no
  `1`).

  Siempre hay **flecha además de color**: uno de cada doce hombres no distingue verde
  de rojo, y una cifra que solo se lee por el color no se lee.

  Y el caso que más engaña: una sucursal **con objetivo y sin ninguna venta** no trae
  cifra, así que no hay nada que comparar. Sale en ámbar con `?` y con la explicación
  al pasar el ratón. Sin marcarla parecería neutral justo cuando es el peor caso de la
  tabla —peor que quien vendió poco, que sale en rojo—, y pintarla como cero sería que
  la pantalla decidiera que «sin filas» significa «cero», que es una decisión de la
  métrica y no del semáforo.

- **Tabla dinámica.** Un desglose en las filas y otro abierto en columnas: la matriz
  de «inventario por modelo y mes», que no se podía armar de ninguna otra forma. Con
  varias métricas la cabecera queda en dos pisos, hay columna de total por fila —se
  puede quitar—, fila de totales abajo, y los desgloses de fila se quedan a la vista
  al desplazar a lo ancho.

  **El cruce se hace en el navegador**, sobre la misma consulta plana que pide
  cualquier otro widget. Así pasa por la misma seguridad por fila, el mismo anclaje de
  versión y el mismo Excel que todo lo demás, en vez de ser el widget especial que
  trae sus datos por otro lado.

  Una celda sin dato queda **en blanco y no en cero**: no es lo mismo «ese mes no hubo
  ninguno» que «no hay fila para ese mes».

  Sobre el orden de las columnas: numérico si los valores son números, y si son texto
  el que devuelve el modelo —alfabético—. Un mes guardado como nombre saldría abril,
  agosto, diciembre, que no es un orden sino un error que parece un orden, así que la
  tabla lo avisa y dice cómo arreglarlo en vez de dibujarlo sin más.

- **Las columnas de un widget se ordenan, y cada una tiene sus propiedades.** Una
  lista aparte del catálogo muestra lo elegido en el orden en que sale, numerado y con
  flechas para moverlo — el orden de las columnas de la tabla y de las series del
  gráfico. Iban en el orden en que se hubiera hecho clic, y no había forma de
  cambiarlo salvo desmarcar todo y volver a empezar.

  Cada columna se abre y tiene **etiqueta** (el nombre en *este* widget; en el modelo
  sigue llamándose igual, que es lo que ven los demás tableros), **formato** (entero,
  decimales, moneda, porcentaje, con el del modelo marcado) y, en las tablas,
  **fila de totales**.

- **Fila de totales en las tablas.** Se pone sola **suma** en dinero y conteos, y
  **sin total** en porcentajes y cifras con decimales: la suma de cuarenta porcentajes
  no significa nada, y una cifra con decimales casi siempre es un promedio, así que
  sumarla daría un número que parece bueno y no lo es. Se puede forzar, y entonces la
  pantalla dice por qué no conviene y cómo se calcula el total bueno de un logro. La
  fila se queda a la vista al desplazar.

- La leyenda de los gráficos deja de mostrar el nombre técnico de la métrica
  (`unidades_vendidas`) y muestra su etiqueta.

- **Un tablero es un libro de hojas.** Se cambia de hoja en una barra de pestañas, y
  cada hoja tiene su propio espacio de trabajo. Los widgets no van dentro de la hoja:
  cada widget dice a cuál pertenece, con lo que un tablero guardado antes de que
  existieran las hojas se abre igual —todos sus widgets en la primera— sin migrar
  nada, los ids siguen siendo únicos en todo el libro, y mover un widget de hoja es
  cambiar un campo en su inspector.

  Las **selecciones son del libro**, no de la hoja: filtrar julio en una hoja y que la
  de al lado siguiera en otro mes es la forma más cara de leer dos cifras que no se
  pueden comparar.

- **El tamaño del espacio de trabajo lo elige quien arma la hoja.** «Cabe en la
  pantalla» —lo que trae de fábrica— reparte el alto visible entre las filas que pida
  la hoja, así que se ve entera sin desplazar; «se desplaza» deja la fila fija y baja
  la página, para un informe largo. La rejilla va de 12 columnas a 24.

  Si lo puesto llega más abajo de las filas declaradas, la hoja **se desplaza de todos
  modos y lo dice**. Recortarlo con `overflow: hidden` dejaría widgets que no se
  pueden ni ver ni alcanzar, y un widget que nadie ve es una cifra que nadie revisa.

- **Buscador en las listas de métricas y de campos del inspector.** Aparece a partir
  de ocho elementos. Busca por el nombre que se ve, por el técnico y por la tabla, sin
  acentos y por trozos en cualquier orden (`logro unid` encuentra «% Logro Unidades»).
  Lo ya elegido nunca se esconde al buscar: si desapareciera de la vista, no habría
  forma de quitarlo sin acordarse de cómo se llamaba. Con noventa y seis métricas, la
  lista sin buscador no era usable.

### Cambiado

- **Fuera los nombres reales que quedaban en comentarios, pruebas y documentación.**
  Marcas y plazas de verdad —y un nombre de tabla con forma de conexión— aparecían en
  comentarios de la interfaz, en un HTML de prueba y en dos documentos. Se cambian por
  los del grupo inventado que ya usa la demo (`Aurex`, `Ekos`, regiones `Norte`/`Sur`)
  y por la convención de conexión que ya estaba en uso (`SUC_SUR__…`).

  Al hacerlo apareció que `demo/probar_modelo.py` **estaba roto**: comprobaba marcas y
  estados que el generador de datos dejó de crear cuando se inventó el grupo, y no lo
  ejecuta ni la integración continua ni ninguna instrucción, así que nadie se enteró.
  Fallaba en 5 de sus comprobaciones; ahora pasan todas, contra los valores que los
  datos traen de verdad.

- **Renombrar o mover de carpeta un tablero certificado ya no le quita el sello.** Solo
  lo quita cambiar su **definición**, que es lo que la certificación dice que se
  revisó. Ninguna de las otras dos toca una cifra, y si descertificaran habría que
  volver a certificar el estante entero cada vez que alguien lo ordena — con lo que el
  sello dejaría de significar nada porque nadie podría mantenerlo puesto.

### Arreglado

- **El widget de filtro ya respeta la etiqueta que le pusiste al campo.** El inspector
  la ofrece —«Solo cambia el nombre en este widget»— y solo la usaban las tablas: el
  panel de filtros seguía enseñando `NOMBRE_MES` por más veces que se escribiera
  «Mes».

- **Un panel de filtros con varios campos no se podía guardar.** La pantalla dejaba
  poner los campos que quepan y los dibujaba bien, pero el servidor seguía exigiendo
  «exactamente un campo» —una regla de antes de que el panel supiera dibujar varios—,
  así que al guardar la barra de filtros de Año, Mes, Estado y Sucursal el tablero se
  rechazaba entero. Ahora lo único que se rechaza es un panel **sin** campos.

- **Un filtro recién agregado salía como lista y no como desplegable.** Se veía como
  que el widget nacía mal y se arreglaba solo al cambiarle el tipo y volver a Filtro.
  La causa: un filtro nuevo no tiene campos todavía, y sin campos el panel no dibujaba
  su contenedor, así que el observador de tamaño se registraba contra nada y no volvía
  a intentarlo — el alto se quedaba en cero para siempre y nunca colapsaba. El
  contenedor se dibuja siempre, aunque esté vacío.

- **La lista de valores del desplegable salía sin estilo**: con viñetas de lista y sin
  los cuatro estados asociativos, mientras la misma lista dentro del panel salía bien.
  El estilo colgaba del panel, y el desplegable se dibuja en un portal fuera de él. Ya
  cuelga de la lista, que es quien lo necesita, y las dos formas se ven igual — que es
  justo lo que el código pretendía al compartir el componente. El desplegable abierto
  además dice de qué campo es: tapa el tablero, y antes había que cerrarlo para saberlo.

- **Un panel de filtros nace como barra y no como columna estrecha.** Ancho de lado a
  lado y bajo, con los campos en fila y salto de línea, como la barra de arriba de una
  hoja de Qlik. Antes nacía en tres columnas, donde el nombre del campo se cortaba.

- **La pestaña Datos ya no se abre con un error de una métrica que nadie eligió.** Al
  entrar se marcan solas las seis primeras métricas, y en un modelo grande entre ellas
  caía una que compara contra otro mes. Ésas necesitan una columna de meses en el
  desglose y al entrar no hay desglose, así que la pantalla se abría con un error
  correcto sobre `% Crec MoM` mientras la métrica marcada por quien miraba era otra —y
  la conclusión razonable era que lo roto era la suya.

  Ahora la selección automática salta las que comparan contra otro mes, **incluidas las
  que lo hacen a través de otra**: `% Crec MoM` no nombra ninguna función de tiempo, la
  nombra `Ventas Mes Anterior`, que es a quien referencia. Hay una prueba en el servidor
  que falla si se agrega una función de tiempo y la lista de la pantalla se queda atrás.

- **Un error de una consulta ya no sobrevive al cambio de selección.** Quitar la métrica
  que causó el error dejaba el error en pantalla, describiendo algo que ya no se estaba
  pidiendo. Se borra al marcar o desmarcar; la tabla de resultados se queda, que lleva
  sus métricas en las cabeceras y se explica sola.

- **Acotar una métrica que ya agrega dejó de salir como error.** `CALCULAR([Total de
  inventario], Dias_Antiguedad < 30)` es correcto —le mete la condición al conteo que
  esa métrica ya hacía, y el SQL sale con un solo `COUNT`— pero la revisión lo marcaba
  en rojo y el diagnóstico lo daba por crítico. En el catálogo `CALCULAR` figura como
  que agrega, porque su resultado *es* una cifra agregada, y eso hacía que se tratara
  como un `SUMA` puesto por fuera. Envolverlo en algo que sí agrega sigue avisando.

- **La revisión de «esto no se puede sumar por meses» era demasiado amplia.** Valía
  para todas las dependencias de la fórmula en cuanto una sola ventana abarcaba varios
  meses, y así rechazaba fórmulas correctas: en `SI(ESVACIO([Objetivo del mes]),
  PROMEDIOMESES([Utilidad media], 3), [Objetivo del mes])` lo único que se suma en tres
  meses es la utilidad media — el objetivo se lee del propio mes, está en la condición y
  fuera de la ventana, así que da igual que sea un promedio. Ahora sólo se exige de lo
  que está dentro de la ventana ancha; metido dentro, se sigue rechazando.

- **La tabla de campos era inalcanzable en una entidad ancha.** Dos cosas la tapaban, y
  juntas hacían que las casillas **ver**, **PII**, **única** y **mes** parecieran no
  existir en la pantalla.

  El aviso de desfase con el origen lista una fila con desplegable por cada columna
  que desapareció: en un catálogo de veintidós columnas eran veintidós desplegables
  empujando la tabla de campos fuera de la vista. Ahora esa lista va plegada cuando
  pasa de cuatro; el aviso se sigue viendo entero.

  Y el nombre del campo se encogía hasta cero. Las seis columnas de la derecha llevan
  ancho fijo y suman unos 300 px, así que en un panel más angosto a la primera no le
  quedaba nada: el encabezado se pisaba con el siguiente y quedaban unas casillas sin
  saber de qué columna eran. Ahora la tabla desborda y su caja la desplaza, y el
  nombre se queda fijo al hacerlo — es lo único que dice de qué fila son las casillas.

### Agregado

- **Importar un YAML pegado.** La pestaña YAML enseñaba el modelo y no había por dónde
  meterlo: un modelo escrito a mano, un respaldo o un juego de métricas traducido de
  otra herramienta sólo podía entrar tecleándolo en el lienzo, una por una. Ahora hay un
  botón **Importar YAML…** con un cuadro donde pegarlo.

  Valen **dos** cosas, porque son dos necesidades distintas. El **modelo completo**
  reemplaza el borrador. Un **trozo con sólo `metricas:`** se mezcla con lo que ya hay
  —es el caso corriente: las entidades ya están dibujadas y lo que llega de fuera son
  las métricas—. La mezcla es por nombre: lo pegado gana sobre la métrica que se llame
  igual y lo que no venga en el texto se queda, así que no desaparece en silencio lo que
  alguien escribió en la pantalla. Al terminar dice qué hizo: *«96 métricas nuevas, 0
  reemplazadas y 1 sin tocar»*.

  Reemplaza o mezcla el **borrador**, nunca una versión publicada: lo que ven los
  tableros no cambia hasta que se publique. Y pasa por las mismas revisiones que lo que
  manda el lienzo —el texto se lee a la definición y se valida— así que una métrica que
  nombra un hecho que no existe no entra, y el error habla de la métrica y no de una
  línea. Un texto que no es ni un modelo ni un juego de métricas se dice como tal, en
  vez del volcado de pydantic con su enlace a `errors.pydantic.dev`.

  El editor sigue siendo de sólo lectura. Teclear encima de lo que se está mirando
  invita a editar la versión publicada por error; importar es un acto con su botón, que
  dice qué va a reemplazar.

- **Acotar una métrica por una columna de otra tabla.** Es el caso más corriente de
  todos: «las ventas cuyo canal es digital», donde el canal no está en la factura
  sino en el catálogo de orígenes. Se escribe con el nombre de la tabla delante:

  ```
  CALCULAR(SUMA(Unidades), DIM_ORIGEN_VENTA.categoria_canal = 'Digital')
  ```

  El compilador une esa tabla **dentro del cálculo del hecho**, que es el único
  sitio donde sirve: acotar después no puede, porque para entonces el hecho ya está
  sumado. Antes esto fallaba con un «Referenced column not found» que hablaba de un
  SQL que nadie había escrito.

  El prefijo es obligatorio y no un adorno: dos tablas suelen tener una columna con
  el mismo nombre —`id_origen` está en el hecho y en la dimensión— y adivinar de cuál
  se hablaba es justo la clase de decisión que este motor no toma en silencio. El
  autocompletado ofrece esas columnas ya con su prefijo.

  La tabla se une **por la izquierda**. En el mismo cálculo viven las demás métricas
  del hecho, y una unión normal les quitaría de en medio las filas cuya clave no casa
  —un origen nulo, un código que no está en el catálogo— cambiando totales que nadie
  pidió filtrar.

  Si el hecho no tiene camino hasta esa tabla, o tiene dos, lo dice el **diagnóstico
  del modelo** y no el tablero de quien sólo estaba mirando una cifra.

- **Comprobar el grano contra los datos.** El grano son las columnas que **juntas**
  identifican una fila: en una tabla de objetivos, la sucursal y el mes — por separado
  las dos se repiten, y juntas no deberían. Es una **afirmación**, y hasta ahora nadie
  la comprobaba: se guardaba y ya. Si un mes se carga dos veces, el objetivo se
  duplica, el porcentaje de logro sale a la mitad y nada protesta.

  Ahora hay un botón **Comprobar** al lado del grano. Cuenta las filas y las
  combinaciones distintas, y dice cuántas sobran: *«5 080 filas para 40 combinaciones
  de sucursal_id: sobran 5 040»*. El número importa — «sobran tres» y «sobran cinco
  mil» se arreglan de formas distintas.

  Las columnas del grano se **eligen de una lista** y quedan como etiquetas con su ×.
  Escribirlas separadas por comas no funcionaba —el campo se comía la coma al
  teclearla— y además pedía el nombre exacto de memoria: un `Fecha_objetivo` con la o
  minúscula no es un error de tipografía, es un grano que habla de una columna que no
  existe. Cambiar el grano borra el resultado de la comprobación anterior, que si no
  se quedaba afirmando de unas columnas lo que se midió de otras.

  Se comprueba con la definición que hay **en pantalla**, sin guardar, porque el
  momento de la duda es mientras se declara. No pasa por las políticas de seguridad
  —filtrar filas cambiaría justo lo que se cuenta— y por eso no devuelve ninguna
  fila, sólo dos números, y lo pide el rol de editor.

  Y el texto de la pantalla ya no promete lo que no hacía. Decía que declarar el
  grano permitía detectar una métrica duplicada; el grano se guardaba, se validaba
  que las columnas existieran, y el motor **no lo miraba nunca**.

- **Una métrica puede elegir por qué relación se une.** Un hecho toca el calendario
  por más de una fecha mucho más a menudo de lo que parece: un contacto tiene fecha
  de primera visita, de asignación y de prueba de manejo, y **cada indicador cuenta
  por la suya**. Es el `USERELATIONSHIP` de DAX.

  Sólo una relación puede seguir activa —si mandaran dos, cada consulta tendría dos
  caminos igual de válidos y el total dependería de cuál eligiera el compilador—.
  Las demás se dejan dibujadas e **inactivas**, y en el editor de la métrica hay una
  casilla por cada una: **Se une por**. Sin marcar nada, se une por la activa, como
  siempre.

  Elegir una no sólo la enciende: **apaga la que estaba activa entre ese mismo par
  de tablas**. Si no, quedarían dos caminos a la vez y el modelo volvería a ser
  ambiguo justo donde se quería precisión.

  Dos métricas del mismo hecho con uniones distintas salen en la misma consulta,
  cada una por su fecha: se agrupan en CTE distintos: por entidad **y** por unión.

  Se comprueba al guardar que la relación exista y que toque al hecho de la métrica.
  Nombrar una que no lo toca no fallaría al compilar —el grafo simplemente no
  cambiaría por ahí— y la cifra saldría por la relación activa sin avisar.

- **Comparar contra otro periodo: el mes anterior, el acumulado del año, el año
  pasado.** Cuatro funciones nuevas, que sólo valen dentro de una métrica compuesta:
  `MESANTERIOR`, `MISMOMESANIOANTERIOR`, `ACUMANIO` y `PROMEDIOMESES`. Son el
  `PREVIOUSMONTH`, `SAMEPERIODLASTYEAR`, `DATESYTD` y `DATESINPERIOD` de DAX.

  **El marco va en meses, no en filas.** La forma fácil de escribir «el mes
  anterior» en SQL es `LAG(1)`, que significa «la fila anterior del resultado»: si
  marzo no tiene ventas, el mes anterior de abril sale siendo febrero, sin una sola
  señal de que lo es. Aquí el marco compara el **valor** del periodo (`RANGE`), así
  que un mes que falta deja el resultado **vacío**, que es la verdad. Hay una prueba
  que quita un mes a propósito y falla si eso deja de cumplirse.

  **La ventana se aplica a cada cifra, no al resultado.**
  `PROMEDIOMESES(DIVIDIR([Utilidad], [Unidades]), 3)` sale como utilidad de tres
  meses entre unidades de tres meses, no como el promedio de tres cocientes. Son
  números distintos y el primero es el que significa en DAX.

  **No se acumula lo que no se puede sumar.** El acumulado del año de un conteo de
  clientes distintos contaría dos veces a quien compró en enero y en marzo: se
  rechaza al consultar. Contra un solo mes sí vale, porque sumar un valor suelto es
  ese valor.

  Para que «el mes anterior» signifique algo hay que decir qué columna nombra un
  mes: es la casilla **mes** nueva en la tabla de campos de una entidad. Se marca
  `Periodo_YYYYMM` o una fecha, nunca un `Mes` de 1 a 12 —se repite cada año, y
  correrlo un mes hacia atrás no significa nada—. Se aceptan las dos formas en que
  suele venir, entero `202601` y fecha, para no tener que tocar el ETL.

  Una función de tiempo **dentro de otra** —el `SAMEPERIODLASTYEAR(DATESYTD(…))` de
  DAX, o sea el acumulado del año pasado— se calcula en **dos capas**: abajo el
  acumulado de cada mes, y encima el desplazamiento de doce. En una sola ventana no
  cabe: para marzo habría que sumar tres meses del año pasado y para noviembre once,
  así que el marco tendría que ensancharse fila a fila y entonces ya no es un marco.
  La capa de abajo pasa la misma revisión que la de arriba, así que partir el
  cálculo en dos no es una forma de colar un acumulado de lo que no se suma.

- **Métricas compuestas: una cifra que sale de dividir dos hechos distintos.** El
  porcentaje de logro es lo vendido entre lo presupuestado, y lo vendido está en las
  facturas mientras que el presupuesto está en otra tabla, a otro grano. Hasta ahora
  no había forma de escribirlo: una métrica se agrega desde **un** hecho, y desde el
  hecho de las ventas la columna del objetivo no existe.

  En «Calcula desde» hay ahora una opción más, **· otras métricas (compuesta)**. Una
  compuesta no lee ninguna tabla: combina otras métricas —`DIVIDIR([Unidades
  Vendidas], [Objetivo de Ventas], 0)`— y puede nombrar cualquiera del modelo, venga
  del hecho que venga.

  Lo importante es **cuándo** se calcula. Cada hecho sigue agregando por su lado, en
  su propio CTE y a su propio grano, y el cociente se hace después, sobre el
  resultado ya agregado. Unir las dos tablas antes multiplicaría el objetivo del mes
  por el número de facturas del mes —el fan trap de siempre, que da un número enorme
  con toda la pinta de estar bien—.

  De ahí salen sus dos límites, que son consecuencia y no capricho: no puede nombrar
  columnas, porque no hay ninguna tabla de la cual sacarlas, ni volver a agregar,
  porque lo que recibe ya viene sumado. Las dos cosas se avisan al guardar y no en el
  primer tablero que la use.

  Pedir una compuesta devuelve **una** columna: sus dependencias se calculan por
  dentro y no se enseñan. Y una compuesta puede apoyarse en otra, con detección de
  ciclos.

  Los modelos de antes no cambian: `entidad` pasó de obligatoria a opcional y una
  métrica que la trae sigue significando exactamente lo mismo.

- **Los grupos de métricas se pliegan, como los de Flujos y Transformar.** Cada cajón
  —una tabla de medidas, o un hecho con sus métricas sueltas— se pliega desde su
  cabecera. Con cinco cajones de seis métricas, llegar al último pedía atravesar
  treinta renglones que en ese momento no interesan.

  Lo que se pulsa es **toda la cabecera** y no sólo el triángulo, que es la misma
  decisión que ya estaba tomada en el panel del ETL: acertarle a nueve píxeles
  cuarenta veces al día es trabajo de verdad. Las acciones que viven dentro de la
  cabecera —`+`, renombrar, quitar— paran el clic, así que renombrar un cajón no lo
  pliega de paso.

  El mecanismo es **el mismo**, no uno parecido: se extrajo a `usePlegado` y ahora lo
  comparten los grupos del ETL y los cajones de métricas. Misma clave, mismo sitio,
  así que plegar significa lo mismo en las dos pantallas. Lo que no se comparte es la
  cabecera: la del cajón lleva su punto de color y sus acciones, y la gris pequeña de
  `Grupo` no le sirve.

  Se recuerda por modelo y por cajón, en el navegador. **No es un cambio del modelo**:
  no marca el borrador como sucio ni obliga a publicar nada.

- **«Reorganizar» el lienzo, y las tablas dejan de solaparse.** Lo que colocaba las
  tablas era `(i % 4) * 300, floor(i / 4) * 340`: una cuadrícula ciega. Con nodos de
  hasta 260 de ancho separados 300, y filas de 340 cuando una tabla de veintidós
  columnas mide más de 500 de alto, **las tablas se montaban unas sobre otras** y las
  líneas cruzaban por encima. Con seis tablas se aguanta; con trece y veinticuatro
  relaciones el lienzo deja de decir nada.

  El botón nuevo del lienzo (⊞) coloca por **capas**, que es la forma del modelo y no
  un accidente: los hechos en la primera columna —son terminales para el motor, nunca
  puente—, las dimensiones que tocan un hecho en la siguiente, las de copo de nieve
  después, y lo que no se relaciona con nada al final, junto. Dentro de cada columna
  el orden se decide por **baricentro** —cada tabla a la altura media de aquellas con
  las que se relaciona, en varias pasadas de ida y vuelta—, que es lo que quita la
  mayoría de los cruces sin resolver un problema NP-completo. Usa el alto **medido**
  de cada tabla, que es la única forma de garantizar que no se toquen.

  Medido sobre el modelo de demostración —11 tablas, 15 relaciones—: las líneas que
  pasaban por encima de una tabla van de **9 a 0**, el largo total de las líneas baja
  un **54 %** y los cruces a la mitad.

  Es un botón y no algo automático a propósito: la disposición viaja con la versión
  del modelo, y mover de sitio el trabajo de alguien sin que lo pida es peor que
  dejarlo desordenado. Se deshace con **un solo** «Deshacer», no con uno por tabla.

  Y una tabla nueva ya no cae en la cuadrícula: se pone a la derecha de todo, en su
  propia columna, donde no puede solaparse con nada.

- **Al pasar el ratón por una tabla, sus relaciones se quedan y las demás se apagan.**
  Con veinticuatro, saber cuáles son las de UNA tabla mirando el dibujo pedía seguir
  una línea con el dedo entre otras veinte que la cruzan. No cambia nada del modelo y
  se deshace solo al quitar el ratón.

- **Tablas de medidas, y una métrica que se distingue de una tabla.** El panel del
  modelo listaba las métricas en plano y sin signo propio: con tres se lee, con
  treinta —lo normal en cuanto un modelo se usa de verdad— es un muro de renglones
  donde no se encuentra ninguna, y encima una métrica se veía igual que una entidad.

  Ahora cada métrica lleva su **Σ**, y se pueden agrupar en **tablas de medidas**:
  cajones que el usuario inventa («KPIs de venta»), como en Power BI. **No son
  entidades**: no tienen datos, no se relacionan con nada y no salen en el lienzo ni
  en el diagnóstico —una entidad sin uniones se marcaría como huérfana, y con razón—.
  Solo ordenan.

  Y por eso la métrica tiene ahora **dos campos distintos**: «Calcula desde» es el
  hecho, que decide el `FROM` del SQL, y «Aparece en» es el cajón. Antes eran uno
  solo llamado «Vive en», que es justo la confusión que hace pensar que ordenar las
  métricas puede cambiar una cifra. No puede: hay una prueba que consulta la misma
  métrica con cajón y sin él y exige el mismo número.

  Lo de antes se ve igual: lo que no está en ningún cajón sigue apareciendo bajo su
  hecho. Quitar un cajón **no borra sus métricas** —vuelven bajo su hecho—, y
  renombrarlo arrastra a las suyas, porque la referencia va por nombre y dejarlas
  apuntando a uno que no existe impediría guardar el modelo.

- **Ya se puede modelar sobre lo que uno cargó y transformó.** Faltaba la mitad del
  camino y no se veía: el modelo semántico solo sabe nombrar tablas, y una carga o el
  resultado de una transformación no son una tabla del motor —son un directorio de
  Parquet—. La transformación corría, escribía sus archivos, y el lienzo del modelo
  **no los encontraba**. Solo se podía modelar sobre los datos de demostración que
  trae el archivo analítico, que es un producto que se puede mirar y no usar.

  Ahora el catálogo ofrece las tres procedencias —**tablas del motor**, **datos
  cargados** y **resultados de transformaciones**— agrupadas en el desplegable, y a
  las dos últimas se les pone una **vista temporal** encima al consultarlas. Vista
  temporal y no una tabla dentro del motor a propósito: el archivo analítico se abre
  en solo lectura, y esa garantía —nada de lo que pase por el ETL puede modificar lo
  que un tablero está leyendo— no se toca. De regalo, la vista apunta a un glob que
  se resuelve en cada consulta, así que **una carga nueva se ve sin reiniciar nada**.

  Tres reglas que hacían falta decidir: una **tabla del motor gana** sobre un Parquet
  del mismo nombre —es lo que ya estaban leyendo los tableros—; un Parquet **no
  declara clave primaria**, así que se sugiere por convención y la marca la persona,
  que es quien sabe; y las secciones **intermedias no se ofrecen**, porque son
  andamiaje y con dieciocho por sucursal el desplegable se vuelve inservible por
  volumen.

- **Crear un modelo, desde la pantalla.** No había botón: el único camino real era el
  sembrador de la demostración o escribir el YAML a mano y mandarlo por la API.
  **Modelo → + Nuevo modelo** pide el nombre y **la primera tabla en el mismo paso**,
  porque un modelo sin entidades no se puede guardar y un «crear» que lo dejara vacío
  prometería algo que el servidor va a rechazar. La API acepta ahora una
  `definicion` además del `yaml`, para que la interfaz no tenga que saber serializar.

- **Buscador y grupos plegables en el panel del ETL.** «Orígenes disponibles» era una
  lista plana con subtítulos de texto suelto: con mil sesenta y cinco datasets, llegar
  a «Resultados de otras» pedía atravesarla entera con la rueda del ratón, y encontrar
  algo concreto era imposible.

  Ahora cada bloque es un **grupo plegable con su contador**, y cada uno se recuerda
  plegado —se quita de en medio una vez y se queda quitado—. Arriba hay un **buscador
  que no se desplaza**, y la cabecera dice «23 de 1,065» mientras se busca.

  La búsqueda perdona lo que la gente escribe de verdad: sin acentos (`orcamento`
  encuentra `Orçamento`), sin distinguir mayúsculas, y **por trozos en cualquier
  orden** — `oriente presu` encuentra `SUC_ORIENTE__presupuesto` sin tener que acertar
  los guiones bajos. Un grupo plegado que tenga resultados **se abre solo mientras se
  busca**, y vuelve a plegarse al limpiar: un grupo cerrado escondiendo el único
  resultado se lee como «no hay nada», que es lo contrario de lo que pasa.

  El mismo buscador está en «Proyectos», y ahí un proyecto sale si coincide su nombre
  **o el de alguna de sus secciones**: buscar `hechos_venta` lleva al proyecto que la
  tiene en vez de obligar a abrirlos uno por uno.

  El orden de los grupos **no cambia**: quien ya sabe dónde está cada cosa no tiene
  por qué volver a aprenderlo, y para quitarse un grupo de en medio ya está el
  plegado.

- **El nombre de una transformación ya se puede cambiar.** Estaba bloqueado con razón
  —el nombre es también el directorio del Parquet y el nombre con el que otras la
  leen— pero bloquearlo era correcto e inservible: dos catálogos que vienen de dos
  sistemas distintos necesitan llamarse distinto, y descubrirlo después de armar la
  transformación obligaba a rehacerla.

  Ahora se renombra de verdad: se **mueve el directorio Parquet** y se **reescriben
  los orígenes** de las transformaciones que la leen. Lo que se toca se dice después,
  con nombres: renombrar algo que otras cuatro cosas leen sin que la pantalla diga
  cuáles es pedir que se confíe a ciegas.

  Tres cosas que no hace, y por qué:

  - **No toca las versiones del modelo**, que son instantáneas inmutables a
    propósito. Si alguna nombra la tabla, el renombrado **se detiene antes de mover
    nada** y dice qué modelo es. Un tablero anclado a una versión no puede cambiar de
    significado porque alguien renombró algo.
  - **No cambia el alias** de un origen, solo su referencia. El alias es el nombre con
    el que la consulta la llama por dentro; cambiarlo rompería el SQL escrito a mano.
  - **No va dentro de «Guardar».** Guardar cambia qué calcula; renombrar mueve datos
    en disco y reescribe definiciones ajenas. Eso no puede colarse en un guardado que
    alguien pulsó para cambiar un filtro, así que tiene su propio botón.

  Un nombre ya usado por otra transformación o por un dataset se rechaza —los dos
  escribirían en el mismo sitio— y también uno que no sirva como nombre de carpeta.

- **Proyectos con secciones en el ETL.** Un proyecto agrupa transformaciones que
  corren en orden, con un solo horario. Es el equivalente a un script con secciones:
  el panel de la izquierda deja de ser una lista plana y pasa a ser
  `PROYECTO ▸ 1 series, 2 calendario, 3 hechos_venta…`, y el número de cada sección
  es el paso en el que corre.

  El problema no era de potencia sino de volumen. Un script de dieciocho secciones se
  convertía en dieciocho transformaciones sueltas más un flujo que las ordenaba:
  correcto pieza por pieza e inmanejable en conjunto — la lista no dice qué va con
  qué, y para probar una hay que ir a otra pantalla. Con cuarenta sucursales deja de
  escalar.

  **Un proyecto es un flujo restringido a transformaciones**, no un objeto nuevo con
  motor propio: comparte la tabla `flujo` y el ejecutor, y por eso hereda los
  reintentos, la cancelación entre pasos, la reanudación por identidad, el historial
  paso a paso y los avisos por correo. Un segundo motor «igual pero para proyectos»
  acabaría siendo el que se queda atrás. Consecuencias buscadas: el proyecto sale en
  Tareas, se detiene con el mismo botón, y un flujo puede llamarlo como paso —el
  maestro trae las cuarenta sucursales y después llama al proyecto que las
  transforma.

  Lo que ya existe no cambia: una transformación sin proyecto sigue funcionando y
  sigue apareciendo, ahora bajo **Sin proyecto**. No se migran solas a un proyecto de
  una sección cada una; eso convertiría doscientas transformaciones en doscientos
  proyectos y el desorden sería el mismo con otro nombre.

- **Ejecutar un tramo: de una sección al final** (`desde_paso`). Cuando la sección 12
  de dieciocho es la que se está afinando, rehacer las once anteriores son veinte
  minutos de espera por nada.

  Los pasos anteriores quedan anotados como **`no se pidió`** —ni `exito`, ni
  `omitido` por un fallo: son tres cosas distintas y el historial tiene que poder
  decir cuál fue—, y la corrida se marca **«tramo desde N»** en el panel y en el
  historial del flujo. Sin esa marca, tres pasos en verde de treinta y cinco se leen
  como «todo al día», que es justo la pantalla con la que se decide sobre un número
  que no se recalculó. Por lo mismo, un tramo que sale bien **no dispara el correo de
  «flujo recuperado»**: los pasos que fallaban pueden ser justo los que no se
  pidieron.

  Sirve igual para el maestro de las treinta y ocho extracciones, no solo para los
  proyectos.

- **Secciones intermedias.** Una sección se puede marcar como andamiaje —un mapeo de
  códigos, una tabla de series, un calendario auxiliar—. Se sigue materializando, que
  es lo que permite ejecutarla sola y ver sus filas, pero **solo se ofrece como
  origen dentro de su propio proyecto** y no ensucia las listas de datos. Con
  dieciocho secciones por sucursal, sin esta marca el catálogo se vuelve inservible
  por volumen.

### Corregido

- **El diagnóstico callaba tres problemas que frenan un modelo entero.** Salieron de
  revisar uno ya armado —catorce tablas, veintidós relaciones— cuyo diagnóstico salía
  **vacío** mientras nada de lo que se quería medir funcionaba. Un diagnóstico limpio
  sobre un modelo que no sirve es peor que ninguno: dice que todo está bien.

  - **Una dimensión con columnas de medida** (crítico). El editor sólo ofrece hechos
    en «Calcula desde», así que esas columnas no se pueden sumar — y no se ve como un
    error, se ve como que la tabla «no sale en la lista».
  - **Los dos lados de una unión con tipos distintos** (crítico). Comparar texto con
    entero no siempre falla, y cuando no falla es peor: no casa ninguna fila y la
    cifra sale vacía sin una sola señal.
  - **Una fecha guardada como texto** (aviso). Ordena mal, no se une a un calendario
    de fechas de verdad y ninguna comparación de periodos funciona encima. Se avisa
    por el nombre **y** el tipo, no sólo por el nombre.

- **La pestaña YAML enseñaba la versión publicada, no lo que tienes en el lienzo.** Y
  lo decía sólo si había cambios **sin guardar**: con el borrador ya guardado, el
  texto salía sin un solo aviso. Quien tenía trece tablas trabajadas y una publicada
  veía **una** en el YAML, y la conclusión razonable era que el YAML estaba roto.
  No lo estaba: era otro texto.

  Ahora hay **dos pestañas** —`Borrador` y `Publicada vN`— cuando existe un borrador,
  y el borrador es lo que se abre primero, que es lo que ya hacía `/definicion`. Sin
  borrador, dice que no hay ninguno en vez de callar. La ruta `/yaml` devuelve además
  `es_borrador`, así que la respuesta ya no es ambigua para quien la consuma desde
  fuera.

- **`CALCULAR` sobre una métrica que ya venía filtrada acumula la condición.** Era
  el patrón «un total con su regla, y luego los tramos de ese total»: `Inventario`
  descarta las unidades de demostración, y `Inventario de menos de 30 días` acota
  además por antigüedad. Antes eso no daba un número equivocado — fallaba, y con un
  mensaje que mentía: decía que `CALCULAR` no encontraba ninguna agregación dentro,
  habiéndola, sólo que ya envuelta en su propio `FILTER`. Ahora las condiciones se
  juntan con `Y` en un solo filtro.

- **Una columna de periodo ya no sale con separador de miles.** `202601` se leía
  como «201,601», o sea como doscientos mil y pico. Ya pasaba antes; ahora se nota
  más, porque comparar contra otro mes obliga a poner esa columna en el desglose.

- **«Tablas del motor» ya sólo trae tablas del motor.** El panel de orígenes del ETL
  metía en ese grupo **todo** lo que se puede nombrar como tabla —las del motor, las
  cargas y los resultados—, así que cada dataset y cada sección salía **dos veces**,
  con el mismo nombre, en dos grupos distintos. Medido sobre los datos de
  demostración: el grupo decía 49 y sólo **12** eran del motor; las otras 37 eran
  cargas y resultados repetidos.

  Y no era cosmético. Cada grupo crea un tipo de origen distinto: del grupo del motor
  sale uno que se lee como tabla del motor, y de los otros uno que se lee como Parquet
  **añadiéndole las etiquetas de su conexión** —`id_sucursal`, la marca—. Tomando una
  carga del grupo de arriba se creaba un origen que apunta a una tabla que no existe
  en el motor, y la transformación reventaba al ejecutarse:

  ```
  Catalog Error: Table with name SUC_ORIENTE__ventas does not exist!
  ```

  El mismo nombre tomado de «Datos cargados» funcionaba. Dos caminos con el mismo
  nombre, uno bueno y otro roto, y nada que los distinguiera mirando. El convertidor a
  SQL sí filtraba bien por procedencia; el panel no.

  La prueba que lo fija no comprueba la etiqueta —sería comprobar lo que pone el mismo
  código que se prueba—: **lee cada nombre del grupo como tabla del motor** y exige
  que se pueda. Lo que sí sigue siendo correcto es que una carga se llame igual que
  una tabla del motor y salga en los dos sitios: ahí son dos cosas distintas con el
  mismo nombre, y las dos se pueden leer. Eso es un problema de nombres, no de grupos.

- **Renombrar una columna en la transformación y que el modelo lo siga.** El botón
  «Actualizar columnas desde el origen» **no terminaba el trabajo**: añadía las
  columnas nuevas, ponía los tipos al día, y las que ya no existían las dejaba ahí.
  El aviso amarillo no se iba por más veces que se pulsara, así que el botón parecía
  roto — y no había ninguna forma de decirle que `vr_base_icms` y `monto_base` son la
  misma columna con otro nombre.

  Ahora el aviso separa dos casos que no son el mismo:

  - **Las que no usa nadie se quitan al actualizar.** Antes se quedaban «por si
    alguna relación o métrica las usa», y ese «por si» no era una respuesta:
    obligaba a repasar a mano veinticuatro relaciones y treinta métricas.
  - **Las que algo usa se nombran, con qué las usa.** «`vr_pis` — 1 relación:
    `fact_venta.vr_pis` → `cat_sucursal.sucursal_id` · la nombran 1 métrica:
    Utilidad». Esas no se tocan solas: quitar una columna con una relación encima
    rompe el modelo lejos de este botón, en la primera consulta.

  Y hay un **«es la misma, renombrada»** por columna. Al confirmarlo, la referencia
  se arrastra por los cuatro sitios donde va por nombre —el campo con su rol,
  etiqueta, «ver», PII y «única»; la clave primaria; el grano; y las relaciones—.
  Cuando hay exactamente una columna que desapareció y una candidata, se propone
  sola; con dos y dos no, porque emparejarlas al azar movería una relación de sitio
  sin que nadie lo pidiera.

  Lo que **no** se reescribe es la fórmula de una métrica: ahí el nombre es texto
  dentro de un lenguaje con variables, y cambiarlo a ciegas podría pisar una `VAR`
  que se llame igual. Se dice qué métricas lo nombran para que las arregle quien las
  escribió.

  De paso, el desplegable de «Nueva relación» ya no ofrece una columna que el origen
  no tiene. Ofrecerla era una trampa: la relación se creaba y fallaba al consultar.

  Comprobado en el navegador sobre el modelo de demostración, que tiene este desfase
  de verdad —`fact_venta` perdió cinco columnas y ganó seis—: el aviso nombra las
  cinco con sus métricas, actualizar deja 19 campos, y renombrar `vr_base_icms` a
  `monto_base` mueve la clave primaria, el grano y la relación al nombre nuevo,
  conserva el rol `medida_base` y avisa de que hay que revisar «Venta» y «Utilidad».
  Funciona igual en los dos órdenes: renombrando antes de actualizar y después.

- **El resultado de esos botones se ve aunque quede desfase.** Salía solo cuando ya
  no quedaba nada por resolver, o sea justo cuando ya no hacía falta: el aviso de
  «revisa la fórmula de Utilidad» aparece después de renombrar una columna de tres,
  con desfase pendiente, así que no se veía nunca.

- **La tabla del lienzo enseña todos sus campos, y se puede unir por cualquiera.** La
  lista de columnas tenía `max-height: 220px` con barra por dentro, así que un catálogo
  de veintidós columnas mostraba diez. Las otras doce no se podían agarrar para
  arrastrar una relación — **y arrastrar es la forma de crearla**. Y la barra tampoco
  servía: la rueda del ratón dentro de un nodo se la queda el lienzo para hacer zoom.

  Había una segunda consecuencia, más callada: el conector de un campo recortado sigue
  existiendo, pero cae fuera de la caja visible. La línea de esa relación **nacía de un
  punto donde no hay nada**.

  Ahora la lista no se recorta. Para que un catálogo largo no se coma el lienzo, la
  cabecera de cada tabla lleva un botón que la deja en **solo los campos unidos** —los
  de sus relaciones y su clave— y de vuelta; dice cuántos esconde (`+9`). En los dos
  estados **todo conector que existe se ve**, que es la propiedad que hacía falta.

  Compactar es una preferencia de la vista y **no toca el modelo**: no marca el
  borrador como sucio, no sale en el YAML y no obliga a publicar una versión. Se
  recuerda por modelo en el navegador, como el ancho de los paneles.

  Comprobado en el navegador sobre el modelo de demostración: con `fact_venta`
  compactada de 13 campos a 4, las **15** relaciones siguen naciendo y muriendo en el
  conector del campo que les toca, y ninguna queda fuera de su caja.

- **El panel de la derecha se ensancha arrastrando, como el de la izquierda.** Era fijo
  de 380px, y ahí la tabla de campos de un catálogo de veintidós columnas sale con
  «Nombre…» cortado en todas las filas: no se distingue `Nombre_Conexion` de
  `Nombre_DB`, que es justo lo que hay que leer para elegir por dónde unir dos tablas.
  Se recuerda por pantalla, y con doble clic en el borde vuelve a su ancho normal. Vale
  para los cuatro sitios donde hay panel derecho: modelo, transformar, flujos y tablero.

  De paso, el ancho de más ahora se lo lleva **el nombre del campo**. La tabla es de
  columnas fijas y la de «PII» no tenía ancho declarado, así que `table-layout: fixed`
  le daba la mitad del sitio nuevo a una casilla de trece píxeles y el nombre seguía
  saliendo cortado. Medido: a 380px, 5 de 13 nombres cortados; a 600px, **0 de 13**.

- **Una tabla nueva se coloca donde de verdad cabe.** El alto que se suponía para una
  tabla sin dibujar salía de números viejos del CSS —19px por fila— y la fila mide 23.
  En una tabla de veintidós columnas eso son casi noventa píxeles de menos, suficiente
  para que dos tablas se toquen. Ahora los números salen de medir el nodo, y se
  redondean **hacia arriba**: pasarse deja un hueco de más, quedarse corto las solapa.

- **Una tabla de MySQL que el catálogo no describe ya se puede traer.** El selector
  listaba `FACTURAS_PR`, en cualquier cliente SQL se consultaba sin problema, y
  Astrolabio contestaba «La tabla 'ventas_origen.FACTURAS_PR' no existe» — mandando a
  buscar un error de escritura que no existía.

  La causa: se concluía «no existe» de que `information_schema.columns` viniera
  vacío, y eso no es lo que significa. Esa vista filtra por privilegios columna a
  columna y además se queda vacía para una vista que MySQL no puede expandir (su
  definidor perdió permiso, o una tabla de debajo cambió de nombre). En los dos casos
  la tabla está ahí y **se puede leer**.

  Ahora se le pregunta al servidor por la vía que no miente: si hay fila en
  `information_schema.tables`, se pide la forma con un `SELECT … LIMIT 0` y se leen
  las columnas del cursor. Sin clave primaria, así que la carga será completa en vez
  de incremental — que es lo correcto con una tabla de la que no se puede saber más.
  Si tampoco se puede leer, el mensaje dice qué pasó y lo que contestó el servidor,
  en vez de culpar al nombre. Y cuando de verdad no hay fila, se nombra la otra causa
  frecuente: sin permiso de lectura, para Astrolabio no existe.

- **Encadenar flujos: un flujo puede ser el paso de otro.** Con el `+` de la lista
  de flujos se pone uno entero como paso del que se está editando, y así uno
  empieza cuando el anterior termina.

  Era lo único que no se podía decir con horarios. No se sabe cuánto tarda cada
  sucursal, y cuarenta crones a las 6:00 no las ponen en fila: las ponen a
  pelearse por el mismo Pervasive. Un maestro que llame a los cuarenta lo dice
  exacto y lleva un solo horario.

  Cada eslabón corre entero —con sus reintentos y su regla al fallar— y deja su
  propia entrada en su propio historial; en el maestro solo queda el resumen
  («28 pasos · 1,204,331 filas»). Un hijo que falla detiene al maestro.

  Los **ciclos** se rechazan al guardar, directos e indirectos, y hay una segunda
  comprobación al correr por si entre guardar y correr las cosas cambiaron: un
  ciclo no daría un error visible, daría un servidor dando vueltas de madrugada.
  El anidamiento se corta a cinco niveles. *Ordenar solo* deja los pasos de tipo
  flujo donde están y lo dice, en vez de borrarlos en silencio.

- **Detener un flujo que ya arrancó**, con el botón «Detener» en Flujos y en el
  aviso de Tareas. Antes solo se podía sacar de la cola algo que no había empezado:
  una cadena de treinta y ocho extractores lanzada a la una de la tarde no había
  forma de pararla.

  **Se detiene entre pasos, nunca a media tabla.** La que se está trayendo termina y
  los pasos que faltan quedan como `cancelado`. No es prudencia de más: el destino se
  borra ANTES de escribir, así que una recarga completa cortada en el momento justo
  dejaría el dataset vacío. En un maestro se propaga al hijo que esté corriendo.

  Estado nuevo `cancelado` (migración 0009) en vez de reutilizar `error`: en la
  pantalla sale en gris y **no dispara el aviso de fallo**. Un correo de alarma por
  algo que acaba de hacer quien opera es la forma de que esos correos se dejen de
  leer. Hay filtro «Detenidos» en Tareas.

  Una carga suelta no se puede detener y se dice por qué: no tiene pasos donde
  pararse. `DELETE /api/flujos/cola/{id}` ahora contesta 200 con `estado`
  (`sacado` | `parando`) y un mensaje, o 409 explicando por qué no.

- **Continuar una corrida detenida o fallida**, desde su renglón del historial.
  Salta los pasos que ya salieron bien —quedan como `saltado`, que no es `exito`— y
  corre los demás. Nueva ruta `POST /api/flujos/{id}/reanudar/{ejecucion_id}` y
  migración `0010` con la cadena `reanuda_a_id` / `reanudada_por_id`.

  **Las transformaciones se rehacen siempre.** Continuar mezcla dos momentos, y una
  transformación que ya corrió con los datos viejos se quedaría rancia mientras sus
  orígenes se actualizan. Rehacerla cuesta poco: lee Parquet local.

  Los pasos se reconocen por `(tipo, id)` y no por su posición —el flujo puede
  haberse editado entre pausar y continuar—, así que el detalle del historial ahora
  guarda el `id` de cada paso. Un paso sin `id` (corridas anteriores) **no se salta**:
  ante la duda se repite trabajo, que es gratis, en vez de saltarse una tabla.

  Sirve también para las **fallidas**, que es el caso frecuente. En un maestro,
  continuar re-entra en el hijo que se quedó a medias y él se salta lo suyo: reanudar
  38 × 28 no vuelve a traer 1.064 tablas. Solo cuentan las corridas de los hijos
  posteriores a la que se está continuando, para no fiarse de una que alguien paró
  aparte la semana pasada.

  Una corrida se continúa **una sola vez**; el segundo intento dice cuál la retomó.
  La antigüedad de lo completado se muestra y no se prohíbe: un límite en horas sería
  un número inventado.

- **Se rastrea quién dispara a quién.** La lista de flujos trae `llamado_por`, y con
  eso la pantalla de tareas dejó de decir «a mano» de los treinta y ocho extractores
  que en realidad llama el maestro cada noche: dice *dentro de «X»*, y si además
  tienen horario propio, las dos cosas, porque entonces corren dos veces. El filtro
  *Sin horario* ya no los cuenta.

  Las corridas que dispara un flujo se guardan con `origen = "flujo"` y el nombre de
  quien llamó en el detalle, así que el historial del hijo dice *desde «X»* en vez de
  *manual*.

- **El horario se elige por partes, y la zona se elige.** Cada cuánto, a qué hora en
  a. m./p. m., y en qué zona; el cron se genera y sigue a la vista para los casos que
  solo se pueden decir así. Al escribir un cron que no encaja en las formas
  conocidas, el selector pasa a *Avanzado* en vez de mentir sobre lo guardado.

  La zona estaba fija en `America/Mexico_City` —el valor por omisión de la base— sin
  forma de cambiarla desde la interfaz. Ahora hay una lista con las once de México
  por su nombre de a pie y el resto del mundo debajo; un horario nuevo parte de la
  zona del navegador. El mismo selector se usa en flujos y en datasets.

- **Editar una conexión** (`PATCH /api/conexiones/{id}`) y probar el cambio sin
  guardarlo (`POST /api/conexiones/{id}/probar-cambio`). Antes, rotar una
  contraseña obligaba a borrar la conexión y volver a crearla, y con ella se iban
  en cascada todos sus datasets: su historial, sus horarios y sus columnas
  elegidas.

  Un secreto que llega vacío **conserva el guardado**; para quitarlo hay que
  nombrarlo en `borrar_secretos`. La interfaz manda solo los campos que se
  tocaron, porque la API no puede devolver las contraseñas y enmascara la cadena
  de ODBC: reenviar el formulario entero guardaría la máscara.

  El tipo y el perfil de ODBC quedan fijos: cambiarlos sería otra conexión.

- **La interfaz se compila dentro de Docker.** Antes `docker compose` esperaba
  encontrar `frontend/dist` ya compilado en el disco, así que el servidor
  necesitaba Node además de Docker. Ahora hay una etapa de construcción que se
  descarta y la imagen final solo lleva Caddy y los archivos estáticos.
- **El cliente ODBC de Actian Zen / Pervasive se instala solo en la imagen.** Se
  deja el paquete de Linux en `backend/drivers/` y `docker compose build` lo
  instala, localiza `libodbcci.so` y lo registra en `/etc/odbcinst.ini` como
  `Actian Zen ODBC Interface` — el nombre que la pantalla de conexiones
  preselecciona sola.

  Sin paquete la imagen se construye igual, sin ese driver. **Con paquete y algo
  mal, la construcción falla**: una imagen que se construye «bien» y se queda sin
  el driver que se pidió es la forma de descubrir el problema tres semanas
  después, de madrugada, en una carga que no corre.

  El binario no se puede redistribuir, así que `backend/drivers/` está en
  `.gitignore` salvo su README.
- **Instrucciones para un servidor Windows**, con Docker Desktop sobre WSL 2:
  cómo generar las claves sin `openssl`, arranque automático, respaldo desde el
  volumen, finales de línea, cómo salir del error `no matching manifest for
  windows(...)` —Docker en modo contenedores de Windows—, y por qué **un driver
  ODBC de Windows no se puede cargar dentro de un contenedor Linux**.
- **Instalación nativa en Windows Server**, con NSSM como servicio, Caddy delante,
  los DSN de 64 bits y el respaldo por el Programador de tareas. Es la salida para
  **Windows Server 2019**, donde no hay contenedores Linux —WSL 2 pide compilación
  19041+, Docker Desktop no se soporta en Server y LCOW está descontinuado— y
  además es la única donde el driver ODBC de Pervasive carga de verdad.
- **Las pruebas corren también en `windows-latest`.** Hay instalaciones que van a
  vivir en Windows Server; que funcione ahí tiene que estar probado, no supuesto.
- Las claves de producción se generan con **PowerShell puro**, sin `openssl` y sin
  Docker. Las instrucciones anteriores usaban un contenedor, que es justo lo que
  no arranca cuando Docker está en el modo equivocado.

### Arreglado

- **Las líneas del lienzo daban la vuelta al modelo entero.** Cada columna tiene el
  conector de origen a la derecha y el de destino a la izquierda, y la línea se
  dibujaba siempre en el sentido de la relación. Así que una relación cuyo destino
  quedaba a la **izquierda** obligaba a la curva a salir por la derecha, cruzar el
  lienzo, y volver a entrar por la izquierda —pasando por dentro de las dos tablas—.
  Con dos tablas se disimula; con veinte relaciones el lienzo se vuelve una madeja y
  no se puede seguir ninguna. El trazo de una de ellas iba de `x=809` a `x=1`
  **pasando por `x=986` y por `x=-176`**.

  Ahora la línea se dibuja siempre de la tabla de la izquierda a la de la derecha,
  por las caras que se miran, sea cual sea el sentido de la relación. Invertir el
  dibujo no cambia nada de lo que se guarda: `desde` → `hasta` sigue igual, y de ahí
  salen la cardinalidad y el SQL. La misma línea ahora va de `x=189` a `x=621` sin
  salirse de ese tramo.

  Y cuando las dos tablas **se solapan horizontalmente** no hay orientación que
  evite el retroceso —una curva que retrocede se enrosca sobre sí misma—, así que
  esas usan **ruta ortogonal**: rodean en ángulo recto. En el modelo de
  demostración son 3 de 15.

- **Pegar SQL suponía que toda tabla nombrada era del motor analítico.** `FROM
  cat_zonas` creaba un origen de tipo `tabla` sin comprobar que existiera, y la
  consulta moría con un `Catalog Error: Table with name cat_zonas does not
  exist! Did you mean "information_schema.constraint_column_usage"?` — que culpa a
  la tabla y no dice lo único útil.

  Ahora el nombre se resuelve contra lo que hay: tabla del motor, dataset ya
  cargado, resultado de otra transformación, o una tabla que llegó de varias
  conexiones. Así `SELECT * FROM MI_SUCURSAL__ventas` funciona sin que nadie sepa
  que detrás hay Parquet. Si el nombre no existe se dice en claro, con la sugerencia
  más parecida, y **no se crea un origen roto** que falle más adelante.

  En modo SQL, una tabla que no esté entre los orígenes da el mismo mensaje útil en
  vez de dejar que DuckDB conteste por su cuenta.

- **En «Elegir columnas» solo se podía marcar una.** Los cuadros de cada paso se
  dibujaban con las columnas que devolvía la vista previa, que son las de la
  **salida** de la cadena completa. Al marcar la primera, la salida pasaba a tener
  una sola columna y el propio paso se quedaba con un solo cuadro: imposible marcar
  la segunda. Cualquier paso colocado después de un «Agrupar y resumir» tenía el
  mismo problema.

  Ahora cada paso ofrece las columnas que le **entran**: las del origen después de
  los pasos anteriores, simuladas en el navegador para no ir al servidor por cada
  clic. La simulación es conservadora: cuando un paso puede traer columnas que desde
  la interfaz no se conocen —unir sin decir cuáles traer, apilar— no quita ninguna.
  Para la salida real sigue mandando la vista previa, que la calcula el compilador.

- **En una instalación nueva, el motor analítico no existía y nada podía leerlo.**
  `duckdb_solo_lectura` es `True` por omisión —y debe serlo, la API no escribe en el
  motor, escribe Parquet— pero **en solo lectura DuckDB no crea el archivo que le
  falta**. Si nunca se sembraron los datos de demostración, ese archivo no existía
  nunca, y el ETL, los tableros y el modelo fallaban con:

      IO Error: Cannot open database "...analitico.duckdb" in read-only mode:
      database does not exist

  Ahora el arranque lo crea vacío si falta. `duckdb_tables()` sobre una base vacía
  devuelve cero filas, que es la verdad: todavía no hay tablas en el motor.

- **El panel de orígenes del ETL se quedaba vacío y callado.** `GET
  /api/transformaciones/origenes` calculaba todo en una sola expresión: si
  `ruta_datos_dataset` lanzaba por **un** nombre con un carácter que no sirve para
  nombrar un origen, la petición contestaba 500 y la pantalla mostraba el panel
  vacío sin decir nada. Con mil sesenta y cinco datasets, uno raro dejaba sin poder
  transformar nada.

  Ahora cada bloque se calcula por separado, lo que no se puede usar sale marcado y
  con su motivo en `avisos`, y la pantalla distingue las tres situaciones que antes
  se veían igual: *leyendo*, *no se pudo leer* y *todavía no hay nada*.

  De paso, la comprobación de «¿tiene datos?» se hace una vez por dataset y no dos
  —recorre directorios, y con mil sesenta y cinco se nota—.

- **Una prueba armaba JSON pegando una ruta con una f-string** y en Windows eso
  produce JSON inválido: `C:\Users` lleva un `\U` que no es un escape válido.
  En Linux colaba porque las rutas no tienen barras invertidas. Lo encontró el
  trabajo de integración continua en Windows el mismo día que se añadió, que era
  exactamente para lo que estaba.

- **El guion de Windows ya no imprime las claves en pantalla.** Parecía servicial
  y era un error: la consola queda en el historial, en las capturas y en el texto
  que uno pega para pedir ayuda. Ahora van a `CLAVES-GENERADAS.txt` con permisos
  solo para administradores, y el guion pide que se guarden y se borre el archivo.
  Hay `-RotarClaveCifrado` para el caso en que una se haya visto igual.

- **`backend/administrar.py`**: `listar-usuarios` y `restablecer <correo>`.
  La contraseña del primer administrador solo se escribe en el registro del
  primer arranque; si ese registro se perdió, no había forma de entrar y la
  única salida era borrar la base de metadatos, que se lleva por delante todo lo
  demás.

### Cambiado

- `api` ya solo escucha en `127.0.0.1:8000`. Quien entra de fuera pasa por Caddy,
  que es el que lleva HTTPS y las cabeceras de seguridad.
- Se quitó la referencia a un `docker-compose.prod.yml` que no existía: la
  diferencia entre desarrollo y producción es el `.env`, no un compose distinto.

Lo que falta y está decidido que se hará: más conectores nativos (PostgreSQL,
SQL Server, SQLite), una barra de selecciones con atrás y adelante, y que el fin de
un flujo dispare otro flujo. La lista completa vive al final de cada documento de
fase.

## [0.1.0] — 2026-08-05

Primera versión pública. El recorrido completo funciona: conectar, transformar,
modelar y publicar, con **296 pruebas** automatizadas.

### Datos

- Conectores de **MySQL/MariaDB**, **archivos** (CSV, Excel, Parquet, y los `.xls`
  que en realidad son HTML) y **ODBC**, con perfiles por origen que arman la cadena
  de conexión y detectan qué drivers hay instalados.
- Ingesta a **Parquet particionado** por año y mes, con carga completa, incremental
  y recarga de particiones.
- **Ventanas móviles** de recarga (`el mes en curso`, `los últimos 2 años`,
  `ultimos_dias:N`…), resueltas en el momento de correr y en la zona horaria del
  dataset.
- **Elegir columnas**, con `null` = todas para que las columnas nuevas del origen
  lleguen solas.
- Los tipos los declara el origen, no se deducen de los datos.
- Se prueba la conexión **antes** de guardarla, y cualquier cambio invalida la
  prueba anterior.

### Transformar

- Pasos visuales (filtrar, unir, agrupar, derivar, apilar, ordenar…) y **SQL
  pegado**, con conversión de SQL a pasos que se niega a adivinar.
- **Conteo de filas por paso**, que es lo que convierte un «no cuadra» en «se
  pierde en el paso 3».
- La base analítica se abre en **solo lectura**; el resultado se escribe a un
  temporal y después se reemplaza.

### Modelo

- Lienzo de entidades y relaciones, métricas definidas una sola vez, y versiones
  inmutables a las que los tableros quedan anclados.
- Diagnóstico de **fan traps, rutas ambiguas y tablas huérfanas**. Ante una ruta
  ambigua el motor **pregunta** en vez de elegir.

### Tableros

- KPI, barras, líneas, pastel y tabla; **filtros asociativos** al estilo Qlik.
- Exportación a Excel y CSV **con el contexto** de la consulta.

### Gobierno

- Tres roles, **seguridad por fila** que también filtra los totales y falla cerrado,
  **simulador** para ver como otro usuario, y auditoría que no se puede borrar.

### Avisos

- Reglas por **correo** o **webhook** (Teams, Slack) cuando una carga o un flujo
  falla, con silencio entre repeticiones, aviso al recuperarse, registro de cada
  intento y un botón para probar el canal.

### Seguridad

- Contraseñas con Argon2, credenciales de conexión cifradas con Fernet, y **freno
  a la fuerza bruta** por cuenta.
- El arranque en producción falla si faltan las claves o son débiles.
- Webhooks a direcciones internas bloqueados por defecto; a las de enlace local,
  siempre.
- Dependencias fijas y auditadas: `pip-audit` sin hallazgos.
