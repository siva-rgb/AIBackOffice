// Mirror of the FastAPI backend's camelCase JSON responses.

export interface Transaction {
  id: string;
  date: string;
  description: string;
  amount: number;
  currency: string;
  type: 'income' | 'expense';
  category: string | null;
  subcategory: string | null;
  taxDeductible: boolean;
  aiConfidence: number | null;
  aiCategorized: boolean;
}

export interface Pnl {
  totalIncome: number;
  totalExpenses: number;
  netProfit: number;
  profitMargin: number;
  incomeByCategory: Record<string, number>;
  expenseByCategory: Record<string, number>;
  deductibleExpenses: number;
  count: number;
}

export interface LineItem {
  description: string;
  quantity: number;
  rate: number;
  amount: number | null;
}

export interface Invoice {
  id: string;
  invoiceNumber: string;
  clientId?: string | null;
  clientName: string;
  clientEmail: string;
  lineItems: LineItem[];
  subtotal: number;
  taxRate: number;
  taxAmount: number;
  total: number;
  currency: string;
  status: string;
  dueDate: string;
  notes?: string | null;
  paymentLink?: string | null;
  contractId?: string | null;
  sentAt?: string | null;
  paidAt?: string | null;
  followUpCount: number;
  lastFollowUpAt?: string | null;
  // Invoice enhancements
  invoiceDate?: string | null;
  paymentTerms?: string | null;
  paymentTermsDays?: number | null;
  clientAddress?: string | null;
  clientTaxId?: string | null;
  poNumber?: string | null;
  pdfPath?: string | null;
  emailMessageId?: string | null;
  amountPaid?: number;
}

export interface AgentLog {
  id: string;
  agentType: string;
  action: string;
  triggeredBy: string;
  status: string;
  modelUsed: string;
  tokensUsed: number | null;
  latencyMs: number | null;
  costUsd: number | null;
  createdAt: string;
  input: unknown;
  output: unknown;
  sourceRecordId: string | null;
}

export interface Alert {
  id: string;
  type: string;
  severity: 'info' | 'warning' | 'critical';
  title: string;
  body: string;
  actionLabel: string | null;
  actionUrl: string | null;
  read: boolean;
}

export interface AgentStats {
  total: number;
  today: number;
  thisWeek: number;
  byType: Record<string, number>;
  byTrigger: Record<string, number>;
  successRate: number;
  avgLatencyMs: number;
  totalCostUsd: number;
}

export interface Contract {
  id: string;
  type: string;
  title: string | null;
  clientName: string;
  clientEmail: string | null;
  providerName: string | null;
  jurisdiction: string;
  terms: Record<string, unknown>;
  contentMd: string | null;
  sectionExplanations: Record<string, string>;
  status: string;
  signedAt: string | null;
  createdAt: string;
}

// Canonical business types — drives which profile sections surface (templates.ts).
export type BusinessType =
  | 'freelancer'
  | 'online_seller'
  | 'small_business'
  | 'agency'
  | 'startup';

// --- Six-domain nested profile (v2) ---
export interface BrandIdentity {
  mission: string | null;
  vision: string | null;
  values: string[];
  usp: string | null;
  voice: string | null;
  colors: string[];
  logoUrl: string | null;
  styleGuidelines: string | null;
}

export interface Offering {
  name: string | null;
  description: string | null;
  pricing: string | null;
  packages: string[];
  deliveryProcess: string | null;
  guarantees: string | null;
}

export interface BuyerPersona {
  name: string | null;
  description: string | null;
  painPoints: string[];
  goals: string[];
}

export interface Customers {
  buyerPersonas: BuyerPersona[];
  industriesServed: string[];
  locations: string[];
  painPoints: string[];
  goals: string | null;
}

export interface TeamMember {
  name: string | null;
  role: string | null;
}

export interface Operations {
  teamMembers: TeamMember[];
  workingHours: string | null;
  tools: string[];
  workflows: string | null;
  sops: string[];
}

export interface SocialAccount {
  platform: string | null;
  handle: string | null;
  url: string | null;
}

export interface Marketing {
  competitors: string[];
  channels: string[];
  socialAccounts: SocialAccount[];
  testimonials: string[];
  caseStudies: string[];
  salesScripts: string[];
}

