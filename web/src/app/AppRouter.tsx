import { GuidedReadingDayPage } from '../pages/GuidedReadingDayPage';
import { ReadingPackPage } from '../pages/ReadingPackPage';
import { ReadingPlansPage } from '../pages/ReadingPlansPage';
import { ReadingSourceDetailPage } from '../pages/ReadingSourceDetailPage';
import { ReadingSourcesPage } from '../pages/ReadingSourcesPage';
import { Shell } from '../shared/ui/Shell';

export function AppRouter() {
  const path = window.location.pathname;

  if (path === '/reading-pack') {
    return <ReadingPackPage />;
  }
  if (path === '/guided-reading') {
    return <GuidedReadingDayPage />;
  }
  if (path === '/guided-reading/plans') {
    return <ReadingPlansPage />;
  }
  if (path === '/guided-reading/sources') {
    return <ReadingSourcesPage />;
  }
  if (path === '/guided-reading/source') {
    return <ReadingSourceDetailPage />;
  }

  return (
    <Shell title="AI Reading Coach" eyebrow="ARC">
      <section className="empty-panel">
        <h2>阅读工作台</h2>
        <p>从飞书导读链接、快读包链接或管理入口进入。</p>
      </section>
    </Shell>
  );
}
