// Deterministic browser-side synthesizer mirroring examples/demo/make_demo.py.
// Generates customers_us.csv (dollars), customers_eu.csv (cents x100 mismatch + label drift),
// and orders.csv (foreign-key join, duplicate rows, July +18% jump, and regional Simpson's paradox).

import { api, uploadFile } from "./api";

function mulberry32(seed: number): () => number {
  let t = seed >>> 0;
  return () => {
    t += 0x6d2b79f5;
    let r = Math.imul(t ^ (t >>> 15), 1 | t);
    r ^= r + Math.imul(r ^ (r >>> 7), 61 | r);
    return ((r ^ (r >>> 14)) >>> 0) / 4294967296;
  };
}

function normal(rng: () => number, mean = 0, sd = 1): number {
  const u1 = Math.max(1e-9, rng());
  const u2 = rng();
  const z = Math.sqrt(-2.0 * Math.log(u1)) * Math.cos(2.0 * Math.PI * u2);
  return mean + z * sd;
}

function pickWeighted<T>(rng: () => number, items: T[], weights: number[]): T {
  const r = rng();
  let acc = 0;
  for (let i = 0; i < items.length; i++) {
    acc += weights[i];
    if (r <= acc) return items[i];
  }
  return items[items.length - 1];
}

function fmtIsoDate(baseYear: number, offsetDays: number): string {
  const dt = new Date(Date.UTC(baseYear, 0, 1));
  dt.setUTCDate(dt.getUTCDate() + offsetDays);
  return dt.toISOString().slice(0, 10);
}

