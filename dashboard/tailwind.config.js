import tailwindcssAnimate from 'tailwindcss-animate';
import tailwindcssForm from '@tailwindcss/forms';
import tailwindcssAspectRatio from '@tailwindcss/aspect-ratio';
import tailwindcssTypography from '@tailwindcss/typography';
import { nextui } from '@nextui-org/react'

/** @type {import('tailwindcss').Config} */
const config = {
    darkMode: ["class"],
    content: [
        './pages/**/*.{ts,tsx}',
        './components/**/*.{ts,tsx}',
        './app/**/*.{ts,tsx}',
        './src/**/*.{ts,tsx}',
        "./node_modules/@nextui-org/theme/dist/**/*.{js,ts,jsx,tsx}",
    ],
    prefix: "",
    theme: {
        screens: {
            'sm': '0',
            'md': '768px',
            'lg': '1024px',
            'xl': '1280px',
        },
        container: {
            center: true,
            padding: "2rem",
            screens: {
                "2xl": "1400px",
            },
        },
        extend: {
            colors: {
                border: "hsl(var(--border))",
                input: "hsl(var(--input))",
                ring: "hsl(var(--ring))",
                background: "hsl(var(--background))",
                foreground: "hsl(var(--foreground))",
                primary: {
                    DEFAULT: "hsl(var(--primary))",
                    foreground: "hsl(var(--primary-foreground))",
                },
                secondary: {
                    DEFAULT: "hsl(var(--secondary))",
                    foreground: "hsl(var(--secondary-foreground))",
                },
                success: {
                    DEFAULT: "hsl(var(--success))",
                    foreground: "hsl(var(--success-foreground))",
                    accent: "hsl(var(--success-accent))",
                },
                destructive: {
                    DEFAULT: "hsl(var(--destructive))",
                    foreground: "hsl(var(--destructive-foreground))",
                    accent: "hsl(var(--destructive-accent))",
                },
                muted: {
                    DEFAULT: "hsl(var(--muted))",
                    foreground: "hsl(var(--muted-foreground))",
                },
                accent: {
                    DEFAULT: "hsl(var(--accent))",
                    foreground: "hsl(var(--accent-foreground))",
                },
                popover: {
                    DEFAULT: "hsl(var(--popover))",
                    foreground: "hsl(var(--popover-foreground))",
                },
                card: {
                    DEFAULT: "hsl(var(--card))",
                    foreground: "hsl(var(--card-foreground))",
                },
                warning: {
                    DEFAULT: "hsl(var(--warning))",
                    foreground: "hsl(var(--warning-foreground))",
                    accent: "hsl(var(--warning-accent))",
                },
            },
            borderRadius: {
                "2xl": "calc(var(--radius) + 6px)",
                xl: "calc(var(--radius) + 2px)",
                lg: "var(--radius)",
                md: "calc(var(--radius) - 2px)",
                sm: "calc(var(--radius) - 4px)",
            },
            boxShadow: {
                'apple-xs': 'var(--shadow-xs)',
                'apple-sm': 'var(--shadow-sm)',
                'apple-md': 'var(--shadow-md)',
                'apple-lg': 'var(--shadow-lg)',
                'apple-xl': 'var(--shadow-xl)',
                'apple-card': 'var(--shadow-card)',
                'apple-card-hover': 'var(--shadow-card-hover)',
                'apple-float': 'var(--shadow-float)',
            },
            keyframes: {
                "accordion-down": {
                    from: { height: "0" },
                    to: { height: "var(--radix-accordion-content-height)" },
                },
                "accordion-up": {
                    from: { height: "var(--radix-accordion-content-height)" },
                    to: { height: "0" },
                },
                "apple-fade-in": {
                    from: { opacity: "0", transform: "scale(0.97)" },
                    to: { opacity: "1", transform: "scale(1)" },
                },
                "apple-slide-up": {
                    from: { opacity: "0", transform: "translateY(8px)" },
                    to: { opacity: "1", transform: "translateY(0)" },
                },
                "apple-slide-down": {
                    from: { opacity: "0", transform: "translateY(-8px)" },
                    to: { opacity: "1", transform: "translateY(0)" },
                },
            },
            animation: {
                "accordion-down": "accordion-down 0.25s cubic-bezier(0.25, 0.1, 0.25, 1)",
                "accordion-up": "accordion-up 0.25s cubic-bezier(0.25, 0.1, 0.25, 1)",
                "apple-fade-in": "apple-fade-in 0.3s cubic-bezier(0.25, 0.1, 0.25, 1)",
                "apple-slide-up": "apple-slide-up 0.35s cubic-bezier(0.22, 1, 0.36, 1)",
                "apple-slide-down": "apple-slide-down 0.35s cubic-bezier(0.22, 1, 0.36, 1)",
            },
        },
    },
    plugins: [
        nextui(),
        tailwindcssAnimate,
        tailwindcssForm,
        tailwindcssAspectRatio,
        tailwindcssTypography
    ],
}

export default config;
