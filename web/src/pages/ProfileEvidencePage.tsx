import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { BadgeCheck, CircleAlert, Gauge, History, RotateCcw, ShieldCheck } from 'lucide-react';
import { FormEvent, ReactNode, useMemo } from 'react';
import { apiGet, apiPost } from '../shared/api/client';
import {
  ProfileEvidenceItem,
  ProfileEvidenceResponse,
  ProfileEvidenceReviewResponse,
  ProfileReviewAction,
} from '../shared/api/types';
import { AdminLogin, isAuthError } from '../shared/ui/AdminAuth';
import { Shell } from '../shared/ui/Shell';
import { ErrorState, LoadingState } from '../shared/ui/State';

const actionLabels: Record<ProfileReviewAction, string> = {
  confirm: '确认',
  inaccurate: '不准确',
  downrank: '降权',
};

const categoryLabels: Record<string, string> = {
  long_term_interest: '长期兴趣',
  short_term_interest: '近期兴趣',
  reading_preference: '阅读偏好',
  knowledge_gap: '知识缺口',
  knowledge_background: '已掌握背景',
  disliked_topic: '低兴趣主题',
  action_stage: '行动阶段',
  life_context: '个人上下文',
};

export function ProfileEvidencePage() {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ['profile-evidence'],
    queryFn: () => apiGet<ProfileEvidenceResponse>('/api/admin/profile-evidence'),
  });
  const reviewMutation = useMutation({
    mutationFn: ({ id, action, note }: { id: number; action: ProfileReviewAction; note: string }) =>
      apiPost<ProfileEvidenceReviewResponse>(`/api/admin/profile-evidence/${id}/review`, { action, note }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['profile-evidence'] }),
  });

  if (query.isLoading) return <LoadingState />;
  if (query.isError && isAuthError(query.error)) {
    return <AdminLogin onLoggedIn={() => queryClient.invalidateQueries({ queryKey: ['profile-evidence'] })} />;
  }
  if (query.isError) return <ErrorState message={(query.error as Error).message} />;
  if (!query.data) return <ErrorState message="画像证据为空。" />;

  const items = query.data.items;
  const needsReview = items.filter((item) => item.confidence < 0.55 || item.inaccurate_count > 0 || item.downrank_count > 0).length;
  const confirmed = items.reduce((sum, item) => sum + item.confirm_count, 0);
  const evidenceCount = items.reduce((sum, item) => sum + item.evidence_count, 0);

  function submitReview(id: number, action: ProfileReviewAction, note: string) {
    reviewMutation.mutate({ id, action, note });
  }

  return (
    <Shell
      eyebrow="Profile Evidence"
      title="画像证据链"
      meta="检查 ARC 为什么这样理解你，并把不贴切的画像标为降权或不准确"
      actions={
        <>
          <a className="secondary-link" href="/admin/weekly-report">画像复盘</a>
          <a className="secondary-link" href="/guided-reading/sources">书源管理</a>
        </>
      }
    >
      <section className="metric-grid">
        <Metric label="画像条目" value={items.length} suffix="条" />
        <Metric label="证据累计" value={evidenceCount} suffix="条" />
        <Metric label="已确认" value={confirmed} suffix="次" />
        <Metric label="需关注" value={needsReview} suffix="项" />
      </section>

      <section className="evidence-list">
        {items.length === 0 ? (
          <div className="empty-panel">
            <h2>暂无画像证据</h2>
            <p>产生推荐反馈并执行日常任务后，这里会显示 ARC/Hermes 形成画像的依据。</p>
          </div>
        ) : (
          items.map((item) => <EvidenceCard key={item.id} item={item} onReview={submitReview} pending={reviewMutation.isPending} />)
        )}
      </section>
    </Shell>
  );
}

function Metric({ label, value, suffix }: { label: string; value: number; suffix: string }) {
  return (
    <div className="metric-card">
      <span>{label}</span>
      <strong>
        {value}
        <small>{suffix}</small>
      </strong>
    </div>
  );
}

