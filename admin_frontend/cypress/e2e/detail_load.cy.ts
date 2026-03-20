/// <reference types="cypress" />

describe('ModelEdit loads without refresh', () => {
  before(() => {
    // Login via API and store token
    cy.request('POST', '/admin/api/auth/login/', {
      username: 'admin',
      password: 'admin',
    }).then((resp) => {
      window.localStorage.setItem('auth_token', resp.body.access_token)
      // Also store full auth state if the app uses a Pinia store persisted to localStorage
      window.localStorage.setItem('auth', JSON.stringify({
        token: resp.body.access_token,
        user: resp.body.user,
      }))
    })
  })

  it('navigates from list to detail and content loads without refresh', () => {
    // Visit the product list
    cy.visit('/admin/products/product')

    // Wait for the table to have rows
    cy.get('table tbody tr', { timeout: 10000 }).should('have.length.greaterThan', 0)

    // Click the first row
    cy.get('table tbody tr').first().click()

    // URL should change to detail view
    cy.url({ timeout: 5000 }).should('match', /\/products\/product\/[^/]+$/)

    // The form should render — look for a Save Changes button or field input
    // NOT the spinner or "Item not found"
    cy.get('[data-testid="not-found"], .card p', { timeout: 10000 }).should('not.exist')
    cy.contains('Save Changes', { timeout: 10000 }).should('be.visible')
  })
})
