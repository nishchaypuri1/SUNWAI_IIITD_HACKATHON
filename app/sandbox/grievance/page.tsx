import { SandboxGrievancePage } from "@/components/sandbox-page";

export default async function Page({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const query = await searchParams;
  return <SandboxGrievancePage session={typeof query.session === "string" ? query.session : "visitor"} review={query.review === "1"}/>;
}
