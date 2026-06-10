import { useMutation } from '@tanstack/react-query';
import { FormEvent } from 'react';
import { LockKeyhole } from 'lucide-react';
import { apiPost } from '../api/client';

export function AdminLogin({ onLoggedIn }: { onLoggedIn: () => void }) {
  const mutation = useMutation({
    mutationFn: (payload: { username: string; password: string }) =>
      apiPost<{ authenticated: boolean }>('/api/admin/login', payload),
    onSuccess: onLoggedIn,
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    mutation.mutate({
      username: String(form.get('username') || ''),
      password: String(form.get('password') || ''),
    });
  }

  return (
    <main className="shell auth-shell">
      <section className="auth-panel">
        <div className="auth-icon">
          <LockKeyhole size={22} />
        </div>
        <div>
          <p className="section-label">Admin</p>
          <h1>登录阅读工作台</h1>
        </div>
        <form onSubmit={submit}>
          <label>
            账号
            <input name="username" defaultValue="admin" autoComplete="username" required />
          </label>
          <label>
            密码
            <input name="password" type="password" autoComplete="current-password" required />
          </label>
          <button type="submit" disabled={mutation.isPending}>
            登录
          </button>
        </form>
        {mutation.isError ? <p className="error-text">{(mutation.error as Error).message}</p> : null}
      </section>
    </main>
  );
}

export function isAuthError(error: unknown) {
  return error instanceof Error && (error.message.includes('签名无效') || error.message.includes('账号或密码'));
}
