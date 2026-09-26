/**
 * JSON-LD'yi script etiketine gömer.
 *
 * `<` karakteri kaçırılıyor: veri içinde `</script>` geçen bir metin sayfayı
 * kırar ve bu bir enjeksiyon yoludur. Kurum adı gibi alanlar ileride dışarıdan
 * gelecek, o yüzden kaçırma baştan yerinde.
 */
export function JsonLd({ data }: { data: Record<string, unknown> }) {
  const govde = JSON.stringify(data).replace(/</g, "\\u003c");
  return <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: govde }} />;
}
