/// <reference types="vite/client" />

// Importar un .css por su efecto (inyectarlo) no tiene tipos propios. TS 7 lo
// exige explicito.
declare module '*.css'
