/**
 * Sözleşmenin ana sürümü.
 *
 * Ajan ile ağ geçidi farklı ana sürümdeyse bağlantı reddedilir. Sessizce yanlış
 * alan okumak, anlaşılır bir hatadan çok daha pahalıdır.
 *
 * Kendi dosyasında duruyor çünkü hem şemasız girişin (tarayıcı) hem şemalı
 * girişin (ağ geçidi) buna ihtiyacı var; şema modülünde olsaydı sürümü okumak
 * zod'u da beraberinde getirirdi.
 */
export const PROTOCOL_VERSION = "1";
