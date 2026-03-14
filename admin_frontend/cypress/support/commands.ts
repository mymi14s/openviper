/// <reference types="cypress" />

// Custom commands for OpenViper Admin testing

declare global {
  namespace Cypress {
    interface Chainable {
      /**
       * Custom command to login to admin panel
       * @example cy.login('admin', 'password')
       */
      login(username: string, password: string): Chainable<void>

      /**
       * Custom command to logout from admin panel
       */
      logout(): Chainable<void>

      /**
       * Custom command to navigate to a model list
       * @example cy.navigateToModel('blog', 'Blog')
       */
      navigateToModel(appLabel: string, modelName: string): Chainable<void>

      /**
       * Get element by data-testid attribute
       */
      getByTestId(testId: string): Chainable<JQuery<HTMLElement>>
    }
  }
}

// Login command
Cypress.Commands.add('login', (username: string, password: string) => {
  cy.visit('/admin/login')
  cy.get('#username').type(username)
  cy.get('#password').type(password)
  cy.get('button[type="submit"]').click()
  cy.url().should('include', '/dashboard')
})

// Logout command
Cypress.Commands.add('logout', () => {
  // Click user menu and logout
  // Using force: true as sometimes header elements might be considered obscured by transitions
  cy.get('[data-testid="user-menu"]').click({ force: true })
  cy.get('[data-testid="logout-button"]').should('be.visible').click()
  cy.url().should('include', '/admin/login')
})

// Navigate to model
Cypress.Commands.add('navigateToModel', (appLabel: string, modelName: string) => {
  cy.get('.sidebar').contains(modelName).click()
  cy.url().should('include', `/${appLabel}/${modelName}`)
})

// Get by test id
Cypress.Commands.add('getByTestId', (testId: string) => {
  return cy.get(`[data-testid="${testId}"]`)
})

export { }
