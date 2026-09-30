import Link from "next/link";

import { Logo } from "@/components/site/logo";

const NAV = [
  { href: "/#tools", label: "Tools" },
  { href: "/privacy", label: "Privacy" },
  { href: "/responsible-use", label: "Responsible use" },
  { href: "/model-cards", label: "Model cards" },
];

export function SiteHeader() {
  return (
    <header className="border-b border-border bg-background/95">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-x-6 gap-y-2 px-4 py-3 sm:px-6">
        <Link
          href="/"
          className="flex min-h-11 items-center gap-2 rounded-md font-heading text-xl font-semibold"
        >
          <Logo />
          <span>FaceLens</span>
        </Link>
        <nav aria-label="Main">
          <ul className="flex flex-wrap gap-x-1 text-sm">
            {NAV.map((item) => (
              <li key={item.href}>
                <Link
                  href={item.href}
                  className="inline-flex min-h-11 items-center rounded-md px-3 text-muted-foreground hover:bg-muted hover:text-foreground"
                >
                  {item.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
      </div>
    </header>
  );
}
