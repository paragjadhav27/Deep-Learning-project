import { ArrowRight, Clock, EyeOff, ShieldCheck, Sparkles, SlidersHorizontal, Trash2 } from "lucide-react";
import Link from "next/link";

import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { TOOLS, TOOL_ORDER, type ToolSlug } from "@/lib/tools";

const TOOL_ICONS: Record<ToolSlug, typeof Clock> = {
  age: Clock,
  presentation: SlidersHorizontal,
  aging: Sparkles,
};

export default function HomePage() {
  return (
    <div className="mx-auto max-w-6xl px-4 sm:px-6">
      <section aria-labelledby="hero-title" className="py-14 sm:py-20">
        <p className="mb-3 text-sm font-medium text-primary">Opt-in · private by default · illustrative</p>
        <h1 id="hero-title" className="max-w-3xl font-heading text-4xl leading-tight font-semibold sm:text-5xl">
          Curious what a model sees in a photo? Explore it, with the uncertainty left in.
        </h1>
        <p className="mt-5 max-w-2xl text-lg text-muted-foreground">
          FaceLens offers three small tools that work on a single photo. Each result is an uncertain
          estimate or a synthetic illustration. None of them is a fact about the person, and none
          should inform a decision about anyone.
        </p>
      </section>

      <section id="tools" aria-labelledby="tools-title" className="scroll-mt-6">
        <h2 id="tools-title" className="mb-6 font-heading text-2xl font-semibold">
          Choose a tool
        </h2>
        <ul className="grid gap-5 md:grid-cols-3">
          {TOOL_ORDER.map((slug) => {
            const tool = TOOLS[slug];
            const Icon = TOOL_ICONS[slug];
            return (
              <li key={slug} className="flex">
                <Card className="flex w-full flex-col">
                  <CardHeader>
                    <Icon className="mb-2 size-6 text-primary" aria-hidden="true" />
                    <CardTitle className="font-heading text-xl">{tool.name}</CardTitle>
                    <CardDescription className="text-base">{tool.summary}</CardDescription>
                  </CardHeader>
                  <CardContent className="flex-1 space-y-3 text-sm">
                    <p>{tool.whatItReturns}</p>
                    <p className="text-muted-foreground">
                      <span className="font-medium text-foreground">Main limitation: </span>
                      {tool.limitations[0]}
                    </p>
                  </CardContent>
                  <CardFooter>
                    <Link
                      href={`/tools/${slug}`}
                      className="inline-flex min-h-11 w-full items-center justify-center gap-2 rounded-lg bg-primary px-4 font-medium text-primary-foreground hover:bg-primary/90"
                    >
                      {tool.action}
                      <ArrowRight className="size-4" aria-hidden="true" />
                    </Link>
                  </CardFooter>
                </Card>
              </li>
            );
          })}
        </ul>
      </section>

      <section aria-labelledby="how-title" className="mt-16">
        <h2 id="how-title" className="mb-6 font-heading text-2xl font-semibold">
          How it works
        </h2>
        <ol className="grid gap-5 md:grid-cols-3">
          <Step n={1} title="Pick a tool">
            Use a photo of an adult that you have permission to use. Results are illustrative,
            not facts about anyone.
          </Step>
          <Step n={2} title="One photo, one face">
            Metadata such as location is removed on your device before upload. Photos with no face
            or with several faces are declined.
          </Step>
          <Step n={3} title="Delete any time">
            Photos and results are deleted automatically within an hour. Or delete them yourself
            straight away with one button.
          </Step>
        </ol>
      </section>

      <section aria-labelledby="not-title" className="mt-16 grid gap-8 rounded-2xl bg-secondary p-6 sm:p-10 md:grid-cols-2">
        <div>
          <h2 id="not-title" className="font-heading text-2xl font-semibold text-secondary-foreground">
            What FaceLens is not
          </h2>
          <p className="mt-3 text-secondary-foreground/90">
            Face-attribute models make mistakes, and their errors aren&apos;t spread evenly across
            people. We tell you what the models can&apos;t do.
          </p>
        </div>
        <ul className="space-y-3 text-secondary-foreground">
          <NotItem icon={EyeOff}>It doesn&apos;t identify anyone or compare faces between photos.</NotItem>
          <NotItem icon={ShieldCheck}>
            It isn&apos;t age verification, and it isn&apos;t suitable for hiring, policing, access
            control, healthcare, or any decision about a person.
          </NotItem>
          <NotItem icon={SlidersHorizontal}>
            &ldquo;Perceived presentation&rdquo; describes how a photo looks to a model. It says
            nothing about someone&apos;s gender identity or sex.
          </NotItem>
          <NotItem icon={Trash2}>It doesn&apos;t keep your photos. There are no accounts and no tracking.</NotItem>
        </ul>
      </section>
    </div>
  );
}

function Step({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <li className="rounded-xl border border-border bg-card p-5">
      <p className="mb-2 flex size-8 items-center justify-center rounded-full bg-primary/10 font-semibold text-primary" aria-hidden="true">
        {n}
      </p>
      <h3 className="font-semibold">
        <span className="sr-only">Step {n}: </span>
        {title}
      </h3>
      <p className="mt-2 text-sm text-muted-foreground">{children}</p>
    </li>
  );
}

function NotItem({ icon: Icon, children }: { icon: typeof Clock; children: React.ReactNode }) {
  return (
    <li className="flex gap-3">
      <Icon className="mt-0.5 size-5 shrink-0" aria-hidden="true" />
      <span>{children}</span>
    </li>
  );
}
