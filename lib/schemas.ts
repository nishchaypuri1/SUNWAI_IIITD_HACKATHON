import { z } from "zod";

export const caseResponseSchema = z.object({
  id: z.string().min(1),
  state: z.string(),
  language: z.enum(["en", "hi", "hinglish"]),
  case_json: z.object({ summary: z.string(), counterparty: z.object({ name: z.string().nullable() }).passthrough() }).passthrough(),
  steps: z.array(z.object({ ordinal: z.number(), status: z.string() }).passthrough()),
}).passthrough();

export const demoClockSchema = z.object({ now: z.string(), today: z.string(), offset_days: z.number(), simulated: z.boolean() });
export const caseSummarySchema = z.object({ id: z.string(), created_at: z.string(), state: z.string(), summary: z.string(), counterparty_name: z.string().nullable(), amount_inr: z.number().nullable(), next_deadline: z.string().nullable(), current_step: z.number().nullable() });

export function parseCaseResponse(value: unknown) {
  const result = caseResponseSchema.safeParse(value);
  if (!result.success) throw new Error("The case data from the API doesn’t match the Sunwai contract.");
  return value;
}

export function parseDemoClock(value: unknown) {
  const result = demoClockSchema.safeParse(value);
  if (!result.success) throw new Error("The demo clock data from the API is incomplete.");
  return result.data;
}

export function parseCaseSummaries(value: unknown) {
  const result = z.array(caseSummarySchema).safeParse(value);
  if (!result.success) throw new Error("The case list from the API doesn’t match the Sunwai contract.");
  return result.data;
}
