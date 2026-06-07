import { ReactNode } from 'react';

type ShellProps = {
  eyebrow: string;
  title: string;
  meta?: string;
  actions?: ReactNode;
  children: ReactNode;
};

export function Shell({ eyebrow, title, meta, actions, children }: ShellProps) {
  return (
    <main className="shell">
      <header className="page-header">
        <div>
          <p className="eyebrow">{eyebrow}</p>
          <h1>{title}</h1>
          {meta ? <p className="meta">{meta}</p> : null}
        </div>
        {actions ? <div className="header-actions">{actions}</div> : null}
      </header>
      {children}
    </main>
  );
}
