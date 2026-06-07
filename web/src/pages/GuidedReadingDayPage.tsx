import { useMutation, useQuery } from '@tanstack/react-query';
import { BookOpen, Check, Clock } from 'lucide-react';
import { useState } from 'react';
import { apiGet, apiPost, searchParams } from '../shared/api/client';
import { GuidedDay } from '../shared/api/types';
import { Shell } from '../shared/ui/Shell';
import { ErrorState, LoadingState, MissingParams } from '../shared/ui/State';

const feedbackButtons = [
  ['completed', '读完了'],
  ['continue', '想继续'],
  ['just_right', '刚刚好'],
  ['too_long', '太长了'],
  ['not_interested', '没兴趣'],
] as const;

export function GuidedReadingDayPage() {
  const params = searchParams();
  const dayId = params.get('day_id');
  const token = params.get('token');

  if (!dayId || !token) {
    return <MissingParams message="导读链接需要 day_id 和 token。" />;
  }

  const query = useQuery({
    queryKey: ['guided-day', dayId, token],
    queryFn: () => apiGet<GuidedDay>(`/api/guided-reading/days/${dayId}?token=${encodeURIComponent(token)}`),
  });

  if (query.isLoading) return <LoadingState />;
  if (query.isError) return <ErrorState message={(query.error as Error).message} />;
  if (!query.data) return <ErrorState message="导读数据为空。" />;

  return <GuidedDayView day={query.data} />;
}

function GuidedDayView({ day }: { day: GuidedDay }) {
  const [note, setNote] = useState('');
  const [saved, setSaved] = useState('');
  const mutation = useMutation({
    mutationFn: (eventType: string) => apiPost<{ status: string }>(`/api/guided-reading/days/${day.id}/feedback`, { token: day.token, event_type: eventType, note }),
    onSuccess: (_, eventType) => {
      setSaved(eventType);
      setNote('');
    },
  });

  return (
    <Shell
      eyebrow={`Day ${day.day_number}/${day.total_days}`}
      title={day.book.title}
      meta={`${day.book.author || '未知作者'} · ${day.mode} · ${day.tone} · 约 ${day.estimated_minutes} 分钟`}
      actions={<span className="meter"><Clock size={14} /> {day.estimated_minutes} 分钟</span>}
    >
      <div className="progress-track" aria-label="计划进度">
        <span style={{ width: `${day.progress_percent}%` }} />
      </div>
      <nav className="pill-row" aria-label="阅读天数">
        {day.days.map((item) => (
          <a key={item.id} className={`pill ${item.id === day.id ? 'active' : ''}`} href={`/guided-reading?day_id=${item.id}&token=${encodeURIComponent(item.token)}`}>
            Day {item.day_number}
          </a>
        ))}
      </nav>
      <section className="hero-panel">
        <p className="eyebrow">今日钩子</p>
        <h2>{day.content.hook}</h2>
        <div className="hero-actions">
          <a className="primary-link" href="#source">
            <BookOpen size={16} />
            开始读
          </a>
          <a className="secondary-link" href="#explain">先看拆解</a>
        </div>
      </section>
      <section className="reading-grid">
        <article className="content-stack">
          {day.content.why_it_matters ? (
            <section className="content-section warm">
              <h2>追剧式续上</h2>
              <p>{day.content.why_it_matters}</p>
            </section>
          ) : null}
          <section className="content-section thesis">
            <h2>今天只抓一个问题</h2>
            <p>{day.content.one_question}</p>
          </section>
          <section className="content-section source" id="source">
            <h2>今日原文</h2>
            {day.source_paragraphs.map((paragraph, index) => (
              <p key={index}>{paragraph}</p>
            ))}
          </section>
          <section className="content-section" id="explain">
            <h2>白话拆解</h2>
            <p>{day.content.plain_explanation}</p>
          </section>
          <section className="content-section">
            <h2>关键点</h2>
            <ul>
              {day.content.key_points.map((point) => (
                <li key={point}>{point}</li>
              ))}
            </ul>
          </section>
          <section className="content-section">
            <h2>现实连接</h2>
            <p>{day.content.reality_connection}</p>
          </section>
          <section className="content-section">
            <h2>明天预告</h2>
            <p>{day.content.tomorrow_teaser}</p>
          </section>
        </article>
        <aside className="side-rail">
          <section className="feedback-card">
            <h2>今天的反馈</h2>
            <textarea maxLength={500} value={note} onChange={(event) => setNote(event.target.value)} placeholder="可选：补一句哪里卡住了" />
            <div className="button-grid two">
              {feedbackButtons.map(([eventType, label]) => (
                <button key={eventType} type="button" onClick={() => mutation.mutate(eventType)} disabled={mutation.isPending}>
                  {saved === eventType ? <Check size={14} /> : null}
                  {label}
                </button>
              ))}
            </div>
            {mutation.isError ? <p className="error-text">{(mutation.error as Error).message}</p> : null}
          </section>
        </aside>
      </section>
    </Shell>
  );
}
