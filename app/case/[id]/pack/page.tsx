import { EvidencePackPage } from "@/components/evidence-pack-page";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <EvidencePackPage id={id}/>;
}
