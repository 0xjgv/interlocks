import { createFileRoute } from '@tanstack/react-router';
import { EditorialPage } from '../../components/markdown';
import { pageContent } from '@/content/docs';

export const Route = createFileRoute('/docs/')({
    component: DocsPage,
    head: () => ({
        title: pageContent.meta.title,
        meta: [
            { name: 'description', content: pageContent.meta.description },
        ],
        links: [
            { rel: 'alternate', hreflang: 'en', href: '/docs/' },
            { rel: 'alternate', hreflang: 'x-default', href: '/docs/' },
        ],
    }),
});

function DocsPage() {
    return (
        <EditorialPage
            toc={pageContent.toc}
            sections={pageContent.sections}
            hero={pageContent.hero}
            logo="/pyharness-logo.svg"
        />
    );
}
