import createClient from "openapi-fetch";

import type { paths } from "../generated/api";

const configuredBase = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "");
export const API_BASE = configuredBase || "";

export const client = createClient<paths>({
  baseUrl: API_BASE,
});
