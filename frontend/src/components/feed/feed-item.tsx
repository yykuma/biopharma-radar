import { cn } from "@/lib/utils";
import { useUrlState } from "@/hooks/use-url-state";
import { getFaviconUrl } from "@/lib/api/favicon";
import type { Feed } from "@/lib/api";
import { FeedFavicon } from "@/components/feed/feed-favicon";

interface FeedItemProps {
  feed: Feed;
}

export function FeedItem({ feed }: FeedItemProps) {
  const { selectedFeedId, setSelectedFeed } = useUrlState();

  const isSelected = selectedFeedId === feed.id;
  const faviconUrl = getFaviconUrl(feed.link, feed.site_url);


  return (
    <div
      className={cn(
        "group flex w-full min-w-0 items-center gap-2 rounded-md px-2 py-1 text-left text-sm transition-colors",
        isSelected ? "bg-accent text-accent-foreground" : "hover:bg-accent/50",
      )}
    >
      <button
        type="button"
        onClick={() => setSelectedFeed(feed.id)}
        className="flex min-w-0 flex-1 items-center gap-2 text-left"
      >
        <FeedFavicon src={faviconUrl} className="h-4 w-4" />
        <span className="block min-w-0 max-w-full flex-1 truncate">
          {feed.name}
        </span>
      </button>
      <div className="ml-2 flex h-6 shrink-0 items-center justify-center">
        <span className="text-[11px] text-muted-foreground">
          {feed.unread_count > 0 ? feed.unread_count : ""}
        </span>

      </div>
    </div>
  );
}
