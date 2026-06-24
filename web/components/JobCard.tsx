"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import type { ShortlistItem } from "@/lib/api";
import { offerLink, scorerLabel } from "@/lib/ui";
import ScoreRing from "./ScoreRing";
import StatusSelect from "./StatusSelect";
import { Icon } from "./icons";

function workplaceLabel(wp: string | null): string {
  if (!wp) return "";
  return wp.replace(/_/g, "-").replace(/\b\w/g, (c) => c.toUpperCase()); // on_site -> On-Site
}

export default function JobCard({
  item,
  onApplied,
}: {
  item: ShortlistItem;
  onApplied?: (jobId: string, next: string, prev: string | null) => void;
}) {
  const router = useRouter();
  const link = offerLink(item);
  const detail = `/job?id=${item.job_id}`;
  const wp = workplaceLabel(item.workplace_type);

  return (
    <article
      role="link"
      tabIndex={0}
      onClick={() => router.push(detail)}
      onKeyDown={(e) => e.key === "Enter" && router.push(detail)}
      className="group flex cursor-pointer flex-col rounded-card border border-transparent bg-surface p-6 shadow-card transition-all hover:border-primary/40 hover:shadow-pop"
    >
      {/* header: title + company · score ring */}
      <div className="mb-4 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="truncate text-lg font-semibold text-on-surface transition-colors group-hover:text-primary">
            {item.title}
          </h3>
          <p className="mt-0.5 flex items-center gap-1.5 text-on-surface-variant">
            <Icon name="building" size={16} className="shrink-0" />
            <span className="truncate">{item.company_name}</span>
          </p>
        </div>
        <div className="flex shrink-0 flex-col items-center gap-1">
          <ScoreRing score={item.score} size={48} />
          {scorerLabel(item.backend) && (
            <span className="whitespace-nowrap text-[10px] font-medium text-on-surface-faint">
              {scorerLabel(item.backend)}
            </span>
          )}
        </div>
      </div>

      {/* chips: workplace + location */}
      {(wp || item.location) && (
        <div className="mb-4 flex flex-wrap gap-2">
          {wp && (
            <span className="inline-flex items-center gap-1 rounded-full bg-surface-sunken px-3 py-1 text-xs font-semibold text-on-surface">
              <Icon name="briefcase" size={14} /> {wp}
            </span>
          )}
          {item.location && (
            <span className="inline-flex items-center gap-1 rounded-full bg-surface-sunken px-3 py-1 text-xs font-semibold text-on-surface">
              <Icon name="map-pin" size={14} /> <span className="max-w-[12rem] truncate">{item.location}</span>
            </span>
          )}
        </div>
      )}

      {/* why it matches */}
      {item.match_reasons && (
        <div className="mb-5 flex-1 rounded-lg border border-border/60 bg-surface-alt p-3">
          <span className="mb-0.5 block text-sm font-medium text-on-surface">Why it matches</span>
          <p className="text-sm text-on-surface-variant">{item.match_reasons}</p>
        </div>
      )}

      {/* actions */}
      <div
        className="mt-auto flex items-center justify-between gap-3 border-t border-border/70 pt-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-3">
          <Link
            href={detail}
            className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-on-primary shadow-sm transition-colors hover:bg-primary-hover"
          >
            View details
          </Link>
          {link && (
            <a
              href={link}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 text-sm font-medium text-on-surface-variant transition-colors hover:text-primary"
            >
              Open posting <Icon name="external" size={14} />
            </a>
          )}
        </div>
        <StatusSelect
          jobId={item.job_id}
          value={item.status}
          onChanged={(next) => onApplied?.(item.job_id, next, item.status ?? null)}
        />
      </div>
    </article>
  );
}
