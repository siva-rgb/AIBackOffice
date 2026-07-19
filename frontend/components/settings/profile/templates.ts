// Single source of truth for the business-type-driven profile UI.
// Business type decides which domain tabs surface (the "clear distinction"
// between a freelancer and an agency). Mirrors the backend weighting in
// services/profile_context.py (_TYPE_SECTIONS).
import type { BusinessType } from '@/lib/api/types';

export type TabKey =
  | 'identity'
  | 'brand'
  | 'offerings'
  | 'customers'
  | 'operations'
  | 'marketing'
  | 'legalFinancial';

export const TAB_LABELS: Record<TabKey, string> = {
  identity: 'Identity',
  brand: 'Brand',
  offerings: 'Offerings',
  customers: 'Customers',
  operations: 'Operations',
  marketing: 'Marketing',
  legalFinancial: 'Legal & finance',
};

const ALL: TabKey[] = [
  'identity', 'brand', 'offerings', 'customers', 'operations', 'marketing', 'legalFinancial',
];

// Everyone gets identity/brand/offerings/customers/legalFinancial; operations &
// marketing unlock by type. Unknown/empty type → show everything (nothing hidden
// before the owner picks a type).
export const TYPE_TABS: Record<BusinessType, TabKey[]> = {
  freelancer: ['identity', 'brand', 'offerings', 'customers', 'legalFinancial'],
  online_seller: ['identity', 'brand', 'offerings', 'customers', 'marketing', 'legalFinancial'],
  small_business: ALL,
  agency: ALL,
  startup: ALL,
};

export function visibleTabs(businessType: string | null | undefined): TabKey[] {
  if (businessType && businessType in TYPE_TABS) {
    return TYPE_TABS[businessType as BusinessType];
  }
  return ALL;
}

export const BUSINESS_TYPES: [BusinessType, string][] = [
  ['freelancer', 'Freelancer / solo services'],
  ['online_seller', 'Online / marketplace seller'],
  ['small_business', 'Small business (with a team)'],
  ['agency', 'Agency'],
  ['startup', 'Startup'],
];

export const CURRENCIES = ['USD', 'EUR', 'GBP', 'CAD', 'AUD', 'INR', 'SGD', 'AED'];
export const TONES = ['friendly', 'professional', 'concise', 'formal'];

export const inputCls =
  'w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-kora-500 focus:outline-none focus:ring-1 focus:ring-kora-500';

// Comma-separated <-> string[] helpers for list fields.
export const toList = (s: string) => s.split(',').map((x) => x.trim()).filter(Boolean);
export const fromList = (a: string[] | null | undefined) => (a ?? []).join(', ');
