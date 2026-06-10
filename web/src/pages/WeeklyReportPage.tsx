import { useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, ArrowRight, BarChart3, FileText, ShieldCheck, UserRound } from 'lucide-react';
import { ReactNode } from 'react';
import { apiGet } from '../shared/api/client';
import { WeeklyReport } from '../shared/api/types';
import { AdminLogin, isAuthError } from '../shared/ui/AdminAuth';
import { Shell } from '../shared/ui/Shell';
import { ErrorState, LoadingState } from '../shared/ui/State';

export function WeeklyReportPage() {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ['weekly-report'],
    queryFn: () => apiGet<WeeklyReport>('/api/admin/weekly-report'),
  });

  if (query.isLoading) return <LoadingState />;
  if (query.isError && isAuthError(query.error)) {
    return <AdminLogin onLoggedIn={() => queryClient.invalidateQueries({ queryKey: ['weekly-report'] })} />;
  }
  if (query.isError) return <ErrorState message={(query.error as Error).message} />;
  if (!query.data) return <ErrorState message="周报数据为空。" />;

  const report = query.data;
  return (
    <Shell
      eyebrow="Profile"
      title={`${report.days} 天阅读画像复盘`}
      meta="面向用户的总结、画像写回状态和下周推荐策略"
      actions={
        <>
          <a className="secondary-link" href="/admin/profile-evidence">画像证据</a>
          <a className="secondary-link" href="/guided-reading/sources">书源管理</a>
        </>
      }
    >
      <section className="metric-grid">
        <Metric label="推荐" value={report.metrics.recommendation_count} suffix="本" />
        <Metric label="反馈" value={report.metrics.feedback_total} suffix="次" />
        <Metric label="正向" value={report.metrics.positive_total} suffix="次" />
        <Metric label="命中率" value={report.metrics.hit_rate} suffix="%" />
      </section>

      <section className="report-grid">
        <ReportPanel title="给你的结论" icon={<UserRound size={18} />} lines={report.user_summary} variant="primary" />
        <ReportPanel title="画像写回状态" icon={<ShieldCheck size={18} />} lines={report.writeback_status} />
      </section>

      <section className="report-grid">
        <ReportPanel title="稳定画像" icon={<BarChart3 size={18} />} lines={report.profile_sections.stable} />
        <ReportPanel title="待验证画像" icon={<ArrowRight size={18} />} lines={report.profile_sections.pending} />
        <ReportPanel title="可能误解" icon={<AlertTriangle size={18} />} lines={report.profile_sections.misunderstood} />
        <ReportPanel title="下周方向" icon={<ArrowRight size={18} />} lines={report.next_directions} />
      </section>

      <section className="report-panel report-full">
        <h2>
          <FileText size={18} />
          完整周报
        </h2>
        <pre>{report.report_text}</pre>
      </section>
    </Shell>
  );
}

function Metric({ label, value, suffix }: { label: string; value: number; suffix: string }) {
  return (
    <div className="metric-card">
      <span>{label}</span>
      <strong>
        {value}
        <small>{suffix}</small>
      </strong>
    </div>
  );
}

function ReportPanel({
  title,
  icon,
  lines,
  variant,
}: {
  title: string;
  icon: ReactNode;
  lines: string[];
  variant?: 'primary';
}) {
  return (
    <section className={`report-panel ${variant === 'primary' ? 'primary' : ''}`}>
      <h2>
        {icon}
        {title}
      </h2>
      <div className="report-lines">
        {lines.map((line, index) => (
          <p key={`${title}-${index}`}>{cleanLine(line)}</p>
        ))}
      </div>
    </section>
  );
}

function cleanLine(line: string) {
  return line.replace(/^-\s*/, '');
}
