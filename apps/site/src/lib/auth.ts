import { betterAuth } from "better-auth";
import { drizzleAdapter } from "better-auth/adapters/drizzle";
import { nextCookies } from "better-auth/next-js";

import { db, schema } from "@/db";
import { epostaGonder } from "./eposta";

/**
 * Kimlik.
 *
 * Oturum kendi Postgres'imizde duruyor, sağlayıcıda değil: bir oturumu yönetici
 * olarak iptal edebilmek ve kullanıcı verisini taşıyabilmek için.
 */
export const auth = betterAuth({
  database: drizzleAdapter(db, {
    provider: "pg",
    schema: {
      user: schema.users,
      session: schema.sessions,
      account: schema.accounts,
      verification: schema.verifications,
    },
  }),

  emailAndPassword: {
    enabled: true,
    /*
     * Doğrulama zorunlu değil: hesap açıldığı anda panele girebilmeli, yoksa
     * ilk deneyim e-posta beklemekle geçiyor. Doğrulama e-postası yine gidiyor
     * ve doğrulanmamış hesap ileride cihaz bağlayamayacak.
     */
    requireEmailVerification: false,
    minPasswordLength: 10,
    sendResetPassword: async ({ user, url }) => {
      await epostaGonder({
        kime: user.email,
        konu: "ASTRO — parola sıfırlama",
        govde:
          `Merhaba,\n\nParolanızı sıfırlamak için bağlantı:\n${url}\n\n` +
          "Bu isteği siz yapmadıysanız bu e-postayı yok sayabilirsiniz.",
      });
    },
  },

  emailVerification: {
    sendOnSignUp: true,
    sendVerificationEmail: async ({ user, url }) => {
      await epostaGonder({
        kime: user.email,
        konu: "ASTRO — e-posta adresinizi doğrulayın",
        govde: `Merhaba,\n\nE-posta adresinizi doğrulamak için:\n${url}`,
      });
    },
  },

  user: {
    additionalFields: {
      /*
       * Rol istemciden gelemez: `input: false` olmadan kayıt gövdesine
       * role:"admin" koyan biri kendini yönetici yapardı.
       */
      role: { type: "string", required: false, defaultValue: "customer", input: false },
      company: { type: "string", required: false, input: true },
      phone: { type: "string", required: false, input: true },
    },
  },

  session: {
    expiresIn: 60 * 60 * 24 * 30,
    updateAge: 60 * 60 * 24,
  },

  advanced: {
    /* Çerez üretimde yalnızca HTTPS üzerinden gider. */
    useSecureCookies: process.env.NODE_ENV === "production",
  },

  /*
   * Sunucu eylemlerinin ve route handler'ların çerez yazabilmesi için gerekli;
   * olmadan giriş başarılı görünüp oturum kurulmuyor.
   */
  plugins: [nextCookies()],
});