export interface LegalFinancial {
  registrationDetails: string | null;
  taxInfo: string | null;
  invoicingPreferences: string | null;
  paymentMethods: string[];
  contractNotes: string | null;
}

export interface BusinessProfile {
  displayName: string | null;
  roleTitle: string | null;
  phone: string | null;
  businessType: BusinessType | string | null;
  industry: string | null;
  description: string | null;
  website: string | null;
  foundedYear: number | null;
  address: string | null;
  timezone: string | null;
  services: string[];
  targetClients: string | null;
  defaultPaymentTermsDays: number | null;
  defaultHourlyRate: number | null;
  typicalProjectValue: number | null;
  invoicePrefix: string | null;
  taxId: string | null;
  defaultTaxRate: number | null;
  paymentMethods: string[];
  monthlyRevenueGoal: number | null;
  annualRevenueGoal: number | null;
  financialGoals: string | null;
  businessPriorities: string[];
  brandTone: string | null;
  // Invoice enhancements
  businessAddress: string | null;
  invoiceFooter: string | null;
  // Notification preferences (owner emails — opt-out, default on)
  notifyDailyDigest?: boolean;
  notifyCriticalAlerts?: boolean;
  // Six-domain nested profile (v2 — additive)
  brand?: BrandIdentity;
  offerings?: Offering[];
  customers?: Customers;
  operations?: Operations;
  marketing?: Marketing;
  legalFinancial?: LegalFinancial;
}

export interface ProfileCompleteness {
  percent: number;
  sections: Record<string, boolean>;
}

// --- Agent graph memory (kg_nodes / kg_edges) ---
export interface KgNode {
  id: string;
  nodeType: string;
  entityId: string | null;
  label: string;
  props: Record<string, any>;
  salience: number;
}

export interface KgEdge {
  id: string;
  srcId: string;
  dstId: string;
  rel: string;
  weight: number;
  props: Record<string, any>;
}

export interface KgGraph {
  nodes: KgNode[];
  edges: KgEdge[];
}

// --- Semantic / hybrid memory recall (agent_memory) ---
export interface MemoryHit {
  content: string;
  kind: string;
  clientId: string | null;
  source: string | null;
  score: number;
  similarity: number | null; // null when embeddings are off (lexical-only)
  lexical: number;
}

export interface MemoryRecallResult {
  query: string;
  results: MemoryHit[];
}

// --- Task / project ledger ---
export type TaskStatus = 'todo' | 'in_progress' | 'blocked' | 'done' | 'cancelled';
export type TaskPriority = 'low' | 'medium' | 'high' | 'urgent';
export type TaskSource = 'manual' | 'meeting' | 'email' | 'contract' | 'agent' | 'notion';

export interface Task {
  id: string;
  clientId: string | null;
  engagementId: string | null;
  title: string;
  descriptionMd: string | null;
  status: TaskStatus;
  priority: TaskPriority;
  dueDate: string | null;
  owner: string | null;
  source: TaskSource;
  externalUrl: string | null;
  completedAt: string | null;
  createdAt: string;
  updatedAt: string | null;
}

// Shape returned inside the Butler client detail (adds a computed `overdue`).
export interface ClientTask {
  id: string;
  title: string;
  status: TaskStatus;
  priority: TaskPriority;
  dueDate: string | null;
  owner: string | null;
  source: TaskSource;
  overdue: boolean;
}

export interface TaskStats {
  total: number;
  open: number;
  overdue: number;
  blocked: number;
  dueToday: number;
  done: number;
}

export interface MemoryStats {
  total: number;
  embedded: number;
  embeddingsEnabled: boolean;
  byKind: Record<string, number>;
}

export interface Me {
  id: string;
  email: string;
  fullName: string | null;
  businessName: string | null;
  country: string;
  currency: string;
  plan: string;
  onboardingCompleted: boolean;
  profile: BusinessProfile;
  googleConnected: boolean;
  googleEmail: string | null;
  createdAt: string;
}

export interface ManagerTask {
  id: string;
  kind: string;
  title: string;
  rationale: string;
  severity: 'info' | 'warning' | 'critical';
  status: string;
  payload: Record<string, unknown>;
  createdAt: string;
}

