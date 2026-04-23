import { createFileRoute } from '@tanstack/react-router';
import { EditorialPage } from '../../components/markdown';
import { pageContent } from '@/content/docs';
import { site } from '@/lib/site';

export const Route = createFileRoute('/docs/')({
    component: DocsPage,
    head: () => ({
        meta: [
            { title: pageContent.meta.title },
            { name: 'description', content: pageContent.meta.description },
        ],
        links: [
            { rel: 'alternate', hrefLang: 'en', href: '/docs/' },
            { rel: 'alternate', hrefLang: 'x-default', href: '/docs/' },
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
            brand={site.brand}
            repoUrl={site.repoUrl}
        />
    );
}
