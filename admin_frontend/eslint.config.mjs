import js from '@eslint/js';
import ts from 'typescript-eslint';
import vue from 'eslint-plugin-vue';
import globals from 'globals';

export default ts.config(
    js.configs.recommended,
    ...ts.configs.recommended,
    ...vue.configs['flat/essential'],
    {
        files: ['*.vue', '**/*.vue', '**/*.ts', '**/*.js'],
        languageOptions: {
            globals: {
                ...globals.browser,
                ...globals.node,
                vi: 'readonly',
            },
            parserOptions: {
                parser: ts.parser,
            },
            sourceType: 'module',
        },
    },
    {
        rules: {
            'no-unused-vars': 'off',
            '@typescript-eslint/no-unused-vars': ['warn', { argsIgnorePattern: '^_' }],
            'vue/multi-word-component-names': 'off',
            'no-console': 'off',
            '@typescript-eslint/no-explicit-any': 'off',
            '@typescript-eslint/no-empty-object-type': 'off',
            '@typescript-eslint/no-unused-expressions': 'off',
        },
    },
    {
        ignores: ['dist/**', 'node_modules/**', 'cypress/**'],
    }
);
