// src/test/setup.ts
// Configurare globală pentru toate testele frontend.
// Importăm matchers @testing-library/jest-dom care extind expect():
//   expect(element).toBeInTheDocument()
//   expect(element).toHaveTextContent('...')
//   expect(element).toBeDisabled()
//   etc.
import '@testing-library/jest-dom'

// Suprimăm erorile React din consolă în teste.
// React loghează intern erorile din Error Boundary înainte ca spy-ul
// din test să poată intercepta — facem asta global.
const originalError = console.error.bind(console)
console.error = (...args: unknown[]) => {
  const msg = typeof args[0] === 'string' ? args[0] : ''
  // Ignorăm mesajele interne React și cele din teste intenționate
  if (
    msg.includes('Warning:') ||
    msg.includes('Error: Uncaught') ||
    msg.includes('The above error') ||
    msg.includes('act(')
  ) return
  originalError(...args)
}
