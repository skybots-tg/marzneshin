module.exports = {
    root: true,
    env: { browser: true, es2020: true },
    extends: ['eslint:recommended', 'plugin:@typescript-eslint/recommended', 'plugin:react-hooks/recommended', 'plugin:storybook/recommended'],
    ignorePatterns: ['dist', '.eslintrc.cjs'],
    parser: '@typescript-eslint/parser',
    plugins: ['eslint-plugin-react-compiler', 'react-refresh'],
    rules: {
        'react-compiler/react-compiler': "off",
        '@typescript-eslint/unused-disable-directives': ['off'],
        '@typescript-eslint/ban-ts-comment': ['off'],
        '@typescript-eslint/no-explicit-any': ['off'],
        'react-refresh/only-export-components': ['off'],
        // Подчёркивание спереди — принятый в этом коде способ сказать
        // «значение нужно по форме, а не по сути»: распакованный, но не
        // нужный элемент кортежа, обязательный аргумент колбэка.
        '@typescript-eslint/no-unused-vars': ['error', {
            argsIgnorePattern: '^_',
            varsIgnorePattern: '^_',
            caughtErrorsIgnorePattern: '^_',
            destructuredArrayIgnorePattern: '^_',
        }],
    },
};
