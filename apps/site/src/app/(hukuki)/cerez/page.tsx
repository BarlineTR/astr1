import { HukukiSayfa, hukukiMetadata } from "@/components/HukukiSayfa";

export const metadata = hukukiMetadata("cerez");

export default function Sayfa() {
  return <HukukiSayfa slug="cerez" />;
}