export interface ManagerStats {
  overdueCount: number;
  overdueTotal: number;
  openInvoices: number;
  unsignedContracts: number;
  cashDangerDays: number | null;
  currentBalance: number | null;
  currency: string;
}

export interface GoalProgress {
  monthIncome: number;
  monthlyGoal: number | null;
}

export interface Advisory {
  kind: string;
  severity: 'info' | 'warning' | 'critical';
  title: string;
  detail: string;
}

export interface ManagerSnapshot {
  goalProgress: GoalProgress;
  stats: ManagerStats;
  advisories: Advisory[];
  pendingTasks: ManagerTask[];
  lastBriefing: ManagerBriefing | null;
  lastRunAt: string | null;
}

export interface SuggestedAction {
  label: string;
  kind: string;
}

export interface ChatReply {
  reply: string;
  suggestedActions: SuggestedAction[];
  queued?: number;
}

export interface ManagerBriefing {
  statusLine: string;
  summary: string;
  priorities: string[];
}

export interface ManagerRun {
  briefing: ManagerBriefing;
  goalProgress: GoalProgress;
  stats: ManagerStats;
  autoActions: string[];
  advisories: Advisory[];
  pendingTasks: ManagerTask[];
  ranAt: string;
}

export interface ReviewFinding {
  title: string;
  severity: 'high' | 'medium' | 'low';
  category: string | null;
  issue: string;
  recommendation: string | null;
  clauseReference: string | null;
}

export interface ContractReview {
  overallRisk: 'high' | 'medium' | 'low';
  summary: string;
  findings: ReviewFinding[];
  missingClauses: string[];
  favorablePoints: string[];
  source: string;
  title: string | null;
  reviewedAt: string;
}

export interface ForecastPoint {
  date: string;
  expected: number;
  optimistic: number;
  conservative: number;
}

export interface Forecast {
  currentBalance: number;
  horizonDays: number;
  forecast: ForecastPoint[];
  keyRisks: string[];
  recommendedActions: string[];
  confidenceScore: number;
  assumptions: string[];
  dangerExpected30d: number | null;
  dangerConservative14d: number | null;
}

export interface Overview {
  user: { fullName: string | null; businessName: string | null; currency: string };
  monthIncome: number;
  outstanding: number;
  overdueCount: number;
  agentStats: AgentStats;
  unreadAlerts: Alert[];
  recentActivity: AgentLog[];
}

// --- Butler / AI business partner ------------------------------------------
export interface ClientFinancials {
  invoiced: number;
  paid: number;
  outstanding: number;
  overdueCount: number;
  overdueTotal: number;
}

export interface Client {
  id: string;
  name: string;
  email?: string | null;
  contactEmails?: string[] | null;
  phone?: string | null;
  company?: string | null;
  industry?: string | null;
  clientType: 'individual' | 'company' | 'agency' | 'marketplace';
  status: 'active' | 'inactive' | 'prospect' | 'churned';
  whatWeDo?: string | null;
  notesMd?: string | null;
  currency: string;
  healthScore: number;
  healthLabel: 'on_track' | 'at_risk' | 'needs_attention' | 'critical';
  lastActivityAt?: string | null;
  createdAt: string;
  // Invoice-related (invoice_artifact)
  billingAddress?: string | null;
  taxId?: string | null;
  // enriched (list)
  financials?: ClientFinancials;
  activeEngagementCount?: number;
  daysSinceActivity?: number | null;
}

export interface Engagement {
  id: string;
  clientId: string;
  title: string;
  descriptionMd?: string | null;
  engagementType: 'project' | 'retainer' | 'one_off' | 'ongoing';
  status: 'planning' | 'active' | 'on_track' | 'at_risk' | 'paused' | 'done' | 'cancelled';
  startDate?: string | null;
  targetEndDate?: string | null;
  budget?: number | null;
  valueDelivered: number;
  contractId?: string | null;
  createdAt: string;
}

export interface ClientNote {
  id: string;
  clientId: string;
  engagementId?: string | null;
  noteType: 'meeting' | 'call' | 'email' | 'decision' | 'blocker' | 'update' | 'general';
  contentMd: string;
  isAiGenerated: boolean;
  createdAt: string;
}

