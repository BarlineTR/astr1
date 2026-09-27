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
     * Doğrulama zorunlu: hesap açıldığında kullanıcı e-posta doğrulaması
     * yapmadan panele ve robot yönetim sistemine erişemez.
     */
    requireEmailVerification: true,
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

  trustedOrigins: [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://192.168.1.111:3000",
    "http://100.95.192.117:3000",
  ],

  advanced: {
    /*
     * Çerez güvenliği:
     * Yerel ağ (192.168.x.x / localhost) HTTP üzerinden çalıştığından
     * Secure çerez zorunluluğu yalnızca USE_SECURE_COOKIES=true (HTTPS) iken açılır.
     */
    useSecureCookies: process.env.USE_SECURE_COOKIES === "true",
  },

  /*
   * Sunucu eylemlerinin ve route handler'ların çerez yazabilmesi için gerekli;
   * olmadan giriş başarılı görünüp oturum kurulmuyor.
   */
  plugins: [nextCookies()],
});
