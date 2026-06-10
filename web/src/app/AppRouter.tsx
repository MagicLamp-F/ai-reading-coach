import { GuidedReadingDayPage } from '../pages/GuidedReadingDayPage';
import { HomePage } from '../pages/HomePage';
import { ProfileEvidencePage } from '../pages/ProfileEvidencePage';
import { ReadingPackPage } from '../pages/ReadingPackPage';
import { ReadingPlansPage } from '../pages/ReadingPlansPage';
import { ReadingQuotesPage } from '../pages/ReadingQuotesPage';
import { ReadingSourceDetailPage } from '../pages/ReadingSourceDetailPage';
import { ReadingSourcesPage } from '../pages/ReadingSourcesPage';
import { WeeklyReportPage } from '../pages/WeeklyReportPage';

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
  if (path === '/admin/weekly-report') {
    return <WeeklyReportPage />;
  }
  if (path === '/admin/profile-evidence') {
    return <ProfileEvidencePage />;
  }
  if (path === '/admin/quotes') {
    return <ReadingQuotesPage />;
  }

  return <HomePage />;
}
