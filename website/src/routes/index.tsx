import { createFileRoute } from '@tanstack/react-router';
import { EditorialPage } from '../components/markdown';
import { pageContent } from '@/content/en';
import { site } from '@/lib/site';

export const Route = createFileRoute('/')({
    component: IndexPage,
    head: () => ({
        meta: [
            { title: pageContent.meta.title },
            { name: 'description', content: pageContent.meta.description },
        ],
        links: [
            { rel: 'alternate', hrefLang: 'en', href: '/' },
            { rel: 'alternate', hrefLang: 'x-default', href: '/' },
        ],
    }),
});

function IndexPage() {
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
