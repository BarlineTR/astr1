import { HukukiSayfa, hukukiMetadata } from "@/components/HukukiSayfa";

export const metadata = hukukiMetadata("gizlilik");

export default function Sayfa() {
  return <HukukiSayfa slug="gizlilik" />;
}
