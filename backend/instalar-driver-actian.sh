#!/bin/sh
# Instala el cliente ODBC de Actian Zen / Pervasive PSQL dentro de la imagen, si
# hay un paquete en `backend/drivers/`.
#
# Por que no se descarga: el cliente es licenciado y no tiene descarga publica.
# Lo consigue sistemas del portal de Actian y lo deja en esa carpeta, que esta en
# .gitignore precisamente para que un binario licenciado no acabe en un
# repositorio publico.
#
# Sin paquete, esto NO falla: la imagen se construye igual y sin driver de
# Pervasive. Es lo que se quiere mientras la licencia no llega.
#
# Con paquete y algo mal, esto SI falla, y a proposito. Una imagen que se
# construye "bien" y se queda sin el driver que se pidio es la forma de descubrir
# el problema tres semanas despues, de madrugada, en una carga que no corre.

set -eu

CARPETA=/tmp/drivers
ODBCINST=/etc/odbcinst.ini
# El nombre con el que quedara registrado. Tiene que casar con los patrones de
# `app/conectores/perfiles_odbc.py` para que la pantalla lo preseleccione sola.
NOMBRE="Actian Zen ODBC Interface"

paquetes() {
    find "$CARPETA" -maxdepth 2 -type f \
        \( -name '*.deb' -o -name '*.tar.gz' -o -name '*.tgz' \) 2>/dev/null
}

if [ -z "$(paquetes)" ]; then
    echo "→ Sin cliente de Actian en backend/drivers/: la imagen queda sin driver"
    echo "  de Pervasive. Los demas conectores funcionan igual."
    exit 0
fi

echo "→ Cliente de Actian encontrado. Instalando."

# Lo que el cliente de Zen necesita en Debian y no trae la imagen base. Se
# instala lo que exista y no se exige nada: los nombres cambian entre versiones
# de Debian —`libaio1` paso a llamarse `libaio1t64` en trixie— y quedarse sin
# construir por el nombre de una libreria de apoyo seria absurdo. Si de verdad
# falta alguna, se vera al cargar el driver, con un error que la nombra.
apt-get update
for libreria in libaio1t64 libaio1 libncurses6 libncurses5 libstdc++6; do
    if apt-get install -y --no-install-recommends "$libreria" 2>/dev/null; then
        echo "  · $libreria"
    fi
done
rm -rf /var/lib/apt/lists/*

for paquete in $(paquetes); do
    case "$paquete" in
        *.deb)
            echo "  · paquete .deb: $paquete"
            apt-get install -y --no-install-recommends "$paquete"
            ;;
        *.tar.gz|*.tgz)
            echo "  · tarball: $paquete"
            mkdir -p /opt/actianzen
            tar -xzf "$paquete" -C /opt/actianzen
            # El tarball del cliente trae un instalador propio. Si esta, manda el
            # del fabricante: sabe donde va cada cosa mejor que este guion.
            instalador=$(find /opt/actianzen -maxdepth 3 -name 'install*.sh' \
                         -type f 2>/dev/null | head -n1)
            if [ -n "$instalador" ]; then
                echo "    instalador del fabricante: $instalador"
                chmod +x "$instalador"
                # Sin terminal interactiva. Si el instalador la exige, cae al
                # camino de abajo: la libreria ya esta extraida del tarball.
                (cd "$(dirname "$instalador")" && sh "$(basename "$instalador")" </dev/null) \
                    || echo "    el instalador no acabo solo; se usa la libreria extraida"
            fi
            ;;
    esac
done

# La libreria del driver, este donde este: la deja el .deb en /usr/local/actianzen
# o el tarball donde se haya extraido.
DRIVER=$(find /opt/actianzen /usr/local /usr/lib -name 'libodbcci.so*' -type f \
         2>/dev/null | head -n1)

if [ -z "$DRIVER" ]; then
    echo "✗ Habia un paquete en backend/drivers/ pero no aparece 'libodbcci.so'."
    echo "  Comprueba que es el CLIENTE de Linux de 64 bits (no el de Windows, no"
    echo "  el servidor). Si el tarball necesita el instalador interactivo,"
    echo "  extraelo a mano y deja el .so en backend/drivers/lib/."
    exit 1
fi

echo "  · driver: $DRIVER"

cat >> "$ODBCINST" <<FIN

[$NOMBRE]
Description = Actian Zen / Pervasive PSQL
Driver      = $DRIVER
Setup       = $DRIVER
Threading   = 1
FIN

# Zen busca sus propias librerias junto al driver.
echo "$(dirname "$DRIVER")" > /etc/ld.so.conf.d/actianzen.conf
ldconfig

rm -rf /tmp/drivers
echo "✓ Registrado como «$NOMBRE»."
