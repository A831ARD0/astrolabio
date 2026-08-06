"""
El puente ODBC de 32 bits.

Un proceso de 64 bits no puede cargar una libreria de 32, y al reves tampoco: no
es una limitacion de Windows ni de Python, es que son formatos de binario
distintos. Cuando el driver ODBC del origen solo existe de 32 bits —y no se puede
cambiar porque otra aplicacion depende de el— la unica salida es que el driver lo
cargue **otro proceso**, de 32 bits, y que Astrolabio le hable por la red local.

Eso es esto. `servidor` corre en el interprete de 32 bits y es el unico que toca
pyodbc de verdad; `app.conectores.puente` es el cliente, y devuelve objetos que se
comportan como los de pyodbc para que el conector ODBC no se entere de nada.

`protocolo` es lo unico que comparten, y por eso no importa nada de `app`: en el
lado de 32 bits solo hay pyodbc instalado, ni pyarrow ni duckdb, que no tienen
ruedas de 32 bits desde hace anos.
"""
