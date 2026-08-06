# La interfaz se compila DENTRO de Docker y sale servida por Caddy.
#
# Antes el `docker compose` esperaba encontrar `frontend/dist` ya compilado en el
# disco, asi que el servidor necesitaba Node instalado ademas de Docker. En un
# servidor Windows eso es una dependencia de mas para nada: aqui la compilacion
# ocurre en una etapa que se tira, y la imagen final solo lleva Caddy y los
# archivos estaticos.

FROM node:20-alpine AS compilar
WORKDIR /app
# Primero el manifiesto: mientras las dependencias no cambien, esta capa se
# reutiliza y `npm ci` no vuelve a correr.
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM caddy:2-alpine
# El Caddyfile NO se copia: va montado desde el disco para poder cambiar el
# dominio sin reconstruir la imagen.
COPY --from=compilar /app/dist /srv
