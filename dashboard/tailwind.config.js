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
                'neon-cyan': "hsl(var(--neon-cyan))",
                'neon-magenta': "hsl(var(--neon-magenta))",
                'neon-purple': "hsl(var(--neon-purple))",
                'neon-yellow': "hsl(var(--neon-yellow))",
            },
            borderRadius: {
                lg: "var(--radius)",
                md: "calc(var(--radius) - 2px)",
                sm: "calc(var(--radius) - 4px)",
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
                "pulse-glow": {
                    "0%, 100%": { 
                        boxShadow: "0 0 5px hsl(var(--primary)), 0 0 10px hsl(var(--primary) / 0.5)",
                    },
                    "50%": { 
                        boxShadow: "0 0 20px hsl(var(--primary)), 0 0 40px hsl(var(--primary) / 0.5), 0 0 60px hsl(var(--primary) / 0.3)",
                    },
                },
                "neon-flicker": {
                    "0%, 19.999%, 22%, 62.999%, 64%, 64.999%, 70%, 100%": {
                        opacity: "1",
                        textShadow: "0 0 5px hsl(var(--primary)), 0 0 10px hsl(var(--primary) / 0.5), 0 0 20px hsl(var(--primary) / 0.3)",
                    },
                    "20%, 21.999%, 63%, 63.999%, 65%, 69.999%": {
                        opacity: "0.4",
                        textShadow: "none",
                    },
                },
                "glitch": {
                    "0%": {
                        transform: "translate(0)",
                    },
                    "20%": {
                        transform: "translate(-2px, 2px)",
                    },
                    "40%": {
                        transform: "translate(-2px, -2px)",
                    },
                    "60%": {
                        transform: "translate(2px, 2px)",
                    },
                    "80%": {
                        transform: "translate(2px, -2px)",
                    },
                    "100%": {
                        transform: "translate(0)",
                    },
                },
                "slide-in-right": {
                    "0%": {
                        transform: "translateX(100%)",
                        opacity: "0",
                    },
                    "100%": {
                        transform: "translateX(0)",
                        opacity: "1",
                    },
                },
                "cyber-scan": {
                    "0%": {
                        transform: "translateY(-100%)",
                    },
                    "100%": {
                        transform: "translateY(100%)",
                    },
                },
            },
            animation: {
                "accordion-down": "accordion-down 0.2s ease-out",
                "accordion-up": "accordion-up 0.2s ease-out",
                "pulse-glow": "pulse-glow 2s ease-in-out infinite",
                "neon-flicker": "neon-flicker 3s infinite",
                "glitch": "glitch 0.3s infinite",
                "slide-in-right": "slide-in-right 0.5s ease-out",
                "cyber-scan": "cyber-scan 3s linear infinite",
            },
            fontFamily: {
                'font-body': ['Rajdhani', 'sans-serif'],
                'font-header': ['Orbitron', 'sans-serif'],
            },
            backgroundImage: {
                'cyber-grid': 'linear-gradient(rgba(0, 255, 255, 0.1) 1px, transparent 1px), linear-gradient(90deg, rgba(0, 255, 255, 0.1) 1px, transparent 1px)',
                'neon-gradient': 'linear-gradient(135deg, hsl(var(--neon-cyan)), hsl(var(--neon-magenta)), hsl(var(--neon-purple)))',
            },
            backgroundSize: {
                'grid': '50px 50px',
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
