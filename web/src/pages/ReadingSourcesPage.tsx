import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Upload } from 'lucide-react';
import { FormEvent } from 'react';
import { apiGet, apiUpload, searchParams } from '../shared/api/client';
import { ReadingSource } from '../shared/api/types';
import { Shell } from '../shared/ui/Shell';
import { ErrorState, LoadingState, MissingParams } from '../shared/ui/State';

export function ReadingSourcesPage() {
  const adminToken = searchParams().get('admin_token');
  if (!adminToken) return <MissingParams message="书源管理入口需要 admin_token。" />;
  const query = useQuery({
    queryKey: ['reading-sources', adminToken],
    queryFn: () => apiGet<{ sources: ReadingSource[] }>(`/api/admin/reading-sources?admin_token=${encodeURIComponent(adminToken)}`),
  });
  if (query.isLoading) return <LoadingState />;
  if (query.isError) return <ErrorState message={(query.error as Error).message} />;

  return (
    <Shell eyebrow="Admin" title="书源管理" meta="导入书源并基于书源创建计划" actions={<a className="secondary-link" href={`/guided-reading/plans?admin_token=${encodeURIComponent(adminToken)}`}>导读计划</a>}>
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
                    <td><a href={`/guided-reading/source?id=${source.id}&admin_token=${encodeURIComponent(adminToken)}`}>{source.title}</a></td>
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

function UploadForm({ adminToken }: { adminToken: string }) {
  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationFn: (form: FormData) => apiUpload<{ source_id: number }>('/api/admin/reading-sources/upload', form),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['reading-sources', adminToken] });
      window.location.href = `/guided-reading/source?id=${data.source_id}&admin_token=${encodeURIComponent(adminToken)}`;
    },
  });
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    form.set('admin_token', adminToken);
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
