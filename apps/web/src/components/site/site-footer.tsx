import Link from "next/link";

export function SiteFooter() {
  return (
    <footer className="mt-16 border-t border-border bg-muted/40">
      <div className="mx-auto grid max-w-6xl gap-6 px-4 py-10 text-sm text-muted-foreground sm:grid-cols-[2fr_1fr] sm:px-6">
        <div className="space-y-2">
          <p className="font-medium text-foreground">
            Estimates are uncertain and illustrative. They are not facts about anyone.
          </p>
          <p>
            Not for hiring, policing, access control, healthcare, age verification, or any other
            decision about a person. FaceLens doesn&apos;t identify people or compare faces.
          </p>
        </div>
        <nav aria-label="Footer">
          <ul className="space-y-1">
            <li>
              <Link className="inline-flex min-h-11 items-center underline-offset-4 hover:underline" href="/privacy">
                Privacy and data retention
              </Link>
            </li>
            <li>
              <Link className="inline-flex min-h-11 items-center underline-offset-4 hover:underline" href="/responsible-use">
                Responsible use
              </Link>
            </li>
            <li>
              <Link className="inline-flex min-h-11 items-center underline-offset-4 hover:underline" href="/model-cards">
                Model cards and limitations
              </Link>
            </li>
            <li>
              <Link className="inline-flex min-h-11 items-center underline-offset-4 hover:underline" href="/evaluation">
                Evaluation results
              </Link>
            </li>
          </ul>
        </nav>
      </div>
    </footer>
  );
}
