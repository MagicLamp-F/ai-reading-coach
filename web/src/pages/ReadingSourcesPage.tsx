import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Upload } from 'lucide-react';
import { FormEvent } from 'react';
import { apiGet, apiUpload, searchParams } from '../shared/api/client';
import { ReadingSource } from '../shared/api/types';
import { AdminLogin, isAuthError } from '../shared/ui/AdminAuth';
import { Shell } from '../shared/ui/Shell';
import { ErrorState, LoadingState } from '../shared/ui/State';

export function ReadingSourcesPage() {
  const adminToken = searchParams().get('admin_token');
  const queryClient = useQueryClient();
  const authSuffix = adminToken ? `?admin_token=${encodeURIComponent(adminToken)}` : '';
  const query = useQuery({
    queryKey: ['reading-sources', adminToken ?? 'session'],
    queryFn: () => apiGet<{ sources: ReadingSource[] }>(`/api/admin/reading-sources${authSuffix}`),
  });
  if (query.isLoading) return <LoadingState />;
  if (query.isError && !adminToken && isAuthError(query.error)) {
    return <AdminLogin onLoggedIn={() => queryClient.invalidateQueries({ queryKey: ['reading-sources', 'session'] })} />;
  }
  if (query.isError) return <ErrorState message={(query.error as Error).message} />;
  const planHref = adminToken ? `/guided-reading/plans?admin_token=${encodeURIComponent(adminToken)}` : '/guided-reading/plans';

  return (
    <Shell eyebrow="Admin" title="书源管理" meta="导入书源并基于书源创建计划" actions={<a className="secondary-link" href={planHref}>导读计划</a>}>
      <section className="admin-grid">
        <section className="table-panel">
          <h2>已导入书源</h2>
          <div className="table-scroll">
            <table>
              <thead><tr><th>ID</th><th>书名</th><th>文件</th><th>格式</th><th>字数</th></tr></thead>
              <tbody>
                {(query.data?.sources ?? []).map((source) => (
                  <tr key={source.id}>
                    <td>{source.id}</td>
                    <td><a href={sourceHref(source.id, adminToken)}>{source.title}</a></td>
                    <td>{source.original_filename}</td>
                    <td>{source.file_format}</td>
                    <td>{source.char_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
        <UploadForm adminToken={adminToken} />
      </section>
    </Shell>
  );
}

function UploadForm({ adminToken }: { adminToken: string | null }) {
  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationFn: (form: FormData) => apiUpload<{ source_id: number }>('/api/admin/reading-sources/upload', form),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['reading-sources', adminToken ?? 'session'] });
      window.location.href = sourceHref(data.source_id, adminToken);
    },
  });
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    if (adminToken) form.set('admin_token', adminToken);
    mutation.mutate(form);
  }
  return (
    <section className="form-panel">
      <h2><Upload size={18} /> 上传书源</h2>
      <form onSubmit={submit}>
        <label>书名<input name="title" required /></label>
        <label>作者<input name="author" /></label>
        <label>文件<input name="source_file" type="file" accept=".md,.txt,.epub,text/plain,text/markdown,application/epub+zip" required /></label>
        <button type="submit" disabled={mutation.isPending}>导入书源</button>
      </form>
      {mutation.isError ? <p className="error-text">{(mutation.error as Error).message}</p> : null}
    </section>
  );
}

function sourceHref(sourceId: number, adminToken: string | null) {
  const params = new URLSearchParams({ id: String(sourceId) });
  if (adminToken) params.set('admin_token', adminToken);
  return `/guided-reading/source?${params.toString()}`;
}
