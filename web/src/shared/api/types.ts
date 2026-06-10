export type ReadingPack = {
  id: number;
  recommendation_id: number;
  token: string;
  title: string;
  book: { title: string; author: string };
  status: string;
  generator_provider: string;
  artifact_path: string;
  recommendation: {
    theme: string;
    reason: string;
    hypothesis: string;
    expected_benefit: string;
    risk: string;
    reading_suggestion: string;
  };
  modules: Array<{ slug: string; label: string; description: string; path: string; active: boolean }>;
  current_module: string;
  current_index: number;
  progress_percent: number;
  sections: Array<{ title: string; body: unknown[]; minutes: number }>;
  feedback_options: Array<{
    type: string;
    label: string;
    reasons: Array<{ code: string; label: string; token: string }>;
  }>;
  quotes: ReadingQuote[];
};

export type ReadingQuote = {
  id: number;
  reading_pack_id: number;
  recommendation_id: number;
  book_id: number;
  book: { title: string; author: string };
  reading_pack_title: string;
  selected_text: string;
  note: string;
  module: string;
  section_title: string;
  source_surface: string;
  created_at: string;
};

export type ReadingQuotesResponse = {
  items: ReadingQuote[];
};

export type GuidedDay = {
  id: number;
  plan_id: number;
  token: string;
  day_number: number;
  total_days: number;
  progress_percent: number;
  estimated_minutes: number;
  status: string;
  mode: string;
  tone: string;
  spoiler_policy: string;
  book: { title: string; author: string };
  artifact_path: string;
  content: {
    hook: string;
    one_question: string;
    plain_explanation: string;
    key_points: string[];
    reality_connection: string;
    why_it_matters: string;
    tomorrow_teaser: string;
  };
  source_paragraphs: string[];
  days: Array<{ id: number; day_number: number; token: string; scheduled_date: string; estimated_minutes: number; status: string }>;
};

export type ReadingPlan = {
  id: number;
  title: string;
  book_title: string;
  book_author: string;
  mode: string;
  tone: string;
  spoiler_policy: string;
  plan_days: number;
  daily_minutes: number;
  lark_push_enabled: boolean;
  status: string;
  created_at: string;
  updated_at: string;
};

export type ReadingSource = {
  id: number;
  title: string;
  author: string;
  original_filename: string;
  file_format: string;
  status: string;
  char_count: number;
  sha256: string;
  created_at: string;
  updated_at: string;
  preview?: string;
};

export type WeeklyReport = {
  days: number;
  metrics: {
    recommendation_count: number;
    feedback_total: number;
    positive_total: number;
    hit_rate: number;
  };
  user_summary: string[];
  writeback_status: string[];
  profile_sections: {
    stable: string[];
    pending: string[];
    new: string[];
    misunderstood: string[];
  };
  enhanced_dimensions: string[];
  misunderstandings: string[];
  recent_free_texts: string[];
  next_directions: string[];
  report_text: string;
};

export type ProfileReviewAction = 'confirm' | 'inaccurate' | 'downrank';

export type ProfileReviewEvent = {
  id: number;
  profile_item_id: number;
  action: ProfileReviewAction;
  note: string;
  previous_weight: number;
  previous_confidence: number;
  new_weight: number;
  new_confidence: number;
  created_at: string;
};

export type ProfileEvidenceItem = {
  id: number;
  category: string;
  content: string;
  weight: number;
  confidence: number;
  evidence_count: number;
  evidence: Array<Record<string, unknown>>;
  created_at: string;
  updated_at: string;
  last_seen_at: string;
  review_count: number;
  confirm_count: number;
  inaccurate_count: number;
  downrank_count: number;
  latest_review: Pick<ProfileReviewEvent, 'action' | 'note' | 'created_at'> | null;
  reviews: ProfileReviewEvent[];
};

export type ProfileEvidenceResponse = {
  items: ProfileEvidenceItem[];
};

export type ProfileEvidenceReviewResponse = {
  item: ProfileEvidenceItem;
  event: ProfileReviewEvent;
};
