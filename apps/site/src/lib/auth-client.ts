"use client";

import { createAuthClient } from "better-auth/react";

/** Tarayıcı tarafı kimlik istemcisi. */
export const authClient = createAuthClient();

export const { signIn, signUp, signOut, useSession } = authClient;
