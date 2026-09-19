/**
 * Everything that makes this receptionist belong to one specific agency.
 *
 * To re-brand the demo for a new client, you do NOT touch any other file:
 * set the environment variables below (locally in .env.local, on Vercel in
 * Project Settings -> Environment Variables) and redeploy.
 */

export const agency = {
  name: process.env.NEXT_PUBLIC_AGENCY_NAME || "Harborview Realty",
  assistantName: process.env.NEXT_PUBLIC_ASSISTANT_NAME || "Ava",
  city: process.env.NEXT_PUBLIC_AGENCY_CITY || "New York",
  state: process.env.NEXT_PUBLIC_AGENCY_STATE || "NY",
  phone: process.env.NEXT_PUBLIC_AGENCY_PHONE || "(212) 555-0142",
  email: process.env.NEXT_PUBLIC_AGENCY_EMAIL || "hello@harborviewrealty.com",

  /** IANA timezone — drives every appointment slot the assistant offers. */
  timezone: process.env.AGENCY_TIMEZONE || "America/New_York",
  /** Local business hours, 24h clock. Slots are only offered inside this window. */
  openHour: Number(process.env.AGENCY_OPEN_HOUR || 9),
  closeHour: Number(process.env.AGENCY_CLOSE_HOUR || 18),
  /** 0 = Sunday … 6 = Saturday */
  workingDays: (process.env.AGENCY_WORKING_DAYS || "1,2,3,4,5,6")
    .split(",")
    .map((d) => Number(d.trim())),
  appointmentMinutes: Number(process.env.AGENCY_APPOINTMENT_MINUTES || 30),

  specialty:
    process.env.NEXT_PUBLIC_AGENCY_SPECIALTY ||
    "condos, co-ops and townhouses across the five boroughs",
  brandColor: process.env.NEXT_PUBLIC_BRAND_COLOR || "#047857",

  welcomeMessage:
    process.env.NEXT_PUBLIC_WELCOME_MESSAGE ||
    "Hi! I'm Ava, the virtual receptionist at Harborview Realty. Are you looking to buy, sell, or rent?",
} as const;

export type Agency = typeof agency;
