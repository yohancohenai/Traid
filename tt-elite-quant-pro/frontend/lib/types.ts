export type Freshness = "VERIFIED" | "STALE" | "UNAVAILABLE" | string;
export type RecStatus = "QUALIFIES" | "WATCH" | "PASS" | string;

export interface Health {
  status: string;
  time: string;
  version: string;
  db?: string;
  live_matches_in_db?: number;
  demo_matches_in_db?: number;
  redis?: string;
}

export interface Meta {
  timezone: string;
  region: string;
  primary_book: string;
  reference_books: string[];
  demo_enabled: boolean;
  max_quote_age_seconds: number;
  disclaimer: string;
}

export interface PlayerRef {
  id: number;
  name: string;
}

export interface MatchBrief {
  id: number;
  player1: PlayerRef;
  player2: PlayerRef;
  scheduled_at: string;
  status: string;
  sets_p1: number | null;
  sets_p2: number | null;
  is_demo: boolean;
  competition: string | null;
  tournament: string | null;
  result_verified: boolean;
  data_quality: string | null;
  set_scores: [number, number][];
  live_state: { sets?: number[]; points?: number[]; [k: string]: unknown } | null;
  live_updated_at: string | null;
  finished_at: string | null;
}

export interface Quote {
  id: number;
  bookmaker: string;
  market: string;
  selection: string;
  line: number | null;
  american: number | null;
  decimal: number;
  quoted_at: string;
  captured_at: string;
  source: string;
  availability: string;
  is_closing: boolean;
  settlement_rules: string | null;
  is_demo: boolean;
  freshness: Freshness;
  age_seconds: number;
  executable: boolean;
  executable_note: string | null;
}

export interface MatchWithPred extends MatchBrief {
  prediction: { p1_win: number; p1_ci: [number, number]; data_quality: string; as_of: string } | null;
  hardrock: Record<string, Quote>;
}

export interface FairOdds {
  decimal: number;
  american: number;
}

export interface Recommendation {
  id: number;
  match: MatchBrief;
  market: string;
  selection: string;
  selection_name: string;
  line: number | null;
  sportsbook: string;
  decimal_odds: number | null;
  american_odds: number | null;
  quote: Quote | null;
  quote_status: Freshness;
  model_prob: number;
  prob_interval: [number | null, number | null];
  break_even: number | null;
  ev: number | null;
  ev_low: number | null;
  edge: number | null;
  novig_prob: number | null;
  fair_odds: FairOdds | null;
  data_quality: string | null;
  model_agreement: { spread?: number; components?: Record<string, number> } | null;
  reasons_for: string[] | null;
  reasons_against: string[] | null;
  filters: Record<string, boolean> | null;
  status: RecStatus;
  status_at_scan: RecStatus;
  user_action: string;
  created_at: string;
  is_demo: boolean;
  hypothetical_result: string | null;
}

export interface Prediction {
  id: number;
  created_at: string;
  as_of: string;
  p1_win: number;
  p2_win: number;
  p1_ci: [number, number];
  p_game: number | null;
  scorelines: Record<string, number> | null;
  components: Record<string, number> | null;
  data_quality: string;
  model_version_id: number | null;
  fair_p1: FairOdds;
  fair_p2: FairOdds;
  features: Record<string, unknown> | null;
  is_demo: boolean;
}

export interface BetRow {
  id: number;
  placed_at: string;
  settled_at: string | null;
  status: string;
  market: string;
  selection: string;
  line: number | null;
  stake: number;
  decimal: number;
  american: number | null;
  net: number | null;
  ev: number | null;
  clv: number | null;
  model_version_id: number | null;
  player: string;
  match: string;
  match_id: number;
  scheduled_at: string;
  bet_ref: string | null;
  notes: string | null;
  potential_payout: number;
  potential_profit: number;
  is_demo: boolean;
}

export interface GroupRow {
  key: string;
  bets: number;
  staked: number;
  net: number;
  won: number;
  lost: number;
  roi: number | null;
}

export interface Summary {
  ledger: string;
  total_bets: number;
  pending: number;
  pending_exposure: number;
  wins: number;
  losses: number;
  pushes: number;
  voids: number;
  in_review: number;
  win_pct: number | null;
  total_wagered: number;
  total_returned: number;
  net_pl: number;
  roi: number | null;
  avg_decimal: number | null;
  avg_ev_at_placement: number | null;
  avg_clv: number | null;
  clv_n: number;
  bankroll: number;
  bankroll_history: { at: string; balance: number; kind: string; amount: number }[];
  pl_curve: { at: string; cum_pl: number }[];
  max_drawdown: number;
  by_day: GroupRow[];
  by_week: GroupRow[];
  by_month: GroupRow[];
  by_player: GroupRow[];
  by_market: GroupRow[];
  by_odds: GroupRow[];
  by_model_version: GroupRow[];
}

export interface RiskSettings {
  bankroll_start: number;
  max_stake: number;
  max_event_exposure: number;
  max_daily_exposure: number;
  daily_loss_limit: number;
  kelly_fraction: number;
  fixed_stake: number;
  fixed_pct: number;
}

export interface Alert {
  id: number;
  created_at: string;
  kind: string;
  severity: string;
  title: string;
  body: string;
  read: boolean;
  is_demo: boolean;
}

export interface ReliabilityBin {
  bin: number;
  lo: number;
  hi: number;
  n: number;
  mean_pred: number | null;
  obs_rate: number | null;
}