export function buildDemoFiles(seed = 20261123): File[] {
  const rng = mulberry32(seed);
  const nCustomers = 950;
  const nOrders = 3400;

  const regions = ["North", "South", "East", "West"] as const;
  const regionWeights = [0.3, 0.25, 0.25, 0.2];
  const plans = ["basic", "plus", "pro"] as const;
  const planWeights = [0.5, 0.3, 0.2];
  const regionMean: Record<string, number> = { North: 4.0, South: 8.0, East: 12.0, West: 16.0 };

  const usLines = [
    "customer_id,signup_date,region,plan,age,loyalty_years,sessions_per_month,satisfaction,lifetime_value,newsletter,email",
  ];
  const euLines = [
    "customer_id,signup_date,region,plan,age,loyalty_years,sessions_per_month,satisfaction,lifetime_value,newsletter,email",
  ];

  const custIds: string[] = [];
  const custLoyalty: number[] = [];
  const custPlan: string[] = [];

  for (let i = 1; i <= nCustomers; i++) {
    const id = `C${String(i).padStart(5, "0")}`;
    const reg = pickWeighted(rng, [...regions], regionWeights);
    const plan = pickWeighted(rng, [...plans], planWeights);
    const rawAge = Math.min(84, Math.max(18, Math.round(normal(rng, 42, 13))));
    const loyalty = Math.min(14.5, Math.max(0.1, Number((Math.abs(normal(rng, 3.2, 2.3)) + 0.2).toFixed(1))));
    const signupOffset = 365 - Math.round(loyalty * 365.25);
    const signup = fmtIsoDate(2024, signupOffset);
    const mu = regionMean[reg];
    const sessions = Math.max(0.2, Number((mu + normal(rng, 0, 2.4)).toFixed(1)));
    // Simpson's paradox: higher regional baseline increases both, but within every region higher sessions lower satisfaction
    const satisfaction = Math.min(
      10,
      Math.max(0.2, Number((3.1 + 0.36 * mu - 0.32 * (sessions - mu) + normal(rng, 0, 0.85)).toFixed(1))),
    );
    const planBonus = plan === "pro" ? 400 : plan === "plus" ? 150 : 0;
    const ltvDollars = Math.max(45, Number((200 + 150 * loyalty + planBonus + normal(rng, 0, 55)).toFixed(2)));
    const newsletter = rng() < 0.42 ? "yes" : "no";
    const email = `member${i}@example.org`;
    const isUS = rng() < 0.6;

    custIds.push(id);
    custLoyalty.push(loyalty);
    custPlan.push(plan);

    if (isUS) {
      const ageCell = rng() < 0.03 ? "" : String(rawAge);
      usLines.push(
        `${id},${signup},${reg},${plan},${ageCell},${loyalty},${sessions},${satisfaction},${ltvDollars},${newsletter},${email}`,
      );
    } else {
      // Planted EU issues: cents instead of dollars (x100), occasional lowercase region labels, higher missingness on age
      const ltvCents = Math.round(ltvDollars * 100);
      const messyReg = rng() < 0.05 ? reg.toLowerCase() : reg;
      const ageCell = rng() < 0.09 ? "" : String(rawAge);
      euLines.push(
        `${id},${signup},${messyReg},${plan},${ageCell},${loyalty},${sessions},${satisfaction},${ltvCents},${newsletter},${email}`,
      );
    }
  }

  const orderLines = [
    "order_id,customer_id,order_date,amount,discount_pct,delivery_days,promo,returned,channel",
  ];
  const channels = ["web", "app", "store"];
  const channelWeights = [0.5, 0.3, 0.2];
  const generatedRows: string[] = [];

  for (let j = 1; j <= nOrders; j++) {
    const idx = Math.floor(rng() * nCustomers);
    const cid = rng() < 0.005 ? `C9${String(j % 9999).padStart(4, "0")}` : custIds[idx];
    const loyalty = custLoyalty[idx];
    const plan = custPlan[idx];
    const dayOfYear = Math.floor(rng() * 365);
    const orderDate = fmtIsoDate(2024, dayOfYear);
    const discount = Math.floor(rng() * 9) * 5;
    const promoProb = 1 / (1 + Math.exp(-(-1.5 + 0.44 * loyalty)));
    const promo = rng() < promoProb ? "true" : "false";
    const planBoost = plan === "pro" ? 25 : plan === "plus" ? 10 : 0;
    let amount =
      40 +
      9 * loyalty +
      planBoost +
      55 * (1 - Math.exp(-discount / 9.0)) +
      normal(rng, 0, 11.5);
    if (orderDate >= "2024-07-01") amount *= 1.18; // Planted regime step-up
    if (j <= 5) amount *= 18; // Extreme outliers
    else if (j === 6 || j === 7) amount *= -1; // Negative refunds
    const cleanAmount = Number(amount.toFixed(2));
    const deliveryDays = 1 + Math.floor(rng() * 14);
    const isNew = loyalty < 1.0;
    const retProb = 1 / (1 + Math.exp(-(-2.75 + (isNew ? 0.31 : 0.02) * deliveryDays)));
    const returned = rng() < retProb ? 1 : 0;
    const channel = pickWeighted(rng, channels, channelWeights);
    const oid = `O${String(j).padStart(6, "0")}`;
    const line = `${oid},${cid},${orderDate},${cleanAmount},${discount},${deliveryDays},${promo},${returned},${channel}`;
    generatedRows.push(line);
    orderLines.push(line);
  }

  // Plant 6 exact duplicate rows for cleaning recipe verification
  for (let d = 0; d < 6; d++) {
    orderLines.push(generatedRows[d * 17]);
  }

  return [
    new File([usLines.join("\n")], "customers_us.csv", { type: "text/csv" }),
    new File([euLines.join("\n")], "customers_eu.csv", { type: "text/csv" }),
    new File([orderLines.join("\n")], "orders.csv", { type: "text/csv" }),
  ];
}

export async function createDemoWorkspace(
  onStep?: (label: string) => void,
): Promise<string> {
  onStep?.("Creating demo workspace…");
  const project = await api.createProject("Commerce US + EU Audit (Demo)");
  const files = buildDemoFiles();
  for (let i = 0; i < files.length; i++) {
    onStep?.(`Loading ${files[i].name} (${i + 1}/3)…`);
    await uploadFile(project.id, files[i], () => {});
  }
  return project.id;
}
