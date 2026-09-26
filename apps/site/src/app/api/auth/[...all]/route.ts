import { toNextJsHandler } from "better-auth/next-js";

import { auth } from "@/lib/auth";

/** better-auth'un bütün uçları bu tek route handler'dan geçer. */
export const { GET, POST } = toNextJsHandler(auth.handler);
