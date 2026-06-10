import { useQuery, useQueryClient } from '@tanstack/react-query';
import { BookMarked, Quote } from 'lucide-react';
import { apiGet } from '../shared/api/client';
import { ReadingQuotesResponse } from '../shared/api/types';
import { AdminLogin, isAuthError } from '../shared/ui/AdminAuth';
import { Shell } from '../shared/ui/Shell';
import { ErrorState, LoadingState } from '../shared/ui/State';

export function ReadingQuotesPage() {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ['reading-quotes'],
    queryFn: () => apiGet<ReadingQuotesResponse>('/api/admin/reading-quotes'),
  });

  if (query.isLoading) return <LoadingState />;
  if (query.isError && isAuthError(query.error)) {
    return <AdminLogin onLoggedIn={() => queryClient.invalidateQueries({ queryKey: ['reading-quotes'] })} />;
  }
  if (query.isError) return <ErrorState message={(query.error as Error).message} />;
  if (!query.data) return <ErrorState message="摘抄数据为空。" />;

  return (
    <Shell
      eyebrow="Quotes"
      title="我的摘抄"
      meta="从快读包保存下来的句子，会关联到作品并进入画像证据"
      actions={
        <>
          <a className="secondary-link" href="/admin/profile-evidence">画像证据</a>
          <a className="secondary-link" href="/admin/weekly-report">画像复盘</a>
        </>
      }
    >
      <section className="quote-admin-list">
        {query.data.items.length === 0 ? (
          <div className="empty-panel">
            <h2>暂无摘抄</h2>
            <p>在快读包页面选中句子并保存后，这里会按时间显示你的摘抄。</p>
          </div>
        ) : (
          query.data.items.map((item) => (
            <article className="quote-admin-card" key={item.id}>
              <div className="quote-admin-head">
                <span>
                  <BookMarked size={16} />
                  {item.book.title}
                </span>
                <small>{formatDate(item.created_at)}</small>
              </div>
              <blockquote>
                <Quote size={16} />
                {item.selected_text}
              </blockquote>
              {item.note ? <p>{item.note}</p> : null}
              <div className="evidence-tags">
                {item.book.author ? <span>{item.book.author}</span> : null}
                {item.module ? <span>{item.module}</span> : null}
                {item.section_title ? <span>{item.section_title}</span> : null}
              </div>
            </article>
          ))
        )}
      </section>
    </Shell>
  );
}

function formatDate(value: string) {
  return value ? value.replace('T', ' ').slice(0, 16) : '-';
}
