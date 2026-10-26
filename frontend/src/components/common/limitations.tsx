import { ShieldAlert } from "lucide-react";

export function Limitations({ notes, title = "Limits of this view" }: { notes: string[]; title?: string }) {
  if (!notes.length) return null;
  return (
    <section className="rounded-2xl border border-border/70 bg-card/40 p-5">
      <h3 className="flex items-center gap-2 text-2xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
        <ShieldAlert className="h-3.5 w-3.5 text-mint-muted" aria-hidden="true" />
        {title}
      </h3>
      <ul className="mt-3 space-y-2 text-sm leading-relaxed text-muted-foreground">
        {notes.map((note) => (
          <li key={note} className="flex gap-2.5">
            <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-mint-muted/60" aria-hidden="true" />
            <span>{note}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
