/// <reference types="cypress" />

describe('OpenViper Admin Flow', () => {
    const adminUser = {
        username: 'admin',
        password: 'admin123',
    }

    beforeEach(() => {
        // Note: session/cookies are cleared between tests by default in Cypress 10+
    })

    it('performs full authentication and navigation flow', () => {
        // 1. Login
        cy.visit('/admin/login')
        cy.get('#username').type(adminUser.username)
        cy.get('#password').type(adminUser.password)
        cy.get('button[type="submit"]').click()

        // 2. Verify Dashboard
        cy.url().should('include', '/dashboard')
        cy.contains('Dashboard').should('be.visible')
        cy.contains('Recent Activity').should('be.visible')

        // 3. Navigate to Users model
        // Use .sidebar-link to avoid matching the app label header
        cy.get('.sidebar-link').contains('Users').click()
        cy.url().should('include', '/users/User')
        cy.get('h1').should('contain', 'Users')

        // 4. Verify user list contains our admin
        cy.get('table').contains('admin').should('be.visible')

        // 5. Navigate to Posts model
        cy.get('.sidebar-link').contains('Posts').click()
        cy.url().should('include', '/posts/Post')
        cy.get('h1').should('contain', 'Posts')

        // 6. Test search functionality if possible
        cy.get('input[placeholder*="Search"]').first().type('test-search-query').clear()

        // 7. Test Theme Toggle
        cy.get('[data-testid="theme-toggle"]').click()
        // Should toggle class on html/body or just check it happened via store (implicit)

        // 8. Logout
        cy.logout() // Uses our custom command with data-testid
        cy.url().should('include', '/login')
    })

    it('redirects unauthenticated users to login', () => {
        cy.visit('/admin/dashboard')
        cy.url().should('include', '/login')
    })
})
