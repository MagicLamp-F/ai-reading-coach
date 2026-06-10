import { useQuery } from '@tanstack/react-query';
import { Activity, BarChart3, BookMarked, BookOpen, CalendarDays, FileUp, Fingerprint, HeartHandshake, Library, Sparkles } from 'lucide-react';
import { apiGet } from '../shared/api/client';

type HealthResponse = {
  status?: string;
};

const quickLinks = [
  {
    title: '今日导读',
    detail: '继续分日阅读',
    href: '/guided-reading',
    icon: BookOpen,
  },
  {
    title: '快读包',
    detail: '打开飞书推荐包',
    href: '/reading-pack',
    icon: Sparkles,
  },
  {
    title: '导读计划',
    detail: '安排阅读节奏',
    href: '/guided-reading/plans',
    icon: CalendarDays,
  },
  {
    title: '书源管理',
    detail: '导入完整书源',
    href: '/guided-reading/sources',
    icon: FileUp,
  },
  {
    title: '画像复盘',
    detail: '查看周报与写回',
    href: '/admin/weekly-report',
    icon: BarChart3,
  },
  {
    title: '画像证据',
    detail: '确认或纠偏画像',
    href: '/admin/profile-evidence',
    icon: Fingerprint,
  },
  {
    title: '我的摘抄',
    detail: '回看喜欢的句子',
    href: '/admin/quotes',
    icon: BookMarked,
  },
];

export function HomePage() {
  const health = useQuery({
    queryKey: ['healthz'],
    queryFn: () => apiGet<HealthResponse>('/api/healthz'),
  });
  const statusLabel = health.isLoading ? 'Checking' : health.isError ? 'Offline' : health.data?.status ?? 'OK';

  return (
    <main className="home-shell">
      <section className="home-hero" aria-labelledby="home-title">
        <img className="home-hero-image" src="/assets/reading-coach-hero.png" alt="" />
        <div className="home-hero-shade" />
        <div className="home-hero-content">
          <p className="home-kicker">ARC</p>
          <h1 id="home-title">AI Reading Coach</h1>
          <p className="home-copy">每日推荐、Hermes 主画像、反馈闭环和渐进导读集中在一个移动入口。</p>
          <div className="home-status-row">
            <span className={`home-status ${health.isError ? 'offline' : ''}`}>
              <Activity size={15} />
              API {statusLabel}
            </span>
            <span className="home-status">
              <HeartHandshake size={15} />
              Hermes Profile
            </span>
          </div>
        </div>
      </section>

      <section className="home-band" aria-label="Reading operations">
        <div className="home-token-panel">
          <div>
            <p className="home-section-label">Admin</p>
            <h2>私人阅读工作台</h2>
          </div>
          <p className="home-token-note">管理页已切换为账号登录，会话保存在 HttpOnly cookie 中。</p>
        </div>

        <div className="home-link-grid">
          {quickLinks.map((item) => {
            const Icon = item.icon;
            return (
              <a className="home-link-card" href={item.href} key={item.title}>
                <span className="home-link-icon">
                  <Icon size={21} />
                </span>
                <span>
                  <strong>{item.title}</strong>
                  <small>{item.detail}</small>
                </span>
              </a>
            );
          })}
        </div>

        <div className="home-ops-strip">
          <div>
            <span>Profile</span>
            <strong>Hermes native USER</strong>
          </div>
          <div>
            <span>History</span>
            <strong>SQLite context</strong>
          </div>
          <div>
            <span>Reading</span>
            <strong>Guided packs</strong>
          </div>
          <div>
            <span>Library</span>
            <strong>
              <Library size={15} /> Sources
            </strong>
          </div>
        </div>
      </section>
    </main>
  );
}
