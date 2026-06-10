import { useMutation } from '@tanstack/react-query';
import { Trash2 } from 'lucide-react';
import { FormEvent, useState } from 'react';
import { apiDelete, apiGet, apiPost, searchParams } from '../shared/api/client';
import { ReadingSource } from '../shared/api/types';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { AdminLogin, isAuthError } from '../shared/ui/AdminAuth';
import { Shell } from '../shared/ui/Shell';
import { ErrorState, LoadingState, MissingParams } from '../shared/ui/State';

export function ReadingSourceDetailPage() {
  const params = searchParams();
  const id = params.get('id');
  const adminToken = params.get('admin_token');
  const queryClient = useQueryClient();
  if (!id) return <MissingParams message="书源详情需要 id。" />;
  const authSuffix = adminToken ? `?admin_token=${encodeURIComponent(adminToken)}` : '';
  const query = useQuery({
    queryKey: ['reading-source', id, adminToken ?? 'session'],
    queryFn: () => apiGet<ReadingSource>(`/api/admin/reading-sources/${id}${authSuffix}`),
  });
  if (query.isLoading) return <LoadingState />;
  if (query.isError && !adminToken && isAuthError(query.error)) {
    return <AdminLogin onLoggedIn={() => queryClient.invalidateQueries({ queryKey: ['reading-source', id, 'session'] })} />;
  }
  if (query.isError) return <ErrorState message={(query.error as Error).message} />;
  if (!query.data) return <ErrorState message="书源数据为空。" />;
  return <SourceDetail source={query.data} adminToken={adminToken} />;
}

function SourceDetail({ source, adminToken }: { source: ReadingSource; adminToken: string | null }) {
  const [result, setResult] = useState('');
  const createMutation = useMutation({
    mutationFn: (payload: Record<string, unknown>) => apiPost<{ first_day_url: string }>('/api/admin/reading-plans', payload),
    onSuccess: (data) => setResult(data.first_day_url),
  });
  const deleteMutation = useMutation({
    mutationFn: () => apiDelete<{ status: string }>(`/api/admin/reading-sources/${source.id}`, adminToken ? { admin_token: adminToken } : {}),
    onSuccess: () => {
      window.location.href = adminToken ? `/guided-reading/sources?admin_token=${encodeURIComponent(adminToken)}` : '/guided-reading/sources';
    },
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    createMutation.mutate({
      ...(adminToken ? { admin_token: adminToken } : {}),
      source_file_id: source.id,
      plan_days: Number(form.get('plan_days') || 5),
      daily_minutes: Number(form.get('daily_minutes') || 8),
      mode: String(form.get('mode') || 'guided'),
      tone: String(form.get('tone') || 'short_video'),
      spoiler_policy: String(form.get('spoiler_policy') || 'avoid'),
      lark_push_enabled: form.get('lark_push_enabled') === '1',
    });
  }

  const sourcesHref = adminToken ? `/guided-reading/sources?admin_token=${encodeURIComponent(adminToken)}` : '/guided-reading/sources';

  return (
    <Shell eyebrow="书源" title={source.title} meta={`${source.original_filename} · ${source.file_format} · ${source.char_count} 字`} actions={<a className="secondary-link" href={sourcesHref}>返回书源管理</a>}>
      <section className="admin-grid">
        <section className="content-section source-preview">
          <h2>内容预览</h2>
          <pre>{source.preview}</pre>
        </section>
        <section className="form-panel">
          <h2>基于此书源创建计划</h2>
          <form onSubmit={submit}>
            <label>计划天数<input name="plan_days" type="number" min="1" max="60" defaultValue="5" /></label>
            <label>每天分钟<input name="daily_minutes" type="number" min="1" max="180" defaultValue="8" /></label>
            <label>模式<select name="mode" defaultValue="guided"><option value="guided">渐进导读</option><option value="drama">追剧式</option><option value="fast_intro">轻速览</option><option value="deep_read">深读</option></select></label>
            <label>口吻<select name="tone" defaultValue="short_video"><option value="short_video">短导读</option><option value="drama">追剧式</option><option value="coach">私教式</option><option value="deep">深读式</option></select></label>
            <label>剧透策略<select name="spoiler_policy" defaultValue="avoid"><option value="avoid">不剧透</option><option value="allow">允许剧透</option></select></label>
            <label className="check-line"><input type="checkbox" name="lark_push_enabled" value="1" /> 飞书推送每日导读</label>
            <button type="submit" disabled={createMutation.isPending}>创建阅读计划</button>
          </form>
          {result ? <a className="primary-link wide" href={result}>打开第一天导读</a> : null}
          <button className="danger-button" type="button" onClick={() => deleteMutation.mutate()} disabled={deleteMutation.isPending}>
            <Trash2 size={16} /> 删除书源
          </button>
          {createMutation.isError ? <p className="error-text">{(createMutation.error as Error).message}</p> : null}
          {deleteMutation.isError ? <p className="error-text">{(deleteMutation.error as Error).message}</p> : null}
        </section>
      </section>
    </Shell>
  );
}
