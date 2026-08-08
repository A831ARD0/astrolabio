/**
 * Buscar por nombre en las listas del panel.
 *
 * Con mil sesenta y cinco datasets llamados `SUC_SUR__Orcamento_Produtos`, teclear
 * el nombre exacto no es una opción, así que la comparación perdona lo que la gente
 * escribe de verdad:
 *
 * - **Sin acentos.** Quien busca `orcamento` tiene que encontrar `Orçamento`.
 * - **Sin distinguir mayúsculas.** `norte` encuentra `SUC_NORTE__ventas`.
 * - **Por trozos, en cualquier orden.** `norte ventas` encuentra
 *   `SUC_NORTE__ventas` sin tener que acertar los guiones bajos ni el orden.
 */
export function coincide(nombre: string, busca: string): boolean {
  const objetivo = normaliza(nombre)
  return normaliza(busca).split(/\s+/).filter(Boolean)
    .every((trozo) => objetivo.includes(trozo))
}

function normaliza(s: string): string {
  return s.normalize('NFD').replace(/\p{Diacritic}/gu, '').toLowerCase()
}