function EvidenceCard({
  item,
  onReview,
  pending,
}: {
  item: ProfileEvidenceItem;
  onReview: (id: number, action: ProfileReviewAction, note: string) => void;
  pending: boolean;
}) {
  const topEvidence = useMemo(() => item.evidence.slice().reverse().slice(0, 4), [item.evidence]);

  function submit(event: FormEvent<HTMLFormElement>, action: ProfileReviewAction) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    onReview(item.id, action, String(form.get('note') || ''));
    event.currentTarget.reset();
  }

  return (
    <article className="evidence-card">
      <div className="evidence-main">
        <div className="evidence-title-row">
          <span className="category-pill">{categoryLabels[item.category] ?? item.category}</span>
          <span className="evidence-time">更新 {formatDate(item.updated_at)}</span>
        </div>
        <h2>{item.content}</h2>
        <div className="score-row">
          <Score icon={<Gauge size={16} />} label="权重" value={item.weight} />
          <Score icon={<ShieldCheck size={16} />} label="置信度" value={item.confidence} />
          <span className="score-chip">
            <History size={16} />
            证据 {item.evidence_count}
          </span>
        </div>

        <div className="evidence-block">
          <h3>证据</h3>
          {topEvidence.length === 0 ? (
            <p className="muted-line">暂无结构化证据。</p>
          ) : (
            <div className="evidence-snippets">
              {topEvidence.map((evidence, index) => (
                <EvidenceSnippet key={`${item.id}-${index}`} evidence={evidence} />
              ))}
            </div>
          )}
        </div>
      </div>

      <aside className="review-panel">
        <div className="review-summary">
          <span>
            <BadgeCheck size={16} />
            确认 {item.confirm_count}
          </span>
          <span>
            <CircleAlert size={16} />
            不准确 {item.inaccurate_count}
          </span>
          <span>
            <RotateCcw size={16} />
            降权 {item.downrank_count}
          </span>
        </div>
        {item.latest_review ? (
          <p className="latest-review">
            最近：{actionLabels[item.latest_review.action]} {item.latest_review.note ? `- ${item.latest_review.note}` : ''}
          </p>
        ) : (
          <p className="latest-review">还没有人工确认。</p>
        )}
        {(['confirm', 'downrank', 'inaccurate'] as ProfileReviewAction[]).map((action) => (
          <form className="review-form" key={action} onSubmit={(event) => submit(event, action)}>
            <input name="note" placeholder={action === 'confirm' ? '可选备注' : '说明为什么不贴切'} maxLength={500} />
            <button type="submit" disabled={pending} className={action === 'confirm' ? 'confirm' : action}>
              {actionLabels[action]}
            </button>
          </form>
        ))}
      </aside>
    </article>
  );
}

function Score({ icon, label, value }: { icon: ReactNode; label: string; value: number }) {
  return (
    <span className="score-chip">
      {icon}
      {label} {(value * 100).toFixed(0)}%
    </span>
  );
}

function EvidenceSnippet({ evidence }: { evidence: Record<string, unknown> }) {
  const title = String(evidence.book || evidence.theme || evidence.content || evidence.source || '证据');
  const details = [
    evidence.feedback_type ? `反馈：${evidence.feedback_type}` : '',
    evidence.reason_code ? `原因：${evidence.reason_code}` : '',
    evidence.free_text ? `备注：${evidence.free_text}` : '',
    evidence.profile_mapping ? `画像映射：${evidence.profile_mapping}` : '',
  ].filter(Boolean);
  const rest = Object.entries(evidence)
    .filter(([key]) => !['book', 'theme', 'content', 'source', 'feedback_type', 'reason_code', 'free_text', 'profile_mapping'].includes(key))
    .slice(0, 4);

  return (
    <div className="evidence-snippet">
      <strong>{title}</strong>
      {details.map((detail) => (
        <p key={detail}>{detail}</p>
      ))}
      {rest.length > 0 ? (
        <div className="evidence-tags">
          {rest.map(([key, value]) => (
            <span key={key}>
              {key}: {String(value)}
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function formatDate(value: string) {
  if (!value) return '-';
  return value.replace('T', ' ').slice(0, 16);
}
