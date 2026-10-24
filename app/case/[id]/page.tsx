import { CasePage } from "@/components/case-page";

export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <CasePage id={id}/>;
}
