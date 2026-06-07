import { GuidedReadingDayPage } from '../pages/GuidedReadingDayPage';
import { HomePage } from '../pages/HomePage';
import { ReadingPackPage } from '../pages/ReadingPackPage';
import { ReadingPlansPage } from '../pages/ReadingPlansPage';
import { ReadingSourceDetailPage } from '../pages/ReadingSourceDetailPage';
import { ReadingSourcesPage } from '../pages/ReadingSourcesPage';

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

  return <HomePage />;
}
