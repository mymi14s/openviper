/// <reference types="cypress" />

/**
 * OpenViper Admin Panel E2E Tests
 * Covers core flows: Auth, Navigation, CRUD, and Dashboard.
 */

describe('OpenViper Admin Panel', () => {
  const adminUser = {
    username: 'admin',
    password: 'admin123',
  }

  beforeEach(() => {
    cy.clearCookies()
    cy.clearLocalStorage()
  })

  describe('Authentication', () => {
    it('redirects to login when unauthenticated', () => {
      cy.visit('/admin/dashboard')
      cy.url().should('include', '/login')
    })

    it('shows error on invalid login', () => {
      cy.visit('/admin/login')
      cy.get('#username').type('wrong')
      cy.get('#password').type('wrong')
      cy.get('button[type="submit"]').click()
      // Wait for loading to finish and error to appear
      cy.contains(/Invalid|failed/i, { timeout: 15000 }).should('be.visible')
    })

    it('logs in successfully with valid credentials', () => {
      cy.login(adminUser.username, adminUser.password)
      cy.url().should('include', '/dashboard')
      cy.contains('Dashboard').should('be.visible')
    })
  })

  describe('Core Admin Flows', () => {
    beforeEach(() => {
      cy.login(adminUser.username, adminUser.password)
    })

    it.skip('navigates through the sidebar', () => {
      cy.get('aside').should('be.visible')
      // Navigate to Blogs (assuming 'Blog' app exists in mock/test data)
      cy.get('aside').contains('Blogs').click()
      cy.url().should('include', '/blog/Blog')
      cy.get('h1').should('contain', 'Blogs')
    })

    it.skip('performs basic search in model list', () => {
      cy.get('aside').contains('Blogs').click()
      cy.get('input[placeholder*="Search"]').type('test{enter}')
      // Verify URL or state change if possible
      cy.url().should('include', 'search=test')
    })

    it.skip('navigates to create form', () => {
      cy.get('aside').contains('Blogs').click()
      cy.contains('button', 'Add').click()
      cy.url().should('include', '/add')
      cy.get('form').should('be.visible')
    })

    it('displays dashboard widgets', () => {
      cy.visit('/admin/dashboard')
      cy.contains('Total Models').should('be.visible')
      cy.contains('Recent Activity').should('be.visible')
    })
  })
})
