import { useMutation, useQuery } from '@tanstack/react-query';
import { Check, ChevronLeft, ChevronRight, MessageSquare } from 'lucide-react';
import { FormEvent, useMemo, useState } from 'react';
import { apiGet, apiPost, searchParams } from '../shared/api/client';
import { ReadingPack } from '../shared/api/types';
import { Shell } from '../shared/ui/Shell';
import { ErrorState, LoadingState, MissingParams } from '../shared/ui/State';

export function ReadingPackPage() {
  const params = searchParams();
  const id = params.get('id');
  const token = params.get('token');
  const module = params.get('module') || 'overview';

  if (!id || !token) {
    return <MissingParams message="快读包链接需要 id 和 token。" />;
  }

  const query = useQuery({
    queryKey: ['reading-pack', id, token, module],
    queryFn: () => apiGet<ReadingPack>(`/api/reading-packs/${id}?token=${encodeURIComponent(token)}&module=${encodeURIComponent(module)}`),
  });

  if (query.isLoading) return <LoadingState />;
  if (query.isError) return <ErrorState message={(query.error as Error).message} />;
  if (!query.data) return <ErrorState message="快读包数据为空。" />;

  return <ReadingPackView pack={query.data} />;
}

function ReadingPackView({ pack }: { pack: ReadingPack }) {
  const current = pack.modules.find((item) => item.active) ?? pack.modules[0];
  const prev = pack.modules[pack.current_index - 1];
  const next = pack.modules[pack.current_index + 1];

  return (
    <Shell
      eyebrow="快读包"
      title={`${pack.book.title}`}
      meta={`${pack.book.author || '未知作者'} · ${pack.status} · ${pack.generator_provider} · ${current.label} ${pack.current_index + 1}/${pack.modules.length}`}
    >
      <nav className="pill-row" aria-label="模块">
        {pack.modules.map((item) => (
          <a
            key={item.slug}
            className={`pill ${item.active ? 'active' : ''}`}
            href={`/reading-pack?id=${pack.id}&token=${encodeURIComponent(pack.token)}&module=${item.slug}`}
          >
            {item.label}
          </a>
        ))}
      </nav>
      <div className="progress-track" aria-label="阅读进度">
        <span style={{ width: `${pack.progress_percent}%` }} />
      </div>
      <section className="brief-panel">
        <div>
          <p className="eyebrow">本页导读</p>
          <h2>{current.description}</h2>
        </div>
        <span className="meter">{pack.sections.reduce((sum, section) => sum + section.minutes, 0)} 分钟</span>
      </section>
      <section className="reading-grid">
        <article className="content-stack">
          <section className="content-section thesis">
            <h2>推荐判断</h2>
            <p>{pack.recommendation.reason}</p>
            <p className="muted">{pack.recommendation.expected_benefit}</p>
          </section>
          {pack.sections.map((section) => (
            <section className="content-section" key={section.title} id={section.title}>
              <div className="section-title-row">
                <h2>{section.title}</h2>
                <span>{section.minutes} 分钟</span>
              </div>
              <StructuredBody value={section.body} />
            </section>
          ))}
          <nav className="pager" aria-label="分页">
            {prev ? (
              <a href={`/reading-pack?id=${pack.id}&token=${encodeURIComponent(pack.token)}&module=${prev.slug}`}>
                <ChevronLeft size={17} />
                <span>{prev.label}</span>
              </a>
            ) : (
              <span />
            )}
            {next ? (
              <a href={`/reading-pack?id=${pack.id}&token=${encodeURIComponent(pack.token)}&module=${next.slug}`}>
                <span>{next.label}</span>
                <ChevronRight size={17} />
              </a>
            ) : (
              <span />
            )}
          </nav>
        </article>
        <aside className="side-rail">
          <FeedbackPanel pack={pack} />
        </aside>
      </section>
    </Shell>
  );
}

function StructuredBody({ value }: { value: unknown }) {
  if (Array.isArray(value)) {
    return (
      <>
        {value.map((item, index) => {
          if (typeof item === 'string') {
            return <p key={index}>{item}</p>;
          }
          if (item && typeof item === 'object') {
            return <ObjectBlock key={index} value={item as Record<string, unknown>} />;
          }
          return <p key={index}>{String(item)}</p>;
        })}
      </>
    );
  }
  return <p>{String(value || '')}</p>;
}

function ObjectBlock({ value }: { value: Record<string, unknown> }) {
  const entries = Object.entries(value).filter(([, item]) => item !== null && item !== undefined && String(item).trim() !== '');
  return (
    <div className="object-block">
      {entries.map(([key, item]) => (
        <div key={key}>
          <strong>{key}</strong>
          {Array.isArray(item) ? <StructuredBody value={item} /> : <p>{String(item)}</p>}
        </div>
      ))}
    </div>
  );
}

function FeedbackPanel({ pack }: { pack: ReadingPack }) {
  const [freeText, setFreeText] = useState('');
  const [saved, setSaved] = useState('');
  const mutation = useMutation({
    mutationFn: (payload: { feedback_type: string; reason_code: string; token: string; free_text: string }) =>
      apiPost<{ status: string; feedback_id: number }>(`/api/reading-packs/${pack.id}/feedback`, payload),
    onSuccess: (_, variables) => {
      setSaved(variables.reason_code);
      setFreeText('');
    },
  });

  const options = useMemo(() => pack.feedback_options, [pack.feedback_options]);

  function submit(event: FormEvent<HTMLFormElement>, feedbackType: string, reasonCode: string, reasonToken: string) {
    event.preventDefault();
    mutation.mutate({ feedback_type: feedbackType, reason_code: reasonCode, token: reasonToken, free_text: freeText });
  }

  return (
    <section className="feedback-card">
      <h2>
        <MessageSquare size={17} />
        反馈
      </h2>
      <textarea maxLength={500} value={freeText} onChange={(event) => setFreeText(event.target.value)} placeholder="可选：补一句原因" />
      {options.map((group) => (
        <details key={group.type}>
          <summary>{group.label}</summary>
          <div className="button-grid">
            {group.reasons.map((reason) => (
              <form key={reason.code} onSubmit={(event) => submit(event, group.type, reason.code, reason.token)}>
                <button type="submit" disabled={mutation.isPending}>
                  {saved === reason.code ? <Check size={14} /> : null}
                  {reason.label}
                </button>
              </form>
            ))}
          </div>
        </details>
      ))}
      {mutation.isError ? <p className="error-text">{(mutation.error as Error).message}</p> : null}
    </section>
  );
}
