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
