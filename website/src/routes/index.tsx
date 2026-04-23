import { createFileRoute } from '@tanstack/react-router';
import { EditorialPage } from '../components/markdown';
import { pageContent } from '@/content/en';

export const Route = createFileRoute('/')({
    component: IndexPage,
    head: () => ({
        title: pageContent.meta.title,
        meta: [
            { name: 'description', content: pageContent.meta.description },
        ],
        links: [
            { rel: 'alternate', hreflang: 'en', href: '/' },
            { rel: 'alternate', hreflang: 'x-default', href: '/' },
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
        />
    );
}
