/**
 * Contraseñas generadas para dárselas a alguien.
 *
 * Están pensadas para dictarse o copiarse, no para memorizarse: en cuanto la
 * persona entra, la cambia. De ahí dos decisiones:
 *
 * - **Sin caracteres que se confunden** al leerlos en voz alta o en pantalla: ni
 *   0/O, ni 1/l/I. Una contraseña temporal que falla por un 0 que era una O
 *   termina en una segunda llamada y, a menudo, en un bloqueo por intentos.
 * - **En tres grupos de cuatro** (`Kp7m-Qx3r-Tz9w`), que se leen y se dictan sin
 *   perder el sitio. Doce caracteres de un alfabeto de 56 son unos 70 bits: más
 *   que de sobra para algo que vive minutos.
 *
 * `crypto.getRandomValues`, no `Math.random`, y con rechazo de los bytes que
 * sesgarían el reparto: 256 no es múltiplo de 56, y tomar el resto sin más haría
 * que los primeros caracteres salieran más.
 */

const ALFABETO = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789'
const TOPE = 256 - (256 % ALFABETO.length)

function caracter(): string {
  const b = new Uint8Array(1)
  for (;;) {
    crypto.getRandomValues(b)
    const n = b[0]!
    if (n < TOPE) return ALFABETO.charAt(n % ALFABETO.length)
  }
}

export function generarContrasena(grupos = 3, largo = 4): string {
  return Array.from({ length: grupos }, () =>
    Array.from({ length: largo }, caracter).join(''),
  ).join('-')
}
