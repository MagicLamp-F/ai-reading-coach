import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus } from 'lucide-react';
import { FormEvent, useState } from 'react';
import { apiGet, apiPost, searchParams } from '../shared/api/client';
import { ReadingPlan } from '../shared/api/types';
import { AdminLogin, isAuthError } from '../shared/ui/AdminAuth';
import { Shell } from '../shared/ui/Shell';
import { ErrorState, LoadingState } from '../shared/ui/State';

export function ReadingPlansPage() {
  const adminToken = searchParams().get('admin_token');
  const queryClient = useQueryClient();
  const authSuffix = adminToken ? `?admin_token=${encodeURIComponent(adminToken)}` : '';
  const query = useQuery({
    queryKey: ['reading-plans', adminToken ?? 'session'],
    queryFn: () => apiGet<{ plans: ReadingPlan[] }>(`/api/admin/reading-plans${authSuffix}`),
  });
  if (query.isLoading) return <LoadingState />;
  if (query.isError && !adminToken && isAuthError(query.error)) {
    return <AdminLogin onLoggedIn={() => queryClient.invalidateQueries({ queryKey: ['reading-plans', 'session'] })} />;
  }
  if (query.isError) return <ErrorState message={(query.error as Error).message} />;
  const sourcesHref = adminToken ? `/guided-reading/sources?admin_token=${encodeURIComponent(adminToken)}` : '/guided-reading/sources';

  return (
    <Shell eyebrow="Admin" title="导读计划配置" meta="创建和查看渐进导读计划" actions={<a className="secondary-link" href={sourcesHref}>书源管理</a>}>
      <section className="admin-grid">
        <PlanTable plans={query.data?.plans ?? []} />
        <PlanForm adminToken={adminToken} />
      </section>
    </Shell>
  );
}

function PlanTable({ plans }: { plans: ReadingPlan[] }) {
  return (
    <section className="table-panel">
      <h2>已有计划</h2>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>书</th>
              <th>模式</th>
              <th>计划</th>
              <th>飞书</th>
              <th>状态</th>
            </tr>
          </thead>
          <tbody>
            {plans.map((plan) => (
              <tr key={plan.id}>
                <td>{plan.id}</td>
                <td>{plan.book_title}</td>
                <td>{plan.mode} / {plan.tone}</td>
                <td>{plan.plan_days} 天 · {plan.daily_minutes} 分钟</td>
                <td>{plan.lark_push_enabled ? '开' : '关'}</td>
                <td>{plan.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function PlanForm({ adminToken }: { adminToken: string | null }) {
  const queryClient = useQueryClient();
  const [result, setResult] = useState('');
  const mutation = useMutation({
    mutationFn: (payload: Record<string, unknown>) => apiPost<{ first_day_url: string }>('/api/admin/reading-plans', payload),
    onSuccess: (data) => {
      setResult(data.first_day_url);
      queryClient.invalidateQueries({ queryKey: ['reading-plans', adminToken ?? 'session'] });
    },
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    mutation.mutate({
      ...(adminToken ? { admin_token: adminToken } : {}),
      title: String(form.get('title') || ''),
      author: String(form.get('author') || ''),
      plan_days: Number(form.get('plan_days') || 5),
      daily_minutes: Number(form.get('daily_minutes') || 8),
      mode: String(form.get('mode') || 'guided'),
      tone: String(form.get('tone') || 'short_video'),
      spoiler_policy: String(form.get('spoiler_policy') || 'avoid'),
      lark_push_enabled: form.get('lark_push_enabled') === '1',
      source_text: String(form.get('source_text') || ''),
    });
  }

  return (
    <section className="form-panel">
      <h2>
        <Plus size={18} />
        创建计划
      </h2>
      <form onSubmit={submit}>
        <label>书名<input name="title" required /></label>
        <label>作者<input name="author" /></label>
        <div className="field-grid">
          <label>计划天数<input name="plan_days" type="number" min="1" max="60" defaultValue="5" /></label>
          <label>每天分钟<input name="daily_minutes" type="number" min="1" max="180" defaultValue="8" /></label>
        </div>
        <div className="field-grid">
          <label>模式<select name="mode" defaultValue="guided"><option value="guided">渐进导读</option><option value="drama">追剧式</option><option value="fast_intro">轻速览</option><option value="deep_read">深读</option></select></label>
          <label>口吻<select name="tone" defaultValue="short_video"><option value="short_video">短导读</option><option value="drama">追剧式</option><option value="coach">私教式</option><option value="deep">深读式</option></select></label>
        </div>
        <label>剧透策略<select name="spoiler_policy" defaultValue="avoid"><option value="avoid">不剧透</option><option value="allow">允许剧透</option></select></label>
        <label className="check-line"><input type="checkbox" name="lark_push_enabled" value="1" /> 飞书推送每日导读</label>
        <label>书源文本<textarea name="source_text" required /></label>
        <button type="submit" disabled={mutation.isPending}>创建阅读计划</button>
      </form>
      {result ? <a className="primary-link wide" href={result}>打开第一天导读</a> : null}
      {mutation.isError ? <p className="error-text">{(mutation.error as Error).message}</p> : null}
    </section>
  );
}
