import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { ToolFlow } from "@/components/flow/tool-flow";
import { isToolSlug, TOOLS } from "@/lib/tools";

export async function generateMetadata(props: PageProps<"/tools/[tool]">): Promise<Metadata> {
  const { tool } = await props.params;
  if (!isToolSlug(tool)) return {};
  return { title: TOOLS[tool].name, description: TOOLS[tool].summary };
}

export default async function ToolPage(props: PageProps<"/tools/[tool]">) {
  const { tool } = await props.params;
  if (!isToolSlug(tool)) notFound();
  return <ToolFlow slug={tool} />;
}
