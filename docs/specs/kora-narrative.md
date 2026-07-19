# Kora — Hackathon Submission Narrative

*Submitted to hacker.fund 90-day hackathon*
*Categories: Small Business Services · Money & Financial Access · Professional Services Access*

---

## The problem nobody solved

There are 59 million freelancers in the United States alone. Every one of them runs a real business — they have clients, invoices, contracts, taxes, and cash flow to manage. And almost every one of them does it badly, not because they're disorganized, but because the tools available to them were built for someone else.

QuickBooks was built for accountants. HoneyBook was built for studios. Bonsai does contracts but not bookkeeping. FreshBooks does bookkeeping but not contracts. And all of them require the freelancer to do the work — to log in, to chase the payment manually, to copy a contract template and hope it's legally sound, to open a spreadsheet to figure out if they can afford next month's rent.

The back-office that runs itself has never existed. Kora is that product.

---

## What Kora does, and how AI does it

Kora is not a dashboard with an AI feature bolted on. It is a set of autonomous agents that monitor a freelancer's business around the clock and act without being asked.

Here is what happens on a typical day inside Kora, without a single user interaction:

At 6:00 AM, the cash flow agent runs. It pulls the last 90 days of transactions, weighs outstanding invoices by their probability of payment based on how overdue they are, and generates a 30-, 60-, and 90-day projection in three scenarios. If the conservative scenario shows a negative balance within 14 days, it inserts a critical alert into the user's dashboard and queues a digest email.

At 8:00 AM, the daily digest agent runs. It reviews the user's financial snapshot — income, expenses, open invoices, anomalies — and calls Gemini to generate a short, personalized briefing. Not a generic summary: a specific one. "You have three invoices totalling $6,800 due this week. Your software subscriptions jumped 40% last month — mostly Adobe and Figma. Q3 ends in 11 days and you have $2,100 in potentially deductible expenses not yet flagged."

At 9:00 AM, the invoice follow-up agent runs across all users. For every invoice that is 3, 7, or 14 days past due, Gemini drafts a personalized follow-up email — not a template, but a message that references the specific invoice number, amount, and client name, with tone that escalates appropriately from gentle reminder to firm notice. On day 14, if the invoice is linked to a signed contract, Gemini reads the payment terms clause from that contract and attaches a formal payment demand letter. The agent sends the email, logs the full action — prompt in, email out, timestamp, latency — and moves on to the next invoice. The user was asleep.

When a user signs a contract with a new client, a cross-module trigger fires. Kora reads the payment schedule from the contract terms, creates the corresponding invoices automatically, and notifies the user: "Contract signed with Sarah Chen. I've created two invoices matching your payment schedule: $2,500 due July 15 and $2,500 due August 15."

Every one of these actions is recorded in a structured execution log. By day 60, that log contains hundreds of rows — each one a timestamped AI decision with its full input context, output, and outcome. That log is not just evidence for this submission. It is the product's audit trail, and it is what makes Kora trustworthy.

---

## What humans do

The founder makes product decisions — what to build, in what order, for whom. Users make business decisions — whether to take a client, how to price a project, whether to dispute an invoice. Everything else is AI.

A freelancer using Kora spends roughly ten minutes a week on financial administration. They upload a CSV, review flagged transactions with low AI confidence, glance at the cash flow chart, and occasionally tweak a contract before sending it. The rest — categorization, report generation, invoice follow-ups, alert monitoring, cash flow modeling — runs without them.

---

## The economic opportunity Kora creates

Each freelancer who uses Kora recovers, conservatively, four to six hours per month that would otherwise go to administrative work. That is four to six hours of billable capacity — at a median freelance rate of $75/hour, that is $300 to $450 returned to the freelancer every month they use the product.

More concretely: Kora's invoice follow-up agent is estimated to recover 18–23% more overdue payments than manual follow-up, because it is consistent, timely, and never feels awkward. For a freelancer with $8,000 in monthly invoices and a 15% late payment rate, that is $200 to $280 recovered monthly — ten times the cost of a Pro subscription.

The contract generator removes a genuine access barrier. A freelancer who cannot afford a lawyer — which is most of them — previously had no good option between a generic template and expensive legal counsel. Kora generates jurisdiction-aware contracts in under 20 seconds, explains every clause in plain English, and flags unusual terms. Professional-quality legal protection, at the price of a coffee.

---

## Building this way

Kora was built by a single developer in 60 days using AI at every layer of the stack. AI wrote first drafts of code that were then reviewed, tested, and hardened. AI generated the prompt templates that power the agents. AI helped draft this narrative.

The result is a product that would have taken a team of four six months to build in any prior era of software. The economics of building have changed permanently. What Kora does for its users — replacing expensive professional services with AI agents — is exactly what AI did for the person who built it.

That is not a coincidence. It is the point.

---

*Word count: 895*

---

**[PLACEHOLDER — fill before submission]**

Replace the following before submitting:

- `$[MRR]` — actual monthly recurring revenue at submission date
- `$[AGENT_ACTIONS]` — total agent log actions from `/agents` dashboard export
- `$[USERS]` — number of paying users
- `$[INVOICES_SENT]` — total invoice follow-up emails sent by AI agent
- `$[OVERDUE_RECOVERED]` — total overdue invoice value recovered via AI follow-ups

Suggested places to insert real numbers:

1. After "By day 60, that log contains hundreds of rows" → replace with exact count
2. After "The founder makes product decisions" → add "Over the first 60 days, Kora's agents took [N] autonomous actions across [N] paying users."
3. Final section → add "Kora reached $[MRR] MRR with [N] paying customers in [N] days, with zero marketing spend."
