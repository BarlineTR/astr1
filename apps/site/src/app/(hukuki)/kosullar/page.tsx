import { HukukiSayfa, hukukiMetadata } from "@/components/HukukiSayfa";

export const metadata = hukukiMetadata("kosullar");

export default function Sayfa() {
  return <HukukiSayfa slug="kosullar" />;
}
