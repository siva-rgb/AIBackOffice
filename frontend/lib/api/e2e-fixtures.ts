/**
 * Static fixture data returned by serverGet() when KORA_E2E_MOCK=true.
 * Keyed by the path passed to serverGet (e.g. '/api/invoices').
 * Only the paths exercised by E2E tests need entries here.
 */

const FIXTURES: Record<string, unknown> = {
  '/api/invoices': [
    {
      id: 'inv-001',
      invoiceNumber: 'INV-001',
      clientName: 'Acme Corp',
      clientEmail: 'acme@example.com',
      lineItems: [],
      subtotal: 2500,
      taxRate: 0,
      taxAmount: 0,
      total: 2500,
      currency: 'USD',
      status: 'sent',
      dueDate: '2099-12-31',
      followUpCount: 0,
      createdAt: '2026-01-01T00:00:00Z',
    },
  ],
  '/api/agents/log': [],
  '/api/bookkeeping/transactions': [
    {
      id: 'tx-001',
      date: '2026-01-15',
      description: 'Client payment',
      amount: 5000,
      currency: 'USD',
      type: 'income',
      category: 'revenue',
      subcategory: null,
      taxDeductible: false,
      aiConfidence: 0.95,
      aiCategorized: true,
    },
    {
      id: 'tx-002',
      date: '2026-01-20',
      description: 'Software subscription',
      amount: -99,
      currency: 'USD',
      type: 'expense',
      category: 'software',
      subcategory: null,
      taxDeductible: true,
      aiConfidence: 0.88,
      aiCategorized: true,
    },
  ],
  '/api/bookkeeping/pnl': {
    totalIncome: 5000,
    totalExpenses: 99,
    netProfit: 4901,
    profitMargin: 98,
    incomeByCategory: { revenue: 5000 },
    expenseByCategory: { software: 99 },
    deductibleExpenses: 99,
    count: 2,
  },
};

export function getE2EFixture(path: string): unknown {
  if (path in FIXTURES) return FIXTURES[path];
  // Unknown path — return empty array so pages don't crash
  return [];
}
