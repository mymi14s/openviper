// ***********************************************************
// This file is processed and loaded automatically before your test files.
// You can read more here:
// https://on.cypress.io/configuration
// ***********************************************************

import './commands'

// Prevent TypeScript from reading file as legacy script
export {}

// Global before each hook
beforeEach(() => {
  // Clear local storage before each test
  cy.window().then((win) => {
    win.localStorage.clear()
  })
})

// Handle uncaught exceptions
Cypress.on('uncaught:exception', (err, runnable) => {
  // Returning false here prevents Cypress from failing the test
  // This is useful for handling third-party errors
  console.log('Uncaught exception:', err.message)
  return false
})