export interface ClientDetail extends Client {
  financials: ClientFinancials;
  healthRisks: string[];
  healthPositives: string[];
  engagements: Engagement[];
  notes: ClientNote[];
  invoices: { id: string; invoiceNumber: string; total: number; status: string; dueDate: string }[];
  contracts: { id: string; title: string; type: string; status: string }[];
  proposals: { id: string; title: string; totalAmount: number; status: string }[];
  retainers: { id: string; title: string; amount: number; billingCycle: string; status: string }[];
  tasks?: ClientTask[];
  openTaskCount?: number;
  graphFacts?: { rel: string; label: string }[];
}

// ── Story layer (M1) + roll-up (M2) + composed view (M3) ───────────────────
export type StoryStatus = 'todo' | 'in_progress' | 'blocked' | 'done' | 'cancelled';
export type ObservationKind = 'blocker' | 'going_well' | 'not_going_well';
export type EvidenceSource = 'email' | 'meeting' | 'drive' | 'task' | 'invoice' | 'agent' | 'user';
export type HealthLabel = 'on_track' | 'at_risk' | 'needs_attention' | 'critical';

export interface StoryObservation {
  id: string;
  kind: ObservationKind;
  text: string;
  source: EvidenceSource;
  sourceRef: string;      // the email / meeting / doc this judgement came from
  observedAt: string;
  userEdited: boolean;
}

export interface Story {
  id: string;
  taskId: string;
  clientId: string | null;
  engagementId: string | null;
  title: string;
  descriptionMd: string | null;
  status: StoryStatus;
  progressPct: number;
  observations: StoryObservation[];
  completedAt: string | null;
  createdAt: string;
  updatedAt: string | null;
}

// One task's roll-up (M2). Health numbers are computed server-side only.
export interface TaskRollup {
  taskId: string;
  title: string;
  status: TaskStatus;
  progressPct: number;
  storyCount: number;
  openStoryCount: number;
  doneStoryCount: number;
  blockerCount: number;
  notGoingWellCount: number;
  goingWellCount: number;
  stalledCount: number;
  isOverdue: boolean;
}

// A project (engagement) roll-up, or the whole-client roll-up — same shape.
export interface RollupScore {
  score: number;
  label: HealthLabel;
  progressPct: number;
  taskCount: number;
  storyCount: number;
  blockerCount: number;
  notGoingWellCount: number;
  goingWellCount: number;
  overdueCount: number;
  stalledCount: number;
  risks: string[];
  positives: string[];
  hasData: boolean;
}

export interface ProjectNode extends RollupScore {
  engagementId: string;
  title: string;
  status: string;
  tasks: TaskRollup[];
}

export interface ClientTree extends RollupScore {
  clientId: string;
  projects: ProjectNode[];
  unassignedTasks: TaskRollup[];
}

// Composed one-pager (M3). Numbers come from the ledger; prose from analysts.
export interface ClientViewSection {
  metrics: Record<string, unknown>;
  summary: string;
  highlights: string[];
  concerns: string[];
  degraded: boolean;
}

export interface ClientView {
  clientId: string;
  clientName: string;
  headline: {
    healthScore: number;
    healthLabel: string;
    progressPct: number;
    outstanding: number;
    openBlockers: number;
  };
  sections: {
    delivery: ClientViewSection;
    money: ClientViewSection;
    relationship: ClientViewSection;
    risk: ClientViewSection;
  };
  degradedSections: string[];
  generatedAt: string | null;
  stale: boolean;
  refreshedAt?: string | null;
  tokenCost?: { totalTokens?: number; estUsd?: number; withinCap?: boolean };
}

export interface QuickCapture {
  id: string;
  rawText: string;
  source: string;
  parseStatus: 'pending' | 'parsed' | 'failed' | 'partial';
  parsedIntent?: string | null;
  parsedEntities: Record<string, unknown>;
  aiConfidence?: number | null;
  actionsTaken: Record<string, unknown>[];
  requiresReview: boolean;
  createdAt: string;
}

