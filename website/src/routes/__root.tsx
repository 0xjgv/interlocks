import { HeadContent, Scripts, createRootRoute } from '@tanstack/react-router';

import appCss from '../styles.css?url';

export const Route = createRootRoute({
    head: () => ({
        meta: [
            { charSet: 'utf-8' },
            {
                name: 'viewport',
                content: 'width=device-width, initial-scale=1',
            },
            { title: 'pyharness — zero-config Python quality harness' },
            {
                name: 'description',
                content:
                    'Lint, format, typecheck, test, coverage, acceptance, audit, deps, architecture, complexity, CRAP, mutation — all behind `harness <task>`.',
            },
        ],
        links: [
            { rel: 'icon', type: 'image/svg+xml', href: '/favicon.svg' },
            { rel: 'stylesheet', href: appCss },
            {
                rel: 'preload',
                as: 'font',
                type: 'font/woff2',
                href: '/fonts/InterVariable.woff2',
                crossOrigin: '',
            },
            { rel: 'preconnect', href: 'https://fonts.googleapis.com' },
            { rel: 'preconnect', href: 'https://fonts.gstatic.com', crossOrigin: '' },
            {
                rel: 'stylesheet',
                href: 'https://fonts.googleapis.com/css2?family=Newsreader:ital,opsz,wght@0,6..72,300..700;1,6..72,300..700&display=swap',
            },
        ],
    }),
    shellComponent: RootDocument,
});

function RootDocument({ children }: { children: React.ReactNode }) {
    return (
        <html lang="en">
            <head>
                <HeadContent />
            </head>
            <body>
                {children}
                <Scripts />
            </body>
        </html>
    );
}
