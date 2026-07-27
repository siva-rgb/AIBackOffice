import { formatMoney, humanize, daysBetween } from "../lib/utils";

describe("formatMoney", () => {
  it("formats USD amounts", () => {
    expect(formatMoney(1000, "USD")).toMatch(/1,000/);
  });

  it("handles zero", () => {
    expect(formatMoney(0, "USD")).toMatch(/0/);
  });
});

describe("humanize", () => {
  it("converts slug to title case", () => {
    expect(humanize("software_subscriptions")).toBe("Software Subscriptions");
  });

  it("returns Uncategorized for null", () => {
    expect(humanize(null)).toBe("Uncategorized");
  });
});

describe("daysBetween", () => {
  it("returns 0 for today", () => {
    const today = new Date().toISOString().slice(0, 10);
    expect(daysBetween(today)).toBe(0);
  });
});