export interface ButlerBriefing {
  headline: string;
  twoSentenceSummary: string;
  keyInsight: string;
  focusToday: string[];
  goingWell: string;
  watchOut: string;
  tone: 'energetic' | 'steady' | 'cautious';
}

export interface ButlerSnapshot {
  memory: Record<string, unknown>;
  lastBriefing?: ButlerBriefing | null;
  lastBriefingAt?: string | null;
  stats: {
    clientCount: number;
    activeEngagements: number;
    atRiskEngagements: number;
    overdueCount: number;
    overdueTotal: number;
    currency: string;
  };
  reviewQueueCount: number;
}

export interface ButlerRun {
  briefing: ButlerBriefing;
  ranAt: string;
}

export interface Proposal {
  id: string;
  clientId?: string | null;
  title: string;
  proposalNumber?: string | null;
  scopeMd?: string | null;
  contentMd?: string | null;
  sectionExplanations: Record<string, string>;
  totalAmount: number;
  currency: string;
  pricingType: 'fixed' | 'hourly' | 'retainer' | 'milestone';
  paymentTerms?: string | null;
  status: 'draft' | 'sent' | 'viewed' | 'accepted' | 'declined' | 'expired';
  validUntil?: string | null;
  contractId?: string | null;
  createdAt: string;
}

export interface Retainer {
  id: string;
  clientId?: string | null;
  clientName?: string | null;
  title: string;
  amount: number;
  currency: string;
  billingCycle: 'weekly' | 'monthly' | 'quarterly' | 'annual';
  startDate: string;
  endDate?: string | null;
  nextInvoiceDate?: string | null;
  status: 'active' | 'paused' | 'cancelled';
  autoInvoice: boolean;
}

export interface PlaybookEntry {
  id: string
  userId: string
  category: 'correction' | 'user_preference' | 'client_intelligence' | 'business_pattern' | 'business_rule' | 'extracted_fact'
  clientId: string | null
  key: string
  value: Record<string, unknown>
  summary: string | null
  confidence: number
  source: 'onboarding' | 'observation' | 'correction' | 'extraction' | 'pattern_detection'
  observationCount: number
  firstObservedAt: string | null
  lastObservedAt: string | null
  expiresAt: string | null
}

export interface PlaybookStats {
  total: number
  corrections: number
  highConfidence: number
  patterns: number
  byCategory: Record<string, number>
}

// --- Calendar ----------------------------------------------------------------

export interface CalendarEvent {
  id: string
  title: string
  start: string
  meetLink: string | null
  clientNames: string[]
  isClientMeeting: boolean
}

export interface CalendarSlot {
  start: string
  end: string
  label: string
}

export interface UnloggedMeeting {
  eventId: string
  title: string
  date: string
  clientNames: string[]
  clientIds: string[]
}

// --- Email Intel -------------------------------------------------------------

export interface EmailIntel {
  clientId: string
  clientName: string
  sentiment: string
  relationshipHealth: string
  summary: string
  actionNeeded: boolean
  actionDescription: string | null
  lastContactDays: number
  lastContactDirection: string
  commitmentsPending: unknown[]
  openQuestions: unknown[]
  processedAt: string
}

// --- Meetings ----------------------------------------------------------------

export interface MeetingActionItem {
  id: string
  description: string
  owner: string
  dueDate: string | null
  priority: string
  status: string
}

export interface DriveDoc {
  driveFileId: string
  fileName: string | null
  docType: string | null
  mimeType: string | null
  processedAt: string | null
  meetingId: string | null
  clientId: string | null
}

export interface Meeting {
  id: string
  clientId: string | null
  title: string
  meetingDate: string
  meetingType: string
  durationMinutes: number | null
  source: string
  parseStatus: string
  summary: string | null
  decisions: Array<{ decision: string; owner: string | null }>
  commitments: Array<{ who: string; what: string; byWhen: string | null; amount: string | null }>
  risksFlagged: Array<{ risk: string; severity: string }>
  nextSteps: Array<{ action: string; owner: string; byWhen: string | null; priority: string }>
  sentiment: string
  aiConfidence: number
  createdAt: string
  clients: { name: string } | null
  meetingActionItems: MeetingActionItem[]
}
