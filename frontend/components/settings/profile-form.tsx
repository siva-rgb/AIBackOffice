'use client';

import { useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Loader2, Check } from 'lucide-react';
import { Card, CardHeader } from '@/components/ui';
import { authedFetch } from '@/lib/api/browser';
import type { Me } from '@/lib/api/types';
import { Field, TextField, TextAreaField, RowsEditor } from './profile/fields';
import {
  BUSINESS_TYPES, CURRENCIES, TONES, inputCls, toList, fromList,
  visibleTabs, TAB_LABELS, type TabKey,
} from './profile/templates';

// Newline-separated <-> string[] (for longer list items like testimonials).
const toLines = (s: string) => s.split('\n').map((x) => x.trim()).filter(Boolean);
const fromLines = (a: string[] | null | undefined) => (a ?? []).join('\n');
const orNull = (s: string) => (s.trim() === '' ? null : s.trim());
const num = (s: string) => (s.trim() === '' ? null : Number(s));

type OfferingRow = { name: string; description: string; pricing: string; packages: string; deliveryProcess: string; guarantees: string };
type PersonaRow = { name: string; description: string; painPoints: string; goals: string };
type TeamRow = { name: string; role: string };
type SocialRow = { platform: string; handle: string; url: string };

export function ProfileForm({ me }: { me: Me }) {
  const router = useRouter();
  const p = me.profile ?? ({} as Me['profile']);

  // Core identity (users columns)
  const [fullName, setFullName] = useState(me.fullName ?? '');
  const [businessName, setBusinessName] = useState(me.businessName ?? '');
  const [country, setCountry] = useState(me.country ?? 'US');
  const [currency, setCurrency] = useState(me.currency ?? 'USD');

  // Flat profile fields (JSONB scalars)
  const [f, setF] = useState({
    displayName: p.displayName ?? '',
    roleTitle: p.roleTitle ?? '',
    phone: p.phone ?? '',
    businessType: p.businessType ?? '',
    industry: p.industry ?? '',
    description: p.description ?? '',
    website: p.website ?? '',
    foundedYear: p.foundedYear?.toString() ?? '',
    address: p.address ?? '',
    services: fromList(p.services),
    targetClients: p.targetClients ?? '',
    defaultPaymentTermsDays: p.defaultPaymentTermsDays?.toString() ?? '',
    defaultHourlyRate: p.defaultHourlyRate?.toString() ?? '',
    typicalProjectValue: p.typicalProjectValue?.toString() ?? '',
    invoicePrefix: p.invoicePrefix ?? '',
    taxId: p.taxId ?? '',
    defaultTaxRate: p.defaultTaxRate?.toString() ?? '',
    paymentMethods: fromList(p.paymentMethods),
    monthlyRevenueGoal: p.monthlyRevenueGoal?.toString() ?? '',
    annualRevenueGoal: p.annualRevenueGoal?.toString() ?? '',
    financialGoals: p.financialGoals ?? '',
    businessPriorities: fromList(p.businessPriorities),
    brandTone: p.brandTone ?? '',
    businessAddress: p.businessAddress ?? '',
    invoiceFooter: p.invoiceFooter ?? '',
  });
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
    setF((s) => ({ ...s, [k]: e.target.value }));

  const [notifyDailyDigest, setNotifyDailyDigest] = useState(p.notifyDailyDigest ?? true);
  const [notifyCriticalAlerts, setNotifyCriticalAlerts] = useState(p.notifyCriticalAlerts ?? true);

  // --- Six-domain nested state ---
  const b = p.brand ?? undefined;
  const [brand, setBrand] = useState({
    mission: b?.mission ?? '', vision: b?.vision ?? '', values: fromList(b?.values),
    usp: b?.usp ?? '', voice: b?.voice ?? '', colors: fromList(b?.colors),
    logoUrl: b?.logoUrl ?? '', styleGuidelines: b?.styleGuidelines ?? '',
  });
  const setB = (k: keyof typeof brand) => (v: string) => setBrand((s) => ({ ...s, [k]: v }));

  const [offerings, setOfferings] = useState<OfferingRow[]>(
    (p.offerings ?? []).map((o) => ({
      name: o.name ?? '', description: o.description ?? '', pricing: o.pricing ?? '',
      packages: fromList(o.packages), deliveryProcess: o.deliveryProcess ?? '', guarantees: o.guarantees ?? '',
    })),
  );

  const c = p.customers ?? undefined;
  const [customers, setCustomers] = useState({
    industriesServed: fromList(c?.industriesServed), locations: fromList(c?.locations),
    painPoints: fromList(c?.painPoints), goals: c?.goals ?? '',
  });
  const setC = (k: keyof typeof customers) => (v: string) => setCustomers((s) => ({ ...s, [k]: v }));
  const [personas, setPersonas] = useState<PersonaRow[]>(
    (c?.buyerPersonas ?? []).map((x) => ({
      name: x.name ?? '', description: x.description ?? '', painPoints: fromList(x.painPoints), goals: fromList(x.goals),
    })),
  );

  const o = p.operations ?? undefined;
  const [operations, setOperations] = useState({
    workingHours: o?.workingHours ?? '', tools: fromList(o?.tools), workflows: o?.workflows ?? '', sops: fromLines(o?.sops),
  });
  const setO = (k: keyof typeof operations) => (v: string) => setOperations((s) => ({ ...s, [k]: v }));
  const [team, setTeam] = useState<TeamRow[]>((o?.teamMembers ?? []).map((t) => ({ name: t.name ?? '', role: t.role ?? '' })));

  const m = p.marketing ?? undefined;
  const [marketing, setMarketing] = useState({
    competitors: fromList(m?.competitors), channels: fromList(m?.channels),
    testimonials: fromLines(m?.testimonials), caseStudies: fromLines(m?.caseStudies), salesScripts: fromLines(m?.salesScripts),
  });
  const setM = (k: keyof typeof marketing) => (v: string) => setMarketing((s) => ({ ...s, [k]: v }));
  const [socials, setSocials] = useState<SocialRow[]>(
    (m?.socialAccounts ?? []).map((s) => ({ platform: s.platform ?? '', handle: s.handle ?? '', url: s.url ?? '' })),
  );

  const lf = p.legalFinancial ?? undefined;
  const [legal, setLegal] = useState({
    registrationDetails: lf?.registrationDetails ?? '', taxInfo: lf?.taxInfo ?? '',
    invoicingPreferences: lf?.invoicingPreferences ?? '', contractNotes: lf?.contractNotes ?? '',
  });
  const setL = (k: keyof typeof legal) => (v: string) => setLegal((s) => ({ ...s, [k]: v }));

  // --- Tabs (type-driven) ---
  const tabs = useMemo(() => visibleTabs(f.businessType), [f.businessType]);
  const [active, setActive] = useState<TabKey>('identity');
  const activeTab = tabs.includes(active) ? active : 'identity';

  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // --- Live completeness (client-side; mirrors backend _profile_completeness) ---
  const completeness = useMemo(() => {
    const has = (...xs: (string | any[])[]) => xs.some((x) => (Array.isArray(x) ? x.length > 0 : !!x.trim()));
    const sections: Record<string, boolean> = {
      identity: has(f.displayName, f.roleTitle, f.industry, f.description),
      brand: has(brand.mission, brand.vision, brand.values, brand.usp, brand.voice, brand.styleGuidelines),
      offerings: offerings.some((x) => x.name.trim()),
      customers: has(customers.industriesServed, customers.locations, customers.painPoints, customers.goals) || personas.some((x) => x.name.trim()),
      operations: has(operations.workingHours, operations.tools, operations.workflows, operations.sops) || team.some((x) => x.name.trim()),
      marketing: has(marketing.competitors, marketing.channels, marketing.testimonials, marketing.caseStudies, marketing.salesScripts) || socials.some((x) => x.platform.trim()),
      legalFinancial: has(legal.registrationDetails, legal.taxInfo, legal.invoicingPreferences, legal.contractNotes, f.taxId, f.paymentMethods),
      goals: has(f.monthlyRevenueGoal, f.annualRevenueGoal, f.financialGoals, f.businessPriorities),
    };
    const filled = Object.values(sections).filter(Boolean).length;
    return { percent: Math.round((100 * filled) / Object.keys(sections).length), sections };
  }, [f, brand, offerings, customers, personas, operations, team, marketing, socials, legal]);

  async function save() {
    setBusy(true); setError(null); setSaved(false);
    try {
      const core = await authedFetch('/api/me', {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ fullName, businessName, country, currency }),
      });
      if (!core.ok) throw new Error('Could not save your account details.');

      const body = {
        // flat
        displayName: orNull(f.displayName), roleTitle: orNull(f.roleTitle), phone: orNull(f.phone),
        businessType: orNull(f.businessType), industry: orNull(f.industry), description: orNull(f.description),
        website: orNull(f.website), foundedYear: num(f.foundedYear), address: orNull(f.address),
        services: toList(f.services), targetClients: orNull(f.targetClients),
        defaultPaymentTermsDays: num(f.defaultPaymentTermsDays), defaultHourlyRate: num(f.defaultHourlyRate),
        typicalProjectValue: num(f.typicalProjectValue), invoicePrefix: orNull(f.invoicePrefix),
        taxId: orNull(f.taxId), defaultTaxRate: num(f.defaultTaxRate), paymentMethods: toList(f.paymentMethods),
        monthlyRevenueGoal: num(f.monthlyRevenueGoal), annualRevenueGoal: num(f.annualRevenueGoal),
        financialGoals: orNull(f.financialGoals), businessPriorities: toList(f.businessPriorities),
        brandTone: orNull(f.brandTone), businessAddress: orNull(f.businessAddress), invoiceFooter: orNull(f.invoiceFooter),
        notifyDailyDigest, notifyCriticalAlerts,
        // nested domains
        brand: {
          mission: orNull(brand.mission), vision: orNull(brand.vision), values: toList(brand.values),
          usp: orNull(brand.usp), voice: orNull(brand.voice), colors: toList(brand.colors),
          logoUrl: orNull(brand.logoUrl), styleGuidelines: orNull(brand.styleGuidelines),
        },
        offerings: offerings.filter((x) => x.name.trim() || x.description.trim()).map((x) => ({
          name: orNull(x.name), description: orNull(x.description), pricing: orNull(x.pricing),
          packages: toList(x.packages), deliveryProcess: orNull(x.deliveryProcess), guarantees: orNull(x.guarantees),
        })),
        customers: {
          buyerPersonas: personas.filter((x) => x.name.trim() || x.description.trim()).map((x) => ({
            name: orNull(x.name), description: orNull(x.description), painPoints: toList(x.painPoints), goals: toList(x.goals),
          })),
          industriesServed: toList(customers.industriesServed), locations: toList(customers.locations),
          painPoints: toList(customers.painPoints), goals: orNull(customers.goals),
        },
        operations: {
          teamMembers: team.filter((x) => x.name.trim() || x.role.trim()).map((x) => ({ name: orNull(x.name), role: orNull(x.role) })),
          workingHours: orNull(operations.workingHours), tools: toList(operations.tools),
          workflows: orNull(operations.workflows), sops: toLines(operations.sops),
        },
        marketing: {
          competitors: toList(marketing.competitors), channels: toList(marketing.channels),
          socialAccounts: socials.filter((x) => x.platform.trim() || x.handle.trim() || x.url.trim()).map((x) => ({
            platform: orNull(x.platform), handle: orNull(x.handle), url: orNull(x.url),
          })),
          testimonials: toLines(marketing.testimonials), caseStudies: toLines(marketing.caseStudies), salesScripts: toLines(marketing.salesScripts),
        },
        legalFinancial: {
          registrationDetails: orNull(legal.registrationDetails), taxInfo: orNull(legal.taxInfo),
          invoicingPreferences: orNull(legal.invoicingPreferences), paymentMethods: toList(f.paymentMethods),
          contractNotes: orNull(legal.contractNotes),
        },
      };

      const profile = await authedFetch('/api/profile', {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      });
      if (!profile.ok) {
        const j = await profile.json().catch(() => ({}));
        throw new Error(typeof j.detail === 'string' ? j.detail : 'Could not save business profile.');
      }
      setSaved(true);
      router.refresh();
      setTimeout(() => setSaved(false), 2500);
    } catch (e: any) {
      setError(e?.message ?? 'Save failed');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-5">
      {/* Completeness meter */}
      <div className="rounded-lg border border-gray-200 bg-white p-4">
        <div className="flex items-center justify-between text-sm">
          <span className="font-medium text-gray-700">Profile completeness</span>
          <span className="font-semibold text-kora-700">{completeness.percent}%</span>
        </div>
        <div className="mt-2 h-2 w-full overflow-hidden rounded-full bg-gray-100">
          <div className="h-full rounded-full bg-kora-500 transition-all" style={{ width: `${completeness.percent}%` }} />
        </div>
        <p className="mt-2 text-xs text-gray-400">
          The more you fill in, the sharper your AI agents' drafts, decisions, and briefings become.
        </p>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 overflow-x-auto border-b border-gray-200">
        {tabs.map((t) => (
          <button
            key={t}
            onClick={() => setActive(t)}
            className={`shrink-0 border-b-2 px-3 py-2 text-sm font-medium transition-colors ${
              activeTab === t ? 'border-kora-600 text-kora-700' : 'border-transparent text-gray-500 hover:text-gray-800'
            }`}
          >
            {TAB_LABELS[t]}
            {completeness.sections[t] && <span className="ml-1.5 inline-block h-1.5 w-1.5 rounded-full bg-emerald-400 align-middle" />}
          </button>
        ))}
      </div>

      {/* Panels */}
      {activeTab === 'identity' && (
        <div className="space-y-5">
          <Card>
            <CardHeader title="Owner" subtitle="Who's running the business" />
            <div className="grid gap-4 p-5 sm:grid-cols-2">
              <TextField label="Full name" value={fullName} onChange={setFullName} />
              <TextField label="Preferred name" value={f.displayName} onChange={setB2(setF, 'displayName')} placeholder="How clients address you" />
              <TextField label="Role / title" value={f.roleTitle} onChange={setB2(setF, 'roleTitle')} placeholder="Freelance Brand Designer" />
              <TextField label="Phone" value={f.phone} onChange={setB2(setF, 'phone')} />
              <Field label="Email"><input className={inputCls + ' bg-gray-50 text-gray-500'} value={me.email} disabled /></Field>
            </div>
          </Card>

          <Card>
            <CardHeader title="Business" subtitle="What you do and who you serve" />
            <div className="grid gap-4 p-5 sm:grid-cols-2">
              <TextField label="Business name" value={businessName} onChange={setBusinessName} />
              <Field label="Business type">
                <select className={inputCls} value={f.businessType} onChange={set('businessType')}>
                  <option value="">Select…</option>
                  {BUSINESS_TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                </select>
              </Field>
              <TextField label="Industry / niche" value={f.industry} onChange={setB2(setF, 'industry')} placeholder="Design, development, crafts…" />
              <TextField label="Website" value={f.website} onChange={setB2(setF, 'website')} placeholder="https://" />
              <TextField label="Founded year" value={f.foundedYear} onChange={setB2(setF, 'foundedYear')} inputMode="numeric" />
              <TextField label="Country" value={country} onChange={setCountry} />
              <div className="sm:col-span-2">
                <TextAreaField label="What your business does" value={f.description} onChange={setB2(setF, 'description')} placeholder="One or two sentences the AI can use as context." />
              </div>
              <TextField label="Services / products (comma-separated)" value={f.services} onChange={setB2(setF, 'services')} placeholder="Logo design, web design, motion" />
              <TextField label="Typical clients" value={f.targetClients} onChange={setB2(setF, 'targetClients')} placeholder="Early-stage startups, local shops" />
              <TextField label="Address" value={f.address} onChange={setB2(setF, 'address')} />
            </div>
          </Card>

          <Card>
            <CardHeader title="Goals & priorities" subtitle="What the Business Manager optimises for" />
            <div className="grid gap-4 p-5 sm:grid-cols-2">
              <TextField label="Monthly revenue goal" value={f.monthlyRevenueGoal} onChange={setB2(setF, 'monthlyRevenueGoal')} inputMode="decimal" />
              <TextField label="Annual revenue goal" value={f.annualRevenueGoal} onChange={setB2(setF, 'annualRevenueGoal')} inputMode="decimal" />
              <div className="sm:col-span-2">
                <TextAreaField label="Financial goals / priorities (free text)" value={f.financialGoals} onChange={setB2(setF, 'financialGoals')} placeholder="e.g. Reach $8k/mo recurring, cut overdue invoices, build a 3-month buffer." />
              </div>
              <div className="sm:col-span-2">
                <TextField label="Business priorities (comma-separated)" value={f.businessPriorities} onChange={setB2(setF, 'businessPriorities')} placeholder="Get paid faster, win retainer clients, reduce admin time" />
              </div>
            </div>
          </Card>

          <Card>
            <CardHeader title="Communication & notifications" subtitle="How Kora sounds and what it emails you" />
            <div className="grid gap-4 p-5 sm:grid-cols-2">
              <Field label="Default brand tone">
                <select className={inputCls} value={f.brandTone} onChange={set('brandTone')}>
                  <option value="">Select…</option>
                  {TONES.map((t) => <option key={t} value={t}>{t[0].toUpperCase() + t.slice(1)}</option>)}
                </select>
              </Field>
            </div>
            <div className="divide-y divide-gray-100 px-5 pb-2">
              <label className="flex cursor-pointer items-start justify-between gap-4 py-4">
                <span>
                  <span className="block text-sm font-medium text-gray-900">Daily digest</span>
                  <span className="block text-xs text-gray-500">Your Business Manager briefing each morning — priorities, what was handled, what needs approval.</span>
                </span>
                <input type="checkbox" className="mt-1 h-4 w-4 shrink-0 accent-kora-600" checked={notifyDailyDigest} onChange={(e) => setNotifyDailyDigest(e.target.checked)} />
              </label>
              <label className="flex cursor-pointer items-start justify-between gap-4 py-4">
                <span>
                  <span className="block text-sm font-medium text-gray-900">Critical alerts</span>
                  <span className="block text-xs text-gray-500">Time-sensitive warnings — cash-flow danger and failed subscription payments.</span>
                </span>
                <input type="checkbox" className="mt-1 h-4 w-4 shrink-0 accent-kora-600" checked={notifyCriticalAlerts} onChange={(e) => setNotifyCriticalAlerts(e.target.checked)} />
              </label>
            </div>
          </Card>
        </div>
      )}

      {activeTab === 'brand' && (
        <Card>
          <CardHeader title="Brand identity" subtitle="Mission, positioning and voice the agents write in" />
          <div className="grid gap-4 p-5 sm:grid-cols-2">
            <div className="sm:col-span-2"><TextAreaField label="Mission" value={brand.mission} onChange={setB('mission')} placeholder="Why the business exists." /></div>
            <div className="sm:col-span-2"><TextAreaField label="Vision" value={brand.vision} onChange={setB('vision')} placeholder="Where it's heading." /></div>
            <TextField label="Core values (comma-separated)" value={brand.values} onChange={setB('values')} placeholder="Craft, honesty, speed" />
            <TextField label="Unique selling proposition" value={brand.usp} onChange={setB('usp')} placeholder="What makes you different" />
            <div className="sm:col-span-2"><TextAreaField label="Brand voice" value={brand.voice} onChange={setB('voice')} placeholder="e.g. Warm, plain-spoken, lightly witty — never corporate." /></div>
            <TextField label="Brand colors (comma-separated)" value={brand.colors} onChange={setB('colors')} placeholder="#1F6FEB, charcoal, cream" />
            <TextField label="Logo URL" value={brand.logoUrl} onChange={setB('logoUrl')} placeholder="https://" />
            <div className="sm:col-span-2"><TextAreaField label="Style guidelines" value={brand.styleGuidelines} onChange={setB('styleGuidelines')} placeholder="Fonts, do's and don'ts, formatting notes." /></div>
          </div>
        </Card>
      )}

      {activeTab === 'offerings' && (
        <Card>
          <CardHeader title="Offerings" subtitle="Products & services — the AI quotes these in proposals and emails" />
          <div className="p-5">
            <RowsEditor<OfferingRow>
              rows={offerings}
              onChange={setOfferings}
              empty={() => ({ name: '', description: '', pricing: '', packages: '', deliveryProcess: '', guarantees: '' })}
              addLabel="Add offering"
              render={(row, update) => (
                <div className="grid gap-3 sm:grid-cols-2">
                  <TextField label="Name" value={row.name} onChange={(v) => update({ name: v })} placeholder="Brand identity package" />
                  <TextField label="Pricing" value={row.pricing} onChange={(v) => update({ pricing: v })} placeholder="from $2,500" />
                  <div className="sm:col-span-2"><TextAreaField label="Description" value={row.description} onChange={(v) => update({ description: v })} /></div>
                  <TextField label="Packages / tiers (comma-separated)" value={row.packages} onChange={(v) => update({ packages: v })} placeholder="Basic, Standard, Premium" />
                  <TextField label="Guarantees" value={row.guarantees} onChange={(v) => update({ guarantees: v })} placeholder="2 revisions, 30-day support" />
                  <div className="sm:col-span-2"><TextAreaField label="Delivery process" value={row.deliveryProcess} onChange={(v) => update({ deliveryProcess: v })} placeholder="Discovery → concepts → delivery." /></div>
                </div>
              )}
            />
          </div>
        </Card>
      )}

      {activeTab === 'customers' && (
        <div className="space-y-5">
          <Card>
            <CardHeader title="Buyer personas" subtitle="Who you sell to — shapes tone and targeting" />
            <div className="p-5">
              <RowsEditor<PersonaRow>
                rows={personas}
                onChange={setPersonas}
                empty={() => ({ name: '', description: '', painPoints: '', goals: '' })}
                addLabel="Add persona"
                render={(row, update) => (
                  <div className="grid gap-3 sm:grid-cols-2">
                    <TextField label="Name" value={row.name} onChange={(v) => update({ name: v })} placeholder="Early-stage founder" />
                    <TextField label="Short description" value={row.description} onChange={(v) => update({ description: v })} />
                    <TextField label="Pain points (comma-separated)" value={row.painPoints} onChange={(v) => update({ painPoints: v })} />
                    <TextField label="Goals (comma-separated)" value={row.goals} onChange={(v) => update({ goals: v })} />
                  </div>
                )}
              />
            </div>
          </Card>
          <Card>
            <CardHeader title="Market" subtitle="Where and to whom you sell" />
            <div className="grid gap-4 p-5 sm:grid-cols-2">
              <TextField label="Industries served (comma-separated)" value={customers.industriesServed} onChange={setC('industriesServed')} />
              <TextField label="Locations (comma-separated)" value={customers.locations} onChange={setC('locations')} />
              <TextField label="Customer pain points (comma-separated)" value={customers.painPoints} onChange={setC('painPoints')} />
              <div className="sm:col-span-2"><TextAreaField label="Customer goals" value={customers.goals} onChange={setC('goals')} /></div>
            </div>
          </Card>
        </div>
      )}

      {activeTab === 'operations' && (
        <div className="space-y-5">
          <Card>
            <CardHeader title="Team" subtitle="People and their roles" />
            <div className="p-5">
              <RowsEditor<TeamRow>
                rows={team}
                onChange={setTeam}
                empty={() => ({ name: '', role: '' })}
                addLabel="Add team member"
                render={(row, update) => (
                  <div className="grid gap-3 sm:grid-cols-2">
                    <TextField label="Name" value={row.name} onChange={(v) => update({ name: v })} />
                    <TextField label="Role" value={row.role} onChange={(v) => update({ role: v })} />
                  </div>
                )}
              />
            </div>
          </Card>
          <Card>
            <CardHeader title="How you work" subtitle="Hours, tools and standard procedures" />
            <div className="grid gap-4 p-5 sm:grid-cols-2">
              <TextField label="Working hours" value={operations.workingHours} onChange={setO('workingHours')} placeholder="Mon–Fri, 9–5 ET" />
              <TextField label="Tools (comma-separated)" value={operations.tools} onChange={setO('tools')} placeholder="Figma, Notion, Slack" />
              <div className="sm:col-span-2"><TextAreaField label="Workflows" value={operations.workflows} onChange={setO('workflows')} placeholder="How a typical project moves from kickoff to delivery." /></div>
              <div className="sm:col-span-2"><TextAreaField label="Standard operating procedures (one per line)" value={operations.sops} onChange={setO('sops')} rows={4} placeholder={"Onboard a client\nWeekly status update\nInvoice on milestone"} /></div>
            </div>
          </Card>
        </div>
      )}

      {activeTab === 'marketing' && (
        <div className="space-y-5">
          <Card>
            <CardHeader title="Marketing & sales" subtitle="Positioning against competitors and how you reach customers" />
            <div className="grid gap-4 p-5 sm:grid-cols-2">
              <TextField label="Competitors (comma-separated)" value={marketing.competitors} onChange={setM('competitors')} />
              <TextField label="Marketing channels (comma-separated)" value={marketing.channels} onChange={setM('channels')} placeholder="Instagram, referrals, SEO" />
              <div className="sm:col-span-2"><TextAreaField label="Testimonials (one per line)" value={marketing.testimonials} onChange={setM('testimonials')} rows={3} /></div>
              <div className="sm:col-span-2"><TextAreaField label="Case studies (one per line)" value={marketing.caseStudies} onChange={setM('caseStudies')} rows={3} /></div>
              <div className="sm:col-span-2"><TextAreaField label="Sales scripts / talking points (one per line)" value={marketing.salesScripts} onChange={setM('salesScripts')} rows={3} /></div>
            </div>
          </Card>
          <Card>
            <CardHeader title="Social accounts" subtitle="Where the business shows up online" />
            <div className="p-5">
              <RowsEditor<SocialRow>
                rows={socials}
                onChange={setSocials}
                empty={() => ({ platform: '', handle: '', url: '' })}
                addLabel="Add account"
                render={(row, update) => (
                  <div className="grid gap-3 sm:grid-cols-3">
                    <TextField label="Platform" value={row.platform} onChange={(v) => update({ platform: v })} placeholder="Instagram" />
                    <TextField label="Handle" value={row.handle} onChange={(v) => update({ handle: v })} placeholder="@studio" />
                    <TextField label="URL" value={row.url} onChange={(v) => update({ url: v })} placeholder="https://" />
                  </div>
                )}
              />
            </div>
          </Card>
        </div>
      )}

      {activeTab === 'legalFinancial' && (
        <div className="space-y-5">
          <Card>
            <CardHeader title="Financial preferences" subtitle="Defaults the invoice, contract & finance agents use" />
            <div className="grid gap-4 p-5 sm:grid-cols-2">
              <Field label="Default currency">
                <select className={inputCls} value={currency} onChange={(e) => setCurrency(e.target.value)}>
                  {CURRENCIES.map((cur) => <option key={cur} value={cur}>{cur}</option>)}
                </select>
              </Field>
              <TextField label="Default payment terms (Net days)" value={f.defaultPaymentTermsDays} onChange={setB2(setF, 'defaultPaymentTermsDays')} inputMode="numeric" placeholder="14" />
              <TextField label="Hourly rate" value={f.defaultHourlyRate} onChange={setB2(setF, 'defaultHourlyRate')} inputMode="decimal" />
              <TextField label="Typical project value" value={f.typicalProjectValue} onChange={setB2(setF, 'typicalProjectValue')} inputMode="decimal" />
              <TextField label="Invoice prefix" value={f.invoicePrefix} onChange={setB2(setF, 'invoicePrefix')} placeholder="INV" />
              <TextField label="Default tax rate (%)" value={f.defaultTaxRate} onChange={setB2(setF, 'defaultTaxRate')} inputMode="decimal" />
              <TextField label="Tax / business ID" value={f.taxId} onChange={setB2(setF, 'taxId')} />
              <TextField label="Payment methods (comma-separated)" value={f.paymentMethods} onChange={setB2(setF, 'paymentMethods')} placeholder="Bank transfer, Stripe, PayPal" />
            </div>
          </Card>
          <Card>
            <CardHeader title="Invoice sender" subtitle="Printed on every PDF invoice you generate" />
            <div className="grid gap-4 p-5">
              <TextAreaField label="Business address (printed on invoice)" value={f.businessAddress} onChange={setB2(setF, 'businessAddress')} rows={3} placeholder={"123 Main Street\nCity, State 10001\nUnited States"} />
              <TextAreaField label="Invoice footer text (optional)" value={f.invoiceFooter} onChange={setB2(setF, 'invoiceFooter')} placeholder="Thank you for your business. Payment due by the date above." />
            </div>
          </Card>
          <Card>
            <CardHeader title="Legal & registration" subtitle="Entity, tax and contract notes for the agents" />
            <div className="grid gap-4 p-5 sm:grid-cols-2">
              <div className="sm:col-span-2"><TextAreaField label="Business registration details" value={legal.registrationDetails} onChange={setL('registrationDetails')} placeholder="Entity type, registration number, jurisdiction." /></div>
              <div className="sm:col-span-2"><TextAreaField label="Tax information" value={legal.taxInfo} onChange={setL('taxInfo')} placeholder="Tax jurisdiction, VAT/GST notes." /></div>
              <div className="sm:col-span-2"><TextAreaField label="Invoicing preferences" value={legal.invoicingPreferences} onChange={setL('invoicingPreferences')} placeholder="Deposit up front, milestone billing, etc." /></div>
              <div className="sm:col-span-2"><TextAreaField label="Contract notes" value={legal.contractNotes} onChange={setL('contractNotes')} placeholder="Standard clauses you always include or avoid." /></div>
            </div>
          </Card>
        </div>
      )}

      {/* Save (always visible) */}
      <div className="flex items-center gap-3 pt-1">
        <button
          onClick={save}
          disabled={busy}
          className="inline-flex items-center gap-2 rounded-lg bg-kora-600 px-5 py-2.5 text-sm font-semibold text-white hover:bg-kora-700 disabled:opacity-60"
        >
          {busy ? <Loader2 size={15} className="animate-spin" /> : saved ? <Check size={15} /> : null}
          {saved ? 'Saved' : 'Save profile'}
        </button>
        {error && <span className="text-sm text-red-600">{error}</span>}
      </div>
    </div>
  );
}

// Adapter: bridge the flat `f` object's event-based setter to the value-based
// onChange the TextField/TextAreaField primitives expect. Defined at module
// scope so component identities stay stable across renders.
function setB2(
  setter: React.Dispatch<React.SetStateAction<any>>,
  key: string,
): (v: string) => void {
  return (v: string) => setter((s: any) => ({ ...s, [key]: v }));
}
